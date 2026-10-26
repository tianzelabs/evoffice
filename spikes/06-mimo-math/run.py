"""Two bounded, isolated API calls. No office state, tools, or orders involved."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
MODELS = ["xiaomi/mimo-v2.6-pro", "anthropic/claude-haiku-5.5"]
LIMIT = 0.03
MAX_TOKENS = 6000


def request(path, payload=None, authenticated=False):
    cmd = ["curl", "--silent", "--show-error", "--fail-with-body", "--max-time", "300",
           "--config", "-", "https://openrouter.ai/api/v1/" + path]
    config = ""
    if authenticated:
        key = os.environ["OPENROUTER_API_KEY"]
        if any(c in key for c in '\r\n"\\'):
            raise ValueError("Invalid key format")
        config += 'header = "Authorization: Bearer ' + key + '"\n'
    if payload is not None:
        body_path = ROOT / "request.json"
        body_path.write_text(json.dumps(payload))
        cmd += ["--header", "Content-Type: application/json", "--data-binary", "@" + str(body_path)]
    result = subprocess.run(cmd, input=config, text=True, capture_output=True, timeout=310)
    if result.returncode:
        raise RuntimeError("API request failed: " + result.stdout[:400] + result.stderr[:200])
    return json.loads(result.stdout)


def main():
    rescue = sys.argv[1:] == ["--no-thinking-rescue"]
    if sys.argv[1:] and not rescue:
        raise ValueError("Only --no-thinking-rescue is supported")
    models = MODELS
    prompt = (ROOT / "prompt.txt").read_text()
    catalog = {m["id"]: m for m in request("models")["data"]}
    worst_case = 0
    for model in models:
        price = catalog[model]["pricing"]
        # Conservative byte count exceeds the token count of this short ASCII prompt.
        upper = (len(prompt.encode()) + 2048) * float(price["prompt"]) + MAX_TOKENS * float(price["completion"])
        if float(price.get("request", 0)):
            upper += float(price["request"])
        worst_case += upper
    previous_cost = 0.0
    if rescue:
        for model in MODELS:
            saved = json.loads((ROOT / (model.rsplit("/", 1)[-1] + ".json")).read_text())
            previous_cost += float(saved["response"]["usage"]["cost"])
    if worst_case + previous_cost > LIMIT:
        raise RuntimeError(f"Preflight upper bound ${worst_case:.6f} exceeds ${LIMIT}")
    (ROOT / ("rescue-preflight.json" if rescue else "preflight.json")).write_text(json.dumps({"max_total_usd": LIMIT,
        "conservative_cost_bound_usd": worst_case, "max_tokens_per_model": MAX_TOKENS,
        "previous_billed_usd": previous_cost,
        "models": {m: catalog[m]["pricing"] for m in models}}, indent=2))
    print(f"PREFLIGHT bound=${worst_case:.6f}; exactly one request per model; no retries", flush=True)
    total = previous_cost
    for model in models:
        slug = model.rsplit("/", 1)[-1]
        target = ROOT / (slug + ("-no-thinking" if rescue else "") + ".json")
        if target.exists():
            raise RuntimeError("Refusing to overwrite an existing paid result: " + str(target))
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS, "stream": False,
            "response_format": {"type": "json_object"},
            "reasoning": {"enabled": not rescue},
            "provider": {"max_price": {"prompt": float(catalog[model]["pricing"]["prompt"]) * 1e6,
                                       "completion": float(catalog[model]["pricing"]["completion"]) * 1e6}}}
        started = time.monotonic()
        print("START " + model, flush=True)
        data = request("chat/completions", payload, authenticated=True)
        elapsed = time.monotonic() - started
        target.write_text(json.dumps({"requested_model": model, "reasoning_enabled": not rescue, "elapsed_seconds": elapsed,
            "response": data}, ensure_ascii=False, indent=2))
        usage = data.get("usage", {})
        cost = usage.get("cost")
        print(json.dumps({"model": model, "elapsed_seconds": round(elapsed, 2),
            "usage": usage, "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason")}), flush=True)
        if cost is None:
            raise RuntimeError("Missing billed cost; stop rather than make another paid call")
        total += float(cost)
        if total >= LIMIT:
            raise RuntimeError("Test cost limit reached")
    print(f"TOTAL_BILLED_USD {total:.9f}", flush=True)


if __name__ == "__main__":
    main()
