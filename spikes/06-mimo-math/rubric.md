# Frozen before the API calls

This is a one-problem smoke test, not a benchmark ranking or a trading backtest.
Both models receive the same prompt, 6,000 total completion-token cap, and one
request, without tools or retries. Reasoning is enabled. Model implementations
may allocate their reasoning budgets differently. No RLM persistence is tested.

Assess each criterion separately; do not turn them into a claim about general mathematical ability:

1. Conditional Gaussian moments: m=tau^2*s/(tau^2+sigma^2), v=tau^2*sigma^2/(tau^2+sigma^2).
2. Cost and optimizer: soft threshold at |m|=k, then divide excess by lam*v and clip to [-1,1]. Handle lam=0 and objective ties. Establish global optimality by concavity or direct comparison.
3. Requested numerical cases: tau=12, sigma=16 imply m=0.36s and v=92.16. Actions are [-1,-0.1736111111111111,0,0,0,0.1736111111111111,1]. Expected net is a*m-k*abs(a); objective subtracts 0.5*lam*a*a*v.
4. Generated Python: check the seven supplied cases and separate deterministic parameter combinations, including lam=0, zero costs, threshold ties, and negative signals. At ties any global optimizer is acceptable.
5. Non-Gaussian counterexample: must respect independence, means, and variances, and actually contradict the Gaussian conditional calculation/action. One reference: R is equiprobable +/-12, epsilon independent equiprobable +/-16. At S=4, R=-12 surely, whereas the Gaussian predictor is +1.44. With k=8, lam=0.04 the actual optimum is -1 and Gaussian optimum is 0. Covariance fixes the best linear predictor but not conditional means or conditional variances generally.
6. Claims: distinguish conditional expectation, realized outcomes, model validity, and selection bias from testing many variants.

Save raw responses and actual billed usage. Review model code before local execution;
run only the pure numerical functions with limited builtins and a time limit.
