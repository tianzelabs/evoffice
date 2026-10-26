"""Baseline numerical checks defined before receiving model answers.

Imported by the verifier inside an isolated numerical worker. No model calls.
Near-tie control cases added after observing an exact-comparison candidate;
see checks-amendment.json. No checker feedback is sent to either model.
"""
import itertools
import json
import numpy as np


def check_filtering(fn):
    failures = []
    total = 0
    sequences = [[],[2.],[-2.,1.,4.,-.2,3.],np.random.default_rng(2517).normal(size=12).tolist()]
    parameters = [(.95,.04,2.,0.,None),(-.4,.2,1.7,1.5,.3),(0.,1.,2.,-.3,.4),(.8,.5,.2,0.,None)]
    for seq in sequences:
        for args in parameters:
            total += 1
            try:
                actual = fn(seq,*args)
                expected = direct_gaussian_conditioning(seq,*args)
                for key in expected:
                    a,b = np.asarray(actual[key]),np.asarray(expected[key])
                    assert a.shape == b.shape and np.allclose(a,b,rtol=1e-7,atol=1e-8), key
            except Exception as e:
                failures.append({"length":len(seq),"parameters":args,"error":repr(e)})
    return {"cases":total,"passed":total-len(failures),"failures":failures[:10],
            "oracle":"Direct multivariate-normal conditioning; no Kalman recurrence"}


def check_control(fn):
    failures = []
    total = 0
    parameters = [(5,[-3.,6.],[16.,9.],.04,[[.8,.2],[.3,.7]]),
                  (0,[-1.,1.],[1.,1.],0,[[.5,.5],[.5,.5]]),
                  (.2,[.1,.3],[.25,4.],.1,[[1.,0.],[0.,1.]]),
                  (5,[6.,6.],[1.,1.],0,[[.8,.2],[.2,.8]]),
                  (0,[1e-11,1e-11],[1.,1.],0,[[.5,.5],[.5,.5]])]
    for horizon in [0,1,3,7]:
        for args in parameters:
            total += 1
            try:
                actual,expected = fn(horizon,*args),ref_dp(horizon,*args)
                for key in ["values","actions"]:
                    a,b = np.asarray(actual[key]),np.asarray(expected[key])
                    assert a.shape == b.shape and np.allclose(a,b,rtol=1e-8,atol=1e-8), key
                if horizon <= 3:
                    c,mus,variances,lam,transition = args
                    for pi,p in enumerate([-1,0,1]):
                        for z in [0,1]:
                            oracle = recursive_control_value(horizon,p,z,c,mus,variances,lam,transition)
                            assert np.isclose(actual["values"][horizon][pi][z],oracle)
            except Exception as e:
                failures.append({"horizon":horizon,"parameters":args,"error":repr(e)})
    return {"cases":total,"passed":total-len(failures),"failures":failures[:10],
            "oracle":"Reference table plus exhaustive action/state recursion at horizons <=3"}


def check_robust(fn):
    failures = []
    total = 0
    trials = list(itertools.product([-20.,-10.,-2.,0.,2.,10.,20.],[0.,.5,3.],
                                    [0.,1.,10.],[0.,.04,1.],[.25,16.]))
    trials += [(sign*(u+k),u,k,lam,16.) for sign,u,k,lam in
               itertools.product([-1,1],[0.,2.],[0.,8.],[0.,.04])]
    grid = np.linspace(-1,1,10001)
    for args in trials:
        total += 1
        try:
            m,u,k,lam,v = args
            a = float(fn(*args))
            expected = ref_robust(*args)
            assert np.isfinite(a) and -1-1e-10<=a<=1+1e-10
            score = a*m-(u+k)*abs(a)-.5*lam*v*a*a
            exact = expected*m-(u+k)*abs(expected)-.5*lam*v*expected*expected
            assert np.isclose(score,exact,rtol=1e-8,atol=1e-8)
            grid_max = np.max(grid*m-(u+k)*abs(grid)-.5*lam*v*grid*grid)
            assert score >= grid_max-1e-8
            if abs(m)==u+k:
                assert a == 0, "specified no-trade tie convention"
        except Exception as e:
            failures.append({"parameters":args,"error":repr(e)})
    return {"cases":total,"passed":total-len(failures),"failures":failures[:10],
            "oracle":"Exact objective maximum plus independent dense grid maximization"}
