"""Verify frozen submitted functions offline; no paid requests or office tools."""
import json
from pathlib import Path

from run import NumericalRepl

ROOT = Path(__file__).resolve().parent
MODELS = ["mimo-v2.6-pro", "claude-haiku-5.5"]
TASKS = ["filtering", "control", "robust"]


def result_folder(task,model):
    if model == "mimo-v2.6-pro" and (ROOT/"rescue-protocol.json").exists():
        return ROOT/"rescue-results"/task/model
    return ROOT/"results"/task/model


def verify_one(task, model, visible):
    folder = result_folder(task,model)
    status = json.loads((folder/"status.json").read_text())
    complete = bool(status.get("completed") or status.get("answer_recovered"))
    candidate = folder/"candidate-not-final.py"
    if not complete and not candidate.exists():
        return {"task":task,"model":model,"status":status,"verification":"No completed answer to score"}
    code_path = folder/"submitted.py" if complete else candidate
    if not code_path.exists():
        return {"task":task,"model":model,"status":status,"verification":"Missing submitted function"}
    repl = NumericalRepl(visible)
    result = {"task":task,"model":model,"status":status,"source_folder":str(folder.relative_to(ROOT)),
              "source_kind":"final_submission" if complete else "tool_candidate_not_final_answer"}
    try:
        setup = "__file__ = '/reference.py'\n"+(ROOT/"reference.py").read_text()+"\n"+(ROOT/"checks.py").read_text()
        output = repl.execute(setup)
        if not output["ok"]:
            raise ValueError("Reference setup failed: "+str(output))
        code = code_path.read_text()
        loaded = repl.execute(code)
        if not loaded["ok"]:
            result["verification"] = {"submission_load_error":loaded}
            return result
        names = {"filtering":"kalman_filter","control":"solve_dp","robust":"robust_position"}
        checking = repl.execute("print('CHECK_JSON '+json.dumps(check_"+task+"("+names[task]+"),default=str))")
        if not checking["ok"]:
            result["verification"] = {"check_error":checking}
            return result
        result["verification"] = json.loads(checking["stdout"].split("CHECK_JSON ",1)[1])
        if task == "filtering":
            code = '''
R_frozen = float(train.r_bps.dropna().var(ddof=1))
filter_output = []
for _, group in frame.groupby('segment',sort=False):
    group = group.dropna(subset=['r_bps'])
    got = kalman_filter(group.r_bps.tolist(),.95,.04,R_frozen)
    for i,(_,row) in enumerate(group.iterrows()):
        filter_output.append({'m':row.m,'partition':row.partition,'y':row.r_bps,
            'pred_mean':got['pred_mean'][i],'pred_var':got['pred_var'][i]})
filter_frame = pd.DataFrame(filter_output)
empirical_verified = {'R':R_frozen}
for part in ['validation','holdout']:
    f = filter_frame[filter_frame.partition==part]
    covered = abs(f.y-f.pred_mean)<=stats.norm.ppf(.975)*np.sqrt(f.pred_var)
    empirical_verified[part]={'n':len(f),'prediction_mse':float(np.mean((f.y-f.pred_mean)**2)),
        'zero_baseline_mse':float(np.mean(f.y**2)),
        'nominal_prediction_interval_covered':int(covered.sum()),
        'nominal_prediction_coverage':float(covered.mean())}
'''
        elif task == "control":
            code = '''
fit = fitted_control(pairs_train)
got = solve_dp(15,5.,fit['mus'],fit['variances'],.04,fit['transition'])
empirical_verified = {'frozen_train_fit':fit,'values_15':got['values'][15],
    'actions_15':got['actions'][15]}
'''
        else:
            code = '''
fit = fitted_ols(pairs_train)
empirical_verified = {'frozen_train_fit':fit}
for part in ['validation','holdout']:
    p = all_pairs[all_pairs.partition==part]
    x,y = p.x_bps.to_numpy(),p.y_bps.to_numpy()
    m = fit['beta0']+fit['beta1']*x
    u = fit['t_critical']*np.sqrt(fit['residual_variance']*(1/fit['n']+(x-fit['xbar'])**2/fit['sxx']))
    a = np.array([robust_position(mm,uu,10.,.04,fit['residual_variance']) for mm,uu in zip(m,u)])
    metrics = prediction_metrics(p,fit,10.)
    metrics['robust_trade_count'] = int(np.count_nonzero(a))
    metrics['mean_proxy_net_bps_per_opportunity'] = float(np.mean(a*y-10.*abs(a)))
    empirical_verified[part] = metrics
'''
        # all_pairs is supplied only to this offline verifier, after answers freeze.
        pair_setup = "all_pairs=pd.DataFrame("+repr(visible["pairs"])+")\n" if task == "robust" else ""
        output = repl.execute(pair_setup+code+"\nprint('EMPIRICAL_JSON '+json.dumps(empirical_verified,default=lambda x:np.asarray(x).tolist()))")
        if output["ok"]:
            result["verified_empirical"] = json.loads(output["stdout"].split("EMPIRICAL_JSON ",1)[1])
        else:
            result["empirical_execution_error"] = output
        (folder/"verification.json").write_text(json.dumps(result,indent=2))
        return result
    finally:
        repl.close()


def main():
    for task in TASKS:
        for model in MODELS:
            if not (result_folder(task,model)/"status.json").exists():
                raise RuntimeError("Wait for all answers to freeze before offline heldout verification")
    visible = json.loads((ROOT/"data/visible.json").read_text())
    hidden = json.loads((ROOT/"data/holdout.json").read_text())
    visible["rows"] += hidden["rows"]
    visible["pairs"] += hidden["pairs"]
    results = []
    for task in TASKS:
        for model in MODELS:
            result = verify_one(task,model,visible)
            results.append(result)
            checks = result.get("verification")
            print(json.dumps({"task":task,"model":model,"checks":checks},ensure_ascii=False),flush=True)
    (ROOT/"verification.json").write_text(json.dumps(results,indent=2))


if __name__ == "__main__":
    main()
