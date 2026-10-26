import numpy as np, pandas as pd

def solve_dp(horizon, c, mus, variances, lam, transition):
    mus = np.asarray(mus, float); variances = np.asarray(variances, float)
    T = np.asarray(transition, float)
    P = (-1, 0, 1)
    vals = np.zeros((horizon+1, 3, 2))
    acts = np.zeros((horizon+1, 3, 2))
    for pi, p in enumerate(P):
        for z in (0,1):
            vals[0, pi, z] = -c*abs(p)
            acts[0, pi, z] = 0
    for n in range(1, horizon+1):
        for pi, p in enumerate(P):
            for z in (0,1):
                best = None
                for q in P:
                    v = (q*mus[z] - lam*q*q*variances[z]/2.0 - c*abs(q-p)
                         + float(T[z] @ vals[n-1, P.index(q) if False else (q+1)]))
                    key = (-v, abs(q-p), abs(q), q)   # maximize v; ties -> smaller |q-p|,|q|,q
                    if best is None or key < best[0]:
                        best = (key, q, v)
                acts[n, pi, z] = best[1]
                vals[n, pi, z] = best[2]
    return {'values': vals.tolist(), 'actions': acts.tolist()}
