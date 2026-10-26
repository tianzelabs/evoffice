"""Numerical checks only. Inspect the saved model code before invoking this file."""
import ast
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def reference(s, tau, sigma, k, lam):
    m = tau*tau*s/(tau*tau+sigma*sigma)
    v = tau*tau*sigma*sigma/(tau*tau+sigma*sigma)
    excess = abs(m)-k
    a = 0.0 if excess <= 0 else math.copysign(1 if lam == 0 else min(1, excess/(lam*v)), m)
    net = a*m-k*abs(a)
    return a, net, net-0.5*lam*a*a*v


def restricted_import(name, *args, **kwargs):
    if name != "math":
        raise ValueError("Only the math module is allowed")
    return math


def check(path):
    raw = json.loads(path.read_text())
    content = raw["response"]["choices"][0]["message"]["content"]
    if not content:
        return {"model": raw["requested_model"], "file": path.name, "completed": False,
            "finish_reason": raw["response"]["choices"][0].get("finish_reason"),
            "elapsed_seconds": raw["elapsed_seconds"], "usage": raw["response"].get("usage")}
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    answer = json.loads(content)
    code = answer["python"]
    if code.startswith("```"):
        code = code.split("\n", 1)[1].rsplit("```", 1)[0]
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private attribute is not permitted")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module]
            if any(n != "math" for n in names):
                raise ValueError("Unexpected import")
    allowed = {"abs": abs, "min": min, "max": max, "float": float, "int": int,
               "bool": bool, "round": round, "ValueError": ValueError, "TypeError": TypeError,
               "isinstance": isinstance, "all": all, "any": any, "map": map,
               "__import__": restricted_import}
    namespace = {"__builtins__": allowed, "__name__": "model_verification"}
    exec(compile(tree, str(path), "exec"), namespace)
    fn = namespace["choose_position"]
    trials = list(itertools.product([-100., -1., 0., 1., 100.], [.5, 12., 100.],
        [.25, 16., 80.], [0., 1., 8., 50.], [0., .001, .04, 1.]))
    trials.extend((s, 12., 16., 8., .04) for s in [-40, -24, -16, 0, 16, 24, 40])
    for tau, sigma, k, lam in itertools.product([.5, 12.], [.25, 16.], [0., 1., 8.], [0., .04]):
        for sign in [-1, 1]:
            trials.append((sign*k*(tau*tau+sigma*sigma)/(tau*tau), tau, sigma, k, lam))
    failures = []
    for args in trials:
        s, tau, sigma, k, lam = args
        _, _, best = reference(*args)
        try:
            a = fn(*args)
            m = tau*tau*s/(tau*tau+sigma*sigma)
            v = tau*tau*sigma*sigma/(tau*tau+sigma*sigma)
            value = a*m-k*abs(a)-.5*lam*a*a*v
            if not math.isfinite(a) or not -1-1e-12 <= a <= 1+1e-12 or not math.isclose(value, best, abs_tol=1e-8, rel_tol=1e-8):
                failures.append({"args": args, "a": a, "objective": value, "expected_max": best})
        except Exception as e:
            failures.append({"args": args, "error": str(e)})
    requested = []
    cases = {row["s"]: row for row in answer["cases"]}
    for s in [-40, -24, -16, 0, 16, 24, 40]:
        expected = reference(s, 12, 16, 8, .04)
        row = cases[s]
        ok = all(math.isclose(float(row[key]), val, abs_tol=1e-6, rel_tol=1e-6)
            for key, val in zip(["a", "expected_net_bps", "objective_bps"], expected))
        requested.append({"s": s, "passed": ok, "expected": expected, "reported": row})
    return {"model": raw["requested_model"], "file": path.name, "completed": True, "elapsed_seconds": raw["elapsed_seconds"],
        "usage": raw["response"].get("usage"), "code_cases": len(trials),
        "code_passed": len(trials)-len(failures), "code_failures": failures[:10],
        "numeric_cases": requested}


if __name__ == "__main__":
    results = [check(ROOT/(model+suffix+".json")) for suffix in ["", "-no-thinking"]
        for model in ["mimo-v2.6-pro", "claude-haiku-5.5"]]
    (ROOT / "verification.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
