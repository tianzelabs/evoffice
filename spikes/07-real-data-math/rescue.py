"""Recorded serving-route rescue: official Xiaomi + streaming, same math/data."""
import json
import os
from pathlib import Path
import select
import subprocess
import time

import run

ROOT = Path(__file__).resolve().parent


def ledger():
    known, reserved = 0., 0.
    reservations = json.loads((ROOT/"unpriced-reservations.json").read_text())
    for parent in [ROOT/"results",ROOT/"rescue-results"]:
        for p in parent.glob("*/*/call-*.json"):
            if p.name.endswith(".request.json"):
                continue
            response = json.loads(p.read_text())["response"]
            cost = (response.get("usage") or {}).get("cost")
            if cost is None:
                key = str(p.relative_to(ROOT))
                if key not in reservations:
                    raise RuntimeError("Unpriced request without conservative reserve: "+key)
                reserved += reservations[key]["max_cost_usd"]
            else:
                known += float(cost)
    return {"known_billed_usd":known,"unpriced_reserve_usd":reserved,"budget_accounted_usd":known+reserved}


def stream_api(payload,destination):
    payload = dict(payload)
    payload["stream"] = True
    payload["stream_options"] = {"include_usage":True}
    payload["provider"] = {**payload["provider"],"order":["Xiaomi"],"allow_fallbacks":False}
    if payload.get("tool_choice") == "none":
        # Xiaomi advertises no tool_choice=none. Omitting tools entirely has
        # the intended equivalent semantics: final answer without tool access.
        payload.pop("tools",None)
        payload.pop("tool_choice",None)
    body = destination.with_suffix(".request.json")
    body.write_text(json.dumps(payload))
    key = os.environ["OPENROUTER_API_KEY"]
    if any(c in key for c in '\r\n"\\'):
        raise ValueError("Invalid key format")
    config = 'header = "Authorization: Bearer '+key+'"\n'
    started = time.monotonic()
    chunks = []
    proc = subprocess.Popen(["curl","--silent","--show-error","--fail-with-body","--no-buffer",
        "--max-time","1200","--config","-","--header","Content-Type: application/json",
        "--data-binary","@"+str(body),"https://openrouter.ai/api/v1/chat/completions"],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    proc.stdin.write(config)
    proc.stdin.close()
    last_progress = started
    received = 0
    error = None
    with destination.with_suffix(".sse").open("w") as raw:
        while True:
            ready,_,_ = select.select([proc.stdout],[],[],30)
            if not ready:
                print(f"STREAM waiting {destination.parent.parent.name} elapsed={time.monotonic()-started:.0f}s",flush=True)
                if time.monotonic()-started > 1210:
                    proc.kill()
                    error = "Streaming wall-time ceiling"
                    break
                continue
            line = proc.stdout.readline()
            if not line:
                break
            raw.write(line)
            raw.flush()
            received += len(line)
            if line.startswith("data:"):
                value = line[5:].strip()
                if value == "[DONE]":
                    break
                try:
                    chunk = json.loads(value)
                    chunks.append(chunk)
                    if chunk.get("error"):
                        error = str(chunk["error"])
                except ValueError:
                    pass
            if time.monotonic()-last_progress >= 30:
                print(f"STREAM {destination.parent.parent.name} elapsed={time.monotonic()-started:.0f}s received_bytes={received}",flush=True)
                last_progress = time.monotonic()
    rc = proc.wait(timeout=5)
    elapsed = time.monotonic()-started
    content,reasoning = "",""
    tools,details = {},{}
    response = {}
    finish = None
    for chunk in chunks:
        for key in ["id","model","provider","created","usage","system_fingerprint"]:
            if chunk.get(key) is not None:
                response[key] = chunk[key]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            reasoning += delta.get("reasoning") or delta.get("reasoning_content") or ""
            for call in delta.get("tool_calls") or []:
                index = call.get("index",0)
                target = tools.setdefault(index,{"id":"","type":"function","function":{"name":"","arguments":""}})
                if call.get("id") and call["id"] != target["id"]:
                    target["id"] += call["id"]
                for key in ["name","arguments"]:
                    target["function"][key] += (call.get("function") or {}).get(key) or ""
            for block in delta.get("reasoning_details") or []:
                index = block.get("index",0)
                target = details.setdefault(index,{})
                for key,value in block.items():
                    if key in ["text","summary","data","signature"] and isinstance(value,str):
                        target[key] = target.get(key,"")+value
                    else:
                        target[key] = value
    message = {"role":"assistant","content":content or None}
    if reasoning:
        message["reasoning"] = reasoning
    if details:
        message["reasoning_details"] = [details[i] for i in sorted(details)]
    if tools:
        message["tool_calls"] = [tools[i] for i in sorted(tools)]
    response["choices"] = [{"index":0,"message":message,"finish_reason":finish}]
    if error or rc:
        response["transport_error"] = error or proc.stderr.read(1000)
    record = {"elapsed_seconds":elapsed,"transport_returncode":rc,"response":response,
              "serving_rescue":"Official Xiaomi provider, streaming; task/data/token cap unchanged"}
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    temp.replace(destination)
    if error or rc:
        raise RuntimeError("Official streaming route failed; saved raw stream and metadata")
    return response,elapsed


def main():
    initial_path = ROOT/"results/filtering/mimo-v2.6-pro/call-1.json"
    initial = json.loads(initial_path.read_text())
    assert initial["transport_returncode"] == 28
    request = json.loads(initial_path.with_suffix(".request.json").read_text())
    prompt_bound = len(json.dumps(request["messages"]).encode())+len(json.dumps(request["tools"]).encode())+2048
    cost_bound = prompt_bound*.435/1e6 + request["max_tokens"]*.87/1e6
    reservation = {str(initial_path.relative_to(ROOT)):{"max_cost_usd":cost_bound,
        "reason":"600s timeout, no cost receipt; reserve full request price bound, never treat as free"}}
    (ROOT/"unpriced-reservations.json").write_text(json.dumps(reservation,indent=2))
    note = {"reason":"Default non-streaming route timed out after 600s without a usable answer or cost receipt",
        "unchanged":["tasks","data","chronological split","reasoning enabled","32768 completion-token limit","four responses per session"],
        "changed":["pin official Xiaomi provider","streaming transport","1200s transport timeout","omit tools on last response instead of unsupported tool_choice=none"],
        "original_attempt_retained":str(initial_path.relative_to(ROOT)),"original_max_cost_reserved_usd":cost_bound,
        "total_experiment_cost_cap_usd":1.0}
    (ROOT/"rescue-protocol.json").write_text(json.dumps(note,indent=2))
    run.RESULTS = ROOT/"rescue-results"
    run.api = stream_api
    run.billed_so_far = lambda: ledger()["budget_accounted_usd"]
    tasks = json.loads((ROOT/"tasks.json").read_text())
    catalog = {m["id"]:m for m in json.loads((ROOT/"data/model_catalog.json").read_text())["data"]}
    for task in tasks:
        run.session(task,"xiaomi/mimo-v2.6-pro",catalog)
    report = ledger()
    (ROOT/"cost-summary.json").write_text(json.dumps(report,indent=2))
    print("COST_LEDGER "+json.dumps(report),flush=True)


if __name__ == "__main__":
    main()
