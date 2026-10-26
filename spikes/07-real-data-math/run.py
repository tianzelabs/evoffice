"""Bounded native-tool research comparison. Never connects to office write APIs."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MODELS = ["xiaomi/mimo-v2.6-pro", "anthropic/claude-haiku-5.5"]
MAX_TOKENS = 32768
MAX_CALLS = 4
TOTAL_CAP = 1.0
SESSION_CAP = .18


class NumericalRepl:
    def __init__(self, visible=None):
        if visible is None:
            visible = json.loads((ROOT / "data/visible.json").read_text())
        profile = '''(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(deny file-read-data (subpath "/Users") (subpath "/private/tmp") (subpath "/tmp")
 (subpath "/private/var/folders") (subpath "/var/folders") (subpath "/private/var/root"))
'''
        env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "TZ": "UTC",
               "HOME": "/nonexistent"}
        self.proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile,
            sys.executable, "-u", "-c", (ROOT / "worker.py").read_text()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, cwd="/private/tmp", bufsize=1)
        try:
            self.proc.stdin.write(json.dumps(visible) + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            raise RuntimeError("Numerical REPL startup: " + self.proc.stderr.read(2500))
        self.ready = self._read(30)

    def _read(self, timeout):
        readable, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not readable:
            self.close()
            raise TimeoutError("Numerical REPL exceeded its wall-time allowance")
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read(2000)
            raise RuntimeError("Numerical REPL terminated: " + err)
        return json.loads(line)

    def execute(self, code):
        self.proc.stdin.write(json.dumps({"code": code}) + "\n")
        self.proc.stdin.flush()
        return self._read(30)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=5)


def api(payload, destination):
    key = os.environ["OPENROUTER_API_KEY"]
    if any(c in key for c in '\r\n"\\'):
        raise ValueError("Invalid key format")
    body = destination.with_suffix(".request.json")
    body.write_text(json.dumps(payload))
    config = 'header = "Authorization: Bearer ' + key + '"\n'
    started = time.monotonic()
    proc = subprocess.run(["curl", "--silent", "--show-error", "--fail-with-body",
        "--max-time", "600", "--config", "-", "--header", "Content-Type: application/json",
        "--data-binary", "@" + str(body), "https://openrouter.ai/api/v1/chat/completions"],
        input=config, capture_output=True, text=True, timeout=610)
    elapsed = time.monotonic() - started
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = {"transport_error": proc.stderr[:1000], "raw_prefix": proc.stdout[:1000]}
    destination.write_text(json.dumps({"elapsed_seconds": elapsed,
        "transport_returncode": proc.returncode, "response": data}, ensure_ascii=False, indent=2))
    if proc.returncode:
        raise RuntimeError("API transport failed; raw result saved, not retried")
    return data, elapsed


def billed_so_far():
    costs = []
    for p in RESULTS.glob("*/*/call-*.json"):
        if p.name.endswith(".request.json"):
            continue
        data = json.loads(p.read_text())["response"]
        usage = data.get("usage") or {}
        if "cost" not in usage:
            raise RuntimeError("Saved API response has no billed cost; do not spend again: " + str(p))
        costs.append(float(usage["cost"]))
    return sum(costs)


def parse_final(content):
    if not isinstance(content, str):
        raise ValueError("No final content")
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(content)


def session(task, model, catalog, claimed=False):
    folder = RESULTS / task["id"] / model.rsplit("/", 1)[-1]
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "status.json").exists() and not claimed:
        print("SKIP saved session " + str(folder), flush=True)
        return
    if list(folder.glob("call-*.json")):
        raise RuntimeError("Partial session exists; refuse accidental paid rerun")
    manifest = json.loads((ROOT / "data/manifest.json").read_text())
    system = """You are doing mathematical research on a frozen real-data snapshot. You have a persistent isolated Python tool with numpy as np, pandas as pd, scipy.stats as stats, math, json, and scipy. Variables: manifest (data/cost metadata), frame (chronologically sorted train+validation bars), train and validation (DataFrames), pairs_train and pairs_validation (DataFrames of causally aligned x_bps=current one-minute return and y_bps=next one-minute return). Missing r_bps marks a gap/segment start, not zero. Bars contain UTC m and epoch, OHLCV, segment, partition, r_bps; microstructure columns are partially missing. Do not access files/network or attempt to see heldout values. Work only in these variables. Definitions/imports persist across tool calls.
You MUST use Python to calculate real-data results and to check your derivations. Tool stdout is bounded: print compact summaries, not full datasets. Do not claim that code ran unless a successful tool output shows it. Do not search thresholds/variants for profit. You may conclude no evidence to trade. Your final answer must be one JSON object with the requested keys. The python field must contain a self-contained PURE implementation of the requested function (imports/helpers included), with no real-data work at module top level. Report actual executed numerical values and discuss unsupported market assumptions. You have at most four model responses including the final answer, so combine related calculations into a single Python call when practical. On your last response no tools will be available. Never fabricate missing numbers to finish."""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": task["task"] + "\n\nFrozen metadata:\n" + json.dumps(manifest)}]
    tools = [{"type": "function", "function": {"name": "python", "description":
        "Execute Python in the persistent numerical REPL. Print compact actual calculations; no files, network, holdout or orders.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                       "required": ["code"], "additionalProperties": False}}}]
    price = catalog[model]["pricing"]
    session_cost, elapsed_total, tool_errors, n_tools = 0., 0., 0, 0
    state = {"model": model, "task": task["id"], "completed": False,
             "max_tokens": MAX_TOKENS, "reasoning": {"enabled": True}}
    repl = None
    try:
        repl = NumericalRepl()
        for turn in range(1, MAX_CALLS+1):
            input_bound = len(json.dumps(messages).encode()) + len(json.dumps(tools).encode()) + 2048
            effective = dict(price)
            for override in price.get("overrides", []):
                if input_bound >= override["min_prompt_tokens"]:
                    effective.update(override)
            bound = input_bound*float(effective["prompt"]) + MAX_TOKENS*float(effective["completion"])
            if billed_so_far()+bound > TOTAL_CAP or session_cost+bound > SESSION_CAP:
                state["error"] = "Conservative next-request cost bound exceeds experiment/session cap"
                break
            payload = {"model": model, "messages": messages, "tools": tools,
                "tool_choice": "required" if turn == 1 else "none" if turn == MAX_CALLS else "auto",
                "max_tokens": MAX_TOKENS, "stream": False, "reasoning": {"enabled": True},
                "provider": {"max_price": {"prompt": float(effective["prompt"])*1e6,
                                           "completion": float(effective["completion"])*1e6}}}
            print(f"START {task['id']} {model} call={turn} next_bound=${bound:.5f}", flush=True)
            data, elapsed = api(payload, folder / f"call-{turn}.json")
            elapsed_total += elapsed
            usage = data.get("usage") or {}
            if usage.get("cost") is None:
                raise RuntimeError("API returned no billed cost; stop paid testing")
            session_cost += float(usage["cost"])
            if not data.get("choices"):
                raise RuntimeError("API returned no choices")
            choice = data["choices"][0]
            msg = choice["message"]
            print(json.dumps({"task": task["id"], "model": model, "call": turn,
                "seconds": round(elapsed, 2), "finish": choice.get("finish_reason"), "usage": usage}), flush=True)
            state["finish_reason"] = choice.get("finish_reason")
            if choice.get("finish_reason") == "length":
                state["error"] = "Completion ceiling reached; incomplete reasoning, not a scored mathematical answer"
                break
            assistant = {k: msg[k] for k in ["role", "content", "tool_calls", "reasoning", "reasoning_details"] if k in msg}
            messages.append(assistant)
            calls = msg.get("tool_calls") or []
            if calls:
                for call in calls:
                    if call["function"]["name"] != "python":
                        raise ValueError("Unexpected tool name")
                    code = json.loads(call["function"]["arguments"])["code"]
                    output = repl.execute(code)
                    n_tools += 1
                    tool_errors += int(not output["ok"])
                    (folder / f"tool-{n_tools}.json").write_text(json.dumps({"code": code, "result": output}, indent=2))
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(output)})
                    print(f"TOOL {task['id']} {model} #{n_tools} ok={output['ok']}", flush=True)
            else:
                final = parse_final(msg.get("content"))
                (folder / "final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2))
                if isinstance(final.get("python"), str):
                    code = final["python"].strip()
                    if code.startswith("```"):
                        code = code.split("\n", 1)[1].rsplit("```", 1)[0]
                    (folder / "submitted.py").write_text(code + "\n")
                state["completed"] = True
                break
    except Exception as e:
        state["error"] = type(e).__name__ + ": " + str(e)[:500]
    finally:
        if repl is not None:
            repl.close()
        state.update({"cost_usd": session_cost, "api_seconds": elapsed_total,
                      "tool_calls": n_tools, "tool_errors": tool_errors})
        (folder / "status.json").write_text(json.dumps(state, indent=2))
        (folder / "conversation.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2))
        print("SESSION " + json.dumps(state), flush=True)


def main():
    global SESSION_CAP
    if sys.argv[1:] == ["--self-check"]:
        repl = NumericalRepl()
        try:
            print(repl.ready)
            print(repl.execute("print(len(train), len(validation),len(pairs_train)); print('api_key_present', bool(__import__('os').environ.get('OPENROUTER_API_KEY')))"))
            test_path = str(ROOT / "data/holdout.json")
            print(repl.execute("open(" + repr(test_path) + ").read()"))
            print(repl.execute("import socket; socket.create_connection(('127.0.0.1', 9), timeout=1)"))
        finally:
            repl.close()
        return
    tasks = json.loads((ROOT / "tasks.json").read_text())
    catalog = {m["id"]: m for m in json.loads((ROOT / "data/model_catalog.json").read_text())["data"]}
    if sys.argv[1:] == ["--haiku-parallel"]:
        # The original serial process already has MiMo in flight. Claim Haiku
        # sessions before it can reach them; its existing status check skips us.
        # Independent spend caps: MiMo 3*.18 + Haiku 3*.15 = .99 < total $1.
        SESSION_CAP = .15
        for task in tasks:
            folder = RESULTS/task["id"]/MODELS[1].rsplit("/",1)[-1]
            folder.mkdir(parents=True,exist_ok=True)
            with (folder/"status.json").open("x") as f:
                json.dump({"model":MODELS[1],"task":task["id"],"in_progress":True},f)
        for task in tasks:
            session(task,MODELS[1],catalog,claimed=True)
        print(f"TOTAL_BILLED_USD {billed_so_far():.9f}",flush=True)
        return
    if sys.argv[1:]:
        raise ValueError("Unknown argument")
    for task in tasks:
        for model in MODELS:
            session(task, model, catalog)
    print(f"TOTAL_BILLED_USD {billed_so_far():.9f}", flush=True)


if __name__ == "__main__":
    main()
