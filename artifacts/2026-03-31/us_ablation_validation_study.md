# US Validation Study

- period: 2026-01-02 to 2026-03-31
- scenario_set: ablation
- holding_sessions: 5
- recommended_scenario: group_liquidity_only

## Segment Summaries
- baseline: train=0.0627 validate=0.0352 test=-0.0221
- drop_rel_ret_20: train=0.0521 validate=0.0364 test=-0.0287
- drop_rel_ret_60: train=0.0371 validate=0.0090 test=-0.0323
- drop_liquidity: train=0.0685 validate=0.0352 test=-0.0248
- drop_profitability: train=0.0627 validate=0.0352 test=-0.0221
- drop_quality: train=0.0627 validate=0.0352 test=-0.0221
- drop_trend: train=0.0635 validate=0.0419 test=-0.0162
- drop_volatility: train=0.0635 validate=0.0419 test=-0.0254
- drop_drawdown: train=0.0699 validate=0.0174 test=-0.0311
- group_momentum_only: train=0.0716 validate=0.0211 test=-0.0211
- group_quality_only: train=-0.0062 validate=0.0041 test=-0.0307
- group_risk_only: train=0.0014 validate=0.0744 test=-0.0221
- group_liquidity_only: train=-0.0061 validate=-0.0100 test=-0.0125
