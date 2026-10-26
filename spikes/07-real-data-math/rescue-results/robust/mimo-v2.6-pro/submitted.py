import math


def robust_position(mhat, u, k, lam, v):
    '''max_a min_{mu in [mhat-u, mhat+u]} { a*mu - k*|a| - lam*a^2*v/2 }, a in [-1,1].'''
    mhat = float(mhat); u = float(u); k = float(k); lam = float(lam); v = float(v)
    if not math.isfinite(mhat):
        raise ValueError('mhat must be finite')
    for name, val in (('u', u), ('k', k), ('lam', lam), ('v', v)):
        if not math.isfinite(val):
            raise ValueError(name + ' must be finite')
    if u < 0:
        raise ValueError('u must be >= 0')
    if k < 0:
        raise ValueError('k must be >= 0')
    if lam < 0:
        raise ValueError('lam must be >= 0')
    if v <= 0:
        raise ValueError('v must be > 0')

    # Worst-case robust edges (interval endpoint minus round-trip cost).
    R_long = mhat - u - k     # a > 0 branch, worst mu = mhat - u
    R_short = -mhat - u - k   # a < 0 branch, worst mu = mhat + u

    if lam == 0.0:
        # Linear objective: bang-bang; strict positivity required; ties -> 0.
        if R_long > 0.0 and R_long > R_short:
            return 1.0
        if R_short > 0.0 and R_short > R_long:
            return -1.0
        return 0.0

    c = lam * v
    cands = []
    if R_long > 0.0:
        size = min(R_long / c, 1.0)
        cands.append((size * R_long - c * size * size / 2.0, size, 1))
    if R_short > 0.0:
        size = min(R_short / c, 1.0)
        cands.append((size * R_short - c * size * size / 2.0, size, -1))
    if not cands:
        return 0.0
    best = max(val for val, size, sign in cands)
    if best <= 0.0:
        return 0.0
    winners = [cand for cand in cands if cand[0] == best]
    if len(winners) > 1:          # exact no-trade tie between branches
        return 0.0
    val, size, sign = winners[0]
    return float(sign * size)
