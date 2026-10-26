import numpy as np

def robust_position(mhat, u, k, lam, v):
    mhat, u, k, lam, v = float(mhat), float(u), float(k), float(lam), float(v)
    if not all(np.isfinite([mhat, u, k, lam, v])):
        raise ValueError('non-finite input')
    if u < 0 or k < 0 or lam < 0 or v <= 0:
        raise ValueError('need u>=0, k>=0, lam>=0, v>0')
    edge = abs(mhat) - u - k
    if edge <= 0:
        return 0.0  # no-trade tie and inside-threshold region
    s = 1.0 if mhat > 0 else -1.0
    if lam == 0:
        return s * 1.0
    return s * min(1.0, edge / (lam * v))
