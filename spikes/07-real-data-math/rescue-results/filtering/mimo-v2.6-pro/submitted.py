import numpy as np


def kalman_filter(returns, phi, q, r, m0=0.0, p0=None):
    """Causal Kalman filter for r_t = mu_t + eps_t, mu_{t+1} = phi*mu_t + eta_{t+1}.

    Parameters
    ----------
    returns : sequence of float
        Observation series in time order.
    phi : float
        State persistence, abs(phi) < 1.
    q : float
        State-innovation variance Q > 0 (bps^2).
    r : float
        Observation variance R > 0 (bps^2).
    m0 : float
        Initial latent prior mean.
    p0 : float or None
        Initial latent prior variance. If None, uses the stationary
        variance q / (1 - phi**2).

    Returns
    -------
    dict with equal-length lists (one entry per input, same order):
      pred_mean[i], pred_var[i]  -- mean/variance of returns[i] BEFORE seeing it
                                    (pred_var includes observation noise R)
      post_mean[i], post_var[i]  -- posterior mean/variance of mu_i given returns[0..i]
    """
    if not np.isfinite(phi) or abs(phi) >= 1.0:
        raise ValueError("phi must be finite with abs(phi) < 1")
    if not (q > 0.0) or not (r > 0.0):
        raise ValueError("q and r must be positive")
    if p0 is None:
        p0 = q / (1.0 - phi * phi)
    if not (p0 >= 0.0):
        raise ValueError("p0 must be nonnegative")

    pred_mean, pred_var, post_mean, post_var = [], [], [], []
    m, P = float(m0), float(p0)

    for y in returns:
        y = float(y)
        # (2) observation predictive: mean m, variance F = P + R
        F = P + r
        pred_mean.append(m)
        pred_var.append(F)
        # (3) Kalman gain
        K = P / F
        # (4) Gaussian posterior update
        mp = m + K * (y - m)
        Pp = P - K * P          # == P * r / (P + r)
        post_mean.append(mp)
        post_var.append(Pp)
        # (5) time update -> prior for the next observation
        m = phi * mp
        P = phi * phi * Pp + q

    return {
        "pred_mean": pred_mean,
        "pred_var": pred_var,
        "post_mean": post_mean,
        "post_var": post_var,
    }

