"""The strategy version: measured from what the trader defined, never from what it says.

Spike 2: a model reported "should_wake unchanged" while the function's bytecode had
changed. So the office hashes the trader's functions, classes and fitted models
itself. Data and notes are not strategy and do not move the version.
"""
from __future__ import annotations

import hashlib
import pickle


def _code_hash(code) -> bytes:
    """Bytecode + constants, recursing into nested code objects (whose repr carries an address)."""
    h = hashlib.sha256(code.co_code)
    for c in code.co_consts:
        h.update(_code_hash(c) if hasattr(c, "co_code") else repr(c).encode())
    h.update(repr(code.co_names).encode())
    return h.digest()


def strategy_version(ns: dict, own: list[str]) -> tuple[str | None, list[str]]:
    """Hash of the trader's functions, classes and fitted models. Data and notes are not strategy."""
    parts, names = [], []
    for name in own:
        v = ns[name]
        try:
            if hasattr(v, "__code__"):
                parts.append(name.encode() + _code_hash(v.__code__))
            elif isinstance(v, type):
                for attr, f in sorted(vars(v).items()):
                    if hasattr(f, "__code__"):
                        parts.append(f"{name}.{attr}".encode() + _code_hash(f.__code__))
            elif hasattr(v, "predict") or hasattr(v, "predict_proba"):
                parts.append(name.encode() + hashlib.sha256(pickle.dumps(v)).digest())
            else:
                continue
            names.append(name)
        except Exception:
            continue
    if not parts:
        return None, []
    return hashlib.sha256(b"".join(sorted(parts))).hexdigest()[:10], names
