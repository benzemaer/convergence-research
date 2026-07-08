# R0 Known Limitations

R0 closes the candidate state definition and handoff package, but it does not remove data-chain and research-stage limitations. These limitations must remain visible to R1 consumers.

1. D2/D3 formal data_version remains unpublished. The R0 formal run uses an evidence-bound candidate chain, not a D3 formal release.
2. D3-T11 / D3 upstream may still carry warnings. R1 must treat this as a research candidate data-chain constraint when interpreting any R0 state frequency or structure result.
3. The current formal universe is 800 securities, with date range 20160104-20260630.
4. R0-T07 confirmed interval row count is 0 and R0-T10-05 confirmed interval row count is 0. R1 cannot start with confirmed interval outcome analysis for this formal package.
5. The 27-config full-grid is a state candidate grid, not a strategy grid.
6. q=0.10/0.20/0.30, W=120/250/500, and K=2/3/5 are R0 candidate grid values. They are not optimized parameters.
7. R0 does not perform parameter selection, release event definition, future label construction, future return analysis, backtest, portfolio construction, or trade signal generation.
8. R0 can hand off only to R1 existence, frequency, structure, stability, and null-model research. It cannot hand off directly to a trading system.
