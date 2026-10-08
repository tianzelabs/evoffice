"""Spike 1c: confirm the two hypotheses.
Local: did the defining cell itself fail (so nothing was kept)?
Docker: does ONE unpicklable variable (a generator) make every function vanish?
"""
import os

from rlm.environments.docker_repl import DockerREPL
from rlm.environments.local_repl import LocalREPL

os.environ["RLM_DOCKER_WORKSPACE_DIR"] = os.path.expanduser("~/pixel-office-home/spike/ws")

loc = LocalREPL(persistent=True)
r = loc.execute_code("class Book:\n    pass\nprint('class ok')")
print("[local class]", repr(r.stdout.strip()), r.stderr.strip()[-160:])
r = loc.execute_code("def trigger(a, b):\n    return a > b\nprint('def ok')")
r2 = loc.execute_code("print(trigger(2, 1))")
print("[local def then call]", r.stdout.strip(), "|", r2.stdout.strip(), r2.stderr.strip()[-120:])
loc.cleanup()

env = DockerREPL(persistent=True)
env.execute_code("def trigger(a, b):\n    return a > b")
print("[docker fn alone]", env.execute_code("print(trigger(2, 1))").stdout.strip() or "LOST")
env.execute_code("gen = (i for i in range(3))")
print("[docker fn after a generator exists]",
      env.execute_code("print(trigger(2, 1))").stdout.strip() or "LOST")
print("[docker vars now]", env.execute_code("print(sorted(k for k in dir() if not k.startswith('_')))").stdout.strip()[-300:])
env.cleanup()
