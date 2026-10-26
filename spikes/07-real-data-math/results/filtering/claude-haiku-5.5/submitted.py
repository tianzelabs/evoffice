import numpy as np

def kalman_filter(returns, phi, q, r, m0=0.0, p0=None):
    """Causal Kalman filter for local-level model r_t = mu_t + eps_t, mu_{t+1} = phi*mu_t + eta_{t+1}.
    returns: sequence of floats; None or NaN marks a missing observation (no update, transition only).
    Returns dict of same-length lists: pred_mean, pred_var (includes R), post_mean, post_var.
    """
    if not (abs(phi) < 1 and q > 0 and r > 0):
        raise ValueError('need |phi|<1, q>0, r>0')
    n = len(returns)
    if p0 is None:
        p0 = q / (1.0 - phi * phi)
    m, p = float(m0), float(p0)
    pred_mean = [0.0] * n
    pred_var = [0.0] * n
    post_mean = [0.0] * n
    post_var = [0.0] * n
    for i, y in enumerate(returns):
        pred_mean[i] = m
        pred_var[i] = p + r
        if y is None or (isinstance(y, float) and np.isnan(y)):
            mp, pp = m, p
        else:
            k = p / (p + r)
            mp = m + k * (float(y) - m)
            pp = (1.0 - k) * p
        post_mean[i] = mp
        post_var[i] = pp
        m = phi * mp
        p = phi * phi * pp + q
    return dict(pred_mean=pred_mean, pred_var=pred_var, post_mean=post_mean, post_var=post_var)

def run_frame_segments(frame, phi, q, r):
    """Run filter per contiguous segment (reset only at segment boundaries); returns per-row pred_mean/pred_var arrays aligned with frame order."""
    rets = frame['r_bps'].astype(float).values
    seg = frame['segment'].values
    pm = np.full(len(frame), np.nan)
    pv = np.full(len(frame), np.nan)
    for s in pd.unique(seg):
        idx = np.where(seg == s)[0]
        res = kalman_filter([rets[i] for i in idx], phi, q, r)
        pm[idx] = res['pred_mean']
        pv[idx] = res['pred_var']
    return pm, pv
