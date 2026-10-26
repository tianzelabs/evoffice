import numpy as np

def solve_dp(horizon, c, mus, variances, lam, transition):
    P = [-1, 0, 1]
    Q = [-1, 0, 1]
    H = int(horizon)
    V = np.zeros((H + 1, 3, 2))
    A = np.zeros((H + 1, 3, 2))
    for pi, p in enumerate(P):
        for z in range(2):
            V[0, pi, z] = -c * abs(p)
            A[0, pi, z] = 0
    for n in range(1, H + 1):
        for pi, p in enumerate(P):
            for z in range(2):
                cands = []
                for qi, q in enumerate(Q):
                    cont = sum(transition[z][z2] * V[n - 1, qi, z2] for z2 in range(2))
                    val = q * mus[z] - lam * q * q * variances[z] / 2.0 - c * abs(q - p) + cont
                    cands.append((val, qi, q))
                best = max(t[0] for t in cands)
                tied = [t for t in cands if best - t[0] <= 1e-10]
                tied.sort(key=lambda t: (abs(t[2] - p), abs(t[2]), t[2]))
                V[n, pi, z] = tied[0][0]
                A[n, pi, z] = tied[0][2]
    return {'values': V.tolist(), 'actions': A.tolist()}
