# CN Validation Study

- period: 2026-01-02 to 2026-03-31
- scenario_set: ablation
- holding_sessions: 5
- recommended_scenario: group_momentum_only

## Segment Summaries
- baseline: train=0.0033 validate=0.0090 test=-0.0153
- drop_rel_ret_20: train=-0.0062 validate=0.0179 test=-0.0153
- drop_rel_ret_60: train=-0.0156 validate=0.0367 test=-0.0342
- drop_trend: train=0.0038 validate=0.0079 test=-0.0153
- drop_liquidity: train=0.0037 validate=0.0130 test=-0.0153
- drop_profitability: train=0.0046 validate=0.0081 test=0.0132
- drop_volatility: train=0.0044 validate=0.0022 test=-0.0153
- drop_drawdown: train=0.0012 validate=0.0233 test=-0.0142
- group_momentum_only: train=0.0017 validate=0.0139 test=0.0135
- group_quality_only: train=-0.0148 validate=0.0543 test=-0.0337
- group_risk_only: train=-0.0029 validate=0.0363 test=-0.0190
- group_liquidity_only: train=-0.0141 validate=0.0439 test=-0.0008
