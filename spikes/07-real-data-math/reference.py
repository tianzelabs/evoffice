"""Independent reference calculations; never passed to the paid models."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent


def ref_filter(returns, phi, q, r, m0=0., p0=None):
    m = float(m0)
    p = q/(1-phi*phi) if p0 is None else float(p0)
    out = {key: [] for key in ["pred_mean", "pred_var", "post_mean", "post_var"]}
    for y in returns:
        out["pred_mean"].append(m)
        out["pred_var"].append(p+r)
        gain = p/(p+r)
        m = m+gain*(y-m)
        p = (1-gain)*p
        out["post_mean"].append(m)
        out["post_var"].append(p)
        m, p = phi*m, phi*phi*p+q
    return out


def direct_gaussian_conditioning(returns, phi, q, r, m0=0., p0=None):
    """Batch multivariate-normal conditioning, independent of the filter recursion."""
    y = np.asarray(returns, dtype=float)
    n = len(y)
    p0 = q/(1-phi*phi) if p0 is None else p0
    means = np.array([m0*phi**i for i in range(n)])
    latent_var = np.array([phi**(2*i)*p0 + q*sum(phi**(2*j) for j in range(i)) for i in range(n)])
    latent = np.array([[phi**abs(i-j)*latent_var[min(i,j)] for j in range(n)] for i in range(n)])
    observation = latent + r*np.eye(n)
    out = {key: [] for key in ["pred_mean", "pred_var", "post_mean", "post_var"]}
    for i in range(n):
        cov = observation[i, :i]
        pred_m = means[i]+(cov @ np.linalg.solve(observation[:i,:i], y[:i]-means[:i]) if i else 0)
        pred_v = observation[i,i]-(cov @ np.linalg.solve(observation[:i,:i], cov) if i else 0)
        cov = latent[i, :i+1]
        post_m = means[i]+cov @ np.linalg.solve(observation[:i+1,:i+1], y[:i+1]-means[:i+1])
        post_v = latent[i,i]-cov @ np.linalg.solve(observation[:i+1,:i+1], cov)
        for key, value in zip(out, [pred_m,pred_v,post_m,post_v]):
            out[key].append(float(value))
    return out


def ref_dp(horizon, c, mus, variances, lam, transition):
    ps = np.array([-1.,0.,1.])
    mus, variances, transition = np.asarray(mus), np.asarray(variances), np.asarray(transition)
    values = np.zeros((horizon+1,3,2))
    actions = np.zeros((horizon+1,3,2))
    values[0] = (-c*abs(ps))[:,None]
    for n in range(1,horizon+1):
        for pi,p in enumerate(ps):
            for z in range(2):
                scores = ps*mus[z]-.5*lam*ps*ps*variances[z]-c*abs(ps-p)+values[n-1] @ transition[z]
                best = np.max(scores)
                tied = np.flatnonzero(abs(scores-best)<=1e-10)
                qi = min(tied,key=lambda i:(abs(ps[i]-p),abs(ps[i]),ps[i]))
                values[n,pi,z] = scores[qi]
                actions[n,pi,z] = ps[qi]
    return {"values": values.tolist(), "actions": actions.tolist()}


def recursive_control_value(n,p,z,c,mus,variances,lam,transition):
    """Uncached exhaustive action/state recursion for small independent checks."""
    if n == 0:
        return -c*abs(p)
    return max(q*mus[z]-.5*lam*q*q*variances[z]-c*abs(q-p)
        +sum(transition[z][zz]*recursive_control_value(n-1,q,zz,c,mus,variances,lam,transition)
             for zz in range(2)) for q in [-1,0,1])


def ref_robust(mhat,u,k,lam,v):
    excess = abs(mhat)-u-k
    if excess <= 0:
        return 0.
    return float(np.sign(mhat)*(1 if lam == 0 else min(1,excess/(lam*v))))


def fitted_control(pairs):
    z = (pairs.x_bps.to_numpy()>=0).astype(int)
    zz = (pairs.y_bps.to_numpy()>=0).astype(int)
    mus = [float(pairs.y_bps.to_numpy()[z==i].mean()) for i in [0,1]]
    variances = [float(pairs.y_bps.to_numpy()[z==i].var(ddof=1)) for i in [0,1]]
    counts = np.array([np.bincount(zz[z==i],minlength=2) for i in [0,1]])
    transition = counts/counts.sum(axis=1,keepdims=True)
    return {"mus":mus,"variances":variances,"transition":transition.tolist(),"transition_counts":counts.tolist()}


def fitted_ols(pairs):
    x,y = pairs.x_bps.to_numpy(),pairs.y_bps.to_numpy()
    n = len(x)
    xbar = x.mean()
    sxx = np.sum((x-xbar)**2)
    b1 = np.sum((x-xbar)*(y-y.mean()))/sxx
    b0 = y.mean()-b1*xbar
    e = y-b0-b1*x
    v = float(e@e/(n-2))
    contiguous = (np.diff(pairs.epoch)==60)&(np.diff(pairs.segment)==0)
    acf = float(np.corrcoef(e[:-1][contiguous],e[1:][contiguous])[0,1])
    return {"n":n,"beta0":float(b0),"beta1":float(b1),"residual_variance":v,
            "xbar":float(xbar),"sxx":float(sxx),"t_critical":float(stats.t.ppf(.975,n-2)),
            "residual_lag1_correlation":acf,"residual_adjacent_pairs":int(contiguous.sum())}


def prediction_metrics(pairs, fit, k):
    x,y = pairs.x_bps.to_numpy(),pairs.y_bps.to_numpy()
    m = fit["beta0"]+fit["beta1"]*x
    leverage = 1/fit["n"]+(x-fit["xbar"])**2/fit["sxx"]
    u = fit["t_critical"]*np.sqrt(fit["residual_variance"]*leverage)
    prediction_width = fit["t_critical"]*np.sqrt(fit["residual_variance"]*(1+leverage))
    a = np.array([ref_robust(mm,uu,k,.04,fit["residual_variance"]) for mm,uu in zip(m,u)])
    pnl = a*y-k*abs(a)
    return {"n":len(pairs),"prediction_mse":float(np.mean((y-m)**2)),
            "zero_baseline_mse":float(np.mean(y*y)),"robust_trade_count":int(np.count_nonzero(a)),
            "mean_proxy_net_bps_per_opportunity":float(pnl.mean()),
            "nominal_prediction_interval_covered":int(np.sum(abs(y-m)<=prediction_width)),
            "max_abs_predicted_mean_bps":float(np.max(abs(m))),
            "max_mean_interval_half_width_bps":float(u.max()),"k_fee_only_bps":k}


def reference_summary():
    visible = json.loads((ROOT/"data/visible.json").read_text())
    holdout = json.loads((ROOT/"data/holdout.json").read_text())
    frame = pd.DataFrame(visible["rows"]+holdout["rows"])
    pairs = pd.DataFrame(visible["pairs"]+holdout["pairs"])
    train = frame[frame.partition=="train"]
    pairs_train = pairs[pairs.partition=="train"]
    r = float(train.r_bps.dropna().var(ddof=1))
    filter_rows = []
    for _,segment in frame.groupby("segment",sort=False):
        segment = segment.dropna(subset=["r_bps"])
        result = ref_filter(segment.r_bps,.95,.04,r)
        for i,(_,row) in enumerate(segment.iterrows()):
            filter_rows.append({"m":row.m,"partition":row.partition,"y":row.r_bps,
                                **{key:result[key][i] for key in result}})
    filtered = pd.DataFrame(filter_rows)
    control_fit = fitted_control(pairs_train)
    control_table = ref_dp(15,5,control_fit["mus"],control_fit["variances"],.04,control_fit["transition"])
    ols = fitted_ols(pairs_train)
    summary = {"filtering":{"phi":.95,"Q":.04,"R":r},
        "control":{**control_fit,"horizon":15,"c":5,"lam":.04,
                   "values_15":control_table["values"][15],"actions_15":control_table["actions"][15]},
        "robust":{"fit":ols}}
    for partition in ["validation","holdout"]:
        f = filtered[filtered.partition==partition]
        yf,pred,pv = f.y.to_numpy(),f.pred_mean.to_numpy(),f.pred_var.to_numpy()
        covered = abs(yf-pred)<=stats.norm.ppf(.975)*np.sqrt(pv)
        summary["filtering"][partition] = {"n":len(f),"prediction_mse":float(np.mean((yf-pred)**2)),
            "zero_baseline_mse":float(np.mean(yf*yf)),"nominal_prediction_interval_covered":int(covered.sum()),
            "nominal_prediction_coverage":float(covered.mean()),
            "last_five":f.tail(5).drop(columns=["partition"]).to_dict(orient="records")}
        p = pairs[pairs.partition==partition]
        z = (p.x_bps.to_numpy()>=0).astype(int)
        pred = np.asarray(control_fit["mus"])[z]
        summary["control"][partition] = {"n":len(p),
            "prediction_mse":float(np.mean((p.y_bps-pred)**2)),
            "zero_baseline_mse":float(np.mean(p.y_bps**2))}
        summary["robust"][partition] = prediction_metrics(p,ols,10)
    return summary


def self_checks():
    for phi,q,r,m0,p0 in [(.95,.04,2.,0.,None),(-.4,.2,1.7,1.5,.3),(0.,1.,2.,-.3,.4)]:
        ys = [-2.,1.,4.,-.2,3.]
        recursive = ref_filter(ys,phi,q,r,m0,p0)
        direct = direct_gaussian_conditioning(ys,phi,q,r,m0,p0)
        for key in recursive:
            assert np.allclose(recursive[key],direct[key],rtol=1e-9,atol=1e-9), key
    table = ref_dp(3,5,[-3.,6.],[16.,9.],.04,[[.8,.2],[.3,.7]])
    for n in range(4):
        for pi,p in enumerate([-1,0,1]):
            for z in [0,1]:
                exhaustive = recursive_control_value(n,p,z,5,[-3.,6.],[16.,9.],.04,[[.8,.2],[.3,.7]])
                assert np.isclose(table["values"][n][pi][z],exhaustive)
    grid = np.linspace(-1,1,20001)
    for m,u,k,lam,v in [(12,1,10,.04,16),(-12,1,10,.04,16),(2,1,1,0,16),(0,0,0,0,16)]:
        a = ref_robust(m,u,k,lam,v)
        score = a*m-(u+k)*abs(a)-.5*lam*v*a*a
        scores = grid*m-(u+k)*abs(grid)-.5*lam*v*grid*grid
        assert score >= scores.max()-1e-9


if __name__ == "__main__":
    self_checks()
    summary = reference_summary()
    (ROOT/"reference-summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
