"""Persistent numerical REPL. Launched with no key, no network, and no user-file access."""
import contextlib
import io
import json
import math
import resource
import sys
import traceback

import numpy as np
import pandas as pd
import scipy
from scipy import stats

resource.setrlimit(resource.RLIMIT_CPU, (90, 95))
resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
source = json.loads(sys.stdin.readline())
frame = pd.DataFrame(source["rows"])
pairs = pd.DataFrame(source["pairs"])
ns = {"__name__": "research_repl", "np": np, "pd": pd, "stats": stats,
      "math": math, "json": json, "scipy": scipy,
      "manifest": source["manifest"], "frame": frame,
      "train": frame[frame.partition == "train"].copy(),
      "validation": frame[frame.partition == "validation"].copy(),
      "pairs_train": pairs[pairs.partition == "train"].copy(),
      "pairs_validation": pairs[pairs.partition == "validation"].copy()}
protocol_out = sys.stdout
print(json.dumps({"ready": True, "train": len(ns["train"]), "validation": len(ns["validation"])}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    output, errors = io.StringIO(), io.StringIO()
    ok = True
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        try:
            exec(request["code"], ns, ns)
        except BaseException:
            ok = False
            traceback.print_exc()
    result = {"ok": ok, "stdout": output.getvalue()[:12000], "stderr": errors.getvalue()[:3000]}
    protocol_out.write(json.dumps(result, default=str) + "\n")
    protocol_out.flush()
