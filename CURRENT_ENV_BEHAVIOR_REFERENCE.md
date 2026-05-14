# Current Env Behavior Reference

This file documents the current live `.env` behavior for backtesting and analysis.

Source of truth:

- Live values come from `C:\Users\mobry\OneDrive\Desktop\CHATBRAIN HISTORY\BACKTEST\CURRENTENV.md`.
- Defaults come from `kalshi_bot/config/settings.py`, mainly `DEFAULT_*` constants and `load_settings()`.
- Runtime behavior comes from `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/risk/risk_manager.py`, and `kalshi_bot/runner/orchestrator.py`.
- Settings are loaded into `KalshiSettings` at process startup. Changing any listed env value requires a runner restart. Restarting also resets in-memory live pacing counters, fast-scan cooldown state, ITM persistence, and live-entry memory.

## Category Legend

Affected category labels used below:

- `scanner/bias`: bias ingestion, scanner eligibility, scanner ranking, or scanner diagnostics.
- `quiet`: quiet continuation path.
- `early`: early momentum confirmation.
- `exhaustion`: exhaustion guard.
- `EV`: expected-value filter.
- `composite`: composite quality filter.
- `reversal`: reversal-specific entry logic.
- `cross/bps`: needs-cross and required-bps logic.
- `segment`: segment/end-window pacing.
- `product pacing`: per-product and per-session entry limits.
- `risk`: stake sizing, exposure, and position limits.
- `submission`: live order safety or submission.
- `exit`: profit capture or trailing stop exits.
- `logs`: diagnostics only.
- `discovery`: market discovery.

## How a Candidate Passes From Scanner to Live Order

1. The runner ingests Kalshi and crypto feed state, builds a `BiasSnapshot`, and scans mapped markets with `ContractScanner.scan()`.
2. Scanner rejects stale markets, missing/neutral/weak bias, late expansion, unconfirmed impulse, impossible target feasibility, and trend exhaustion. Ranked candidates get a score from confidence plus bid/ask/liquidity/volume.
3. If `LIVE_QUIET_CONTINUATION_ENABLED=true`, a neutral chop/exhaustion bias can be converted into a trend-like quiet continuation candidate only when it is ITM, needs no cross, stays under required-bps and recent-move thresholds, and passes quiet signal blocks.
4. Scanner annotates each ranked or skipped contract with exhaustion, early momentum, range expansion, deceleration, near-extreme, and reversal diagnostics.
5. `LiveExecutionCoordinator.process_contract_scan_snapshot()` walks ranked contracts and applies live gates: direction, price, stale ticker, reversal cross-hold, end-window timing, segment pacing, flip/retry persistence, EV filter, product/session pacing, risk sizing, mid-price confirmation, execution safety, count, composite quality, and intent creation.
6. EV-eligible candidates can bypass some timing/composite/pacing blockers when the relevant EV and conditional override settings allow it.
7. Risk sizing uses `RiskManager.evaluate_entry_risk()` with live stake/exposure limits. Order submission then uses `RiskManager.evaluate_live_order()`.
8. Normal live runner submission uses `_live_runner_risk_manager_from_settings()`, which forces `live_validation_enabled=True` and `live_validation_env="prod"` for runner live execution. It still respects `LIVE_TRADING_ENABLED`, `LIVE_KILL_SWITCH_ACTIVE`, `LIVE_MAX_CONTRACT_COUNT`, `LIVE_MIN_STAKE_DOLLARS`, `LIVE_MAX_STAKE_DOLLARS`, `LIVE_MAX_OPEN_POSITIONS`, `LIVE_MAX_EXPOSURE_DOLLARS`, and the required time-in-force.

## Per-Variable Reference

All rows below are variables present in the current live `CURRENTENV.md`.

| Variable | Default if unset | Live value | Example/settings value | Read path | Controls | Role | Affects | Interactions | Restart | Common log/block reasons |
|---|---:|---:|---:|---|---|---|---|---|---|---|
| `LATENCY_DIAGNOSTICS_ENABLED` | `false` | `true` | example `false` | `settings.load_settings`; runner latency diagnostics setup | Enables spot/orderbook latency diagnostics. | logs | logs | Uses sample interval, min spot move, max depth. | yes | None directly; diagnostic records only. |
| `LATENCY_DIAGNOSTICS_SAMPLE_INTERVAL_MS` | `1000` | `1000` | example `1000` | `settings.load_settings`; latency diagnostics | Minimum sample interval. | logs | logs | Used only when latency diagnostics enabled. | yes | None directly. |
| `LATENCY_DIAGNOSTICS_MIN_SPOT_MOVE_BPS` | `5` | `5` | example `5` | `settings.load_settings`; latency diagnostics | Minimum spot move for latency samples. | logs | logs | Used only when latency diagnostics enabled. | yes | None directly. |
| `LATENCY_DIAGNOSTICS_MAX_DEPTH_LEVELS` | `3` | `3` | example `3` | `settings.load_settings`; latency diagnostics | Orderbook depth levels included in diagnostics. | logs | logs | Used only when latency diagnostics enabled. | yes | None directly. |
| `LIVE_QUIET_CONTINUATION_ENABLED` | `false` | `true` | example `false` | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner.scan()` | Enables neutral chop/exhaustion to be reinterpreted as quiet continuation trend candidates. | allows/scores/logs | scanner/bias, quiet, cross/bps | Requires neutral bias, quiet target feasibility, no cross, required bps <= `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`, and quiet thresholds. | yes | `quiet_continuation_*`, `neutral_bias`. |
| `LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED` | `false` | `true` | example `false` | `settings.load_settings`; runner cycle logging; `_live_candidate_funnel_summary_payload()` | Adds detailed candidate funnel diagnostics to cycle/live logs. | logs | logs | Does not change eligibility; increases diagnostic payload detail. | yes | None; logs `candidate_funnel_diagnostics`. |
| `LIVE_WEAK_MOMENTUM_STABILIZATION_MIN_DISTANCE` | unset | unset | example blank | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._weak_momentum_stabilization_status()` | Minimum negative ITM distance required for weak-momentum stabilization. | allows/scores/logs | scanner/bias, quiet, cross/bps, logs | Active only when this, `LIVE_WEAK_MOMENTUM_MAX_RANGE`, and `LIVE_WEAK_MOMENTUM_MAX_PRICE` are all set; requires ITM/no-cross and does not bypass EV, pacing, risk, or execution safety. | yes | `weak_momentum_stabilization_distance_not_deep_enough_itm`; logs `weak_momentum_stabilization_*`. |
| `LIVE_WEAK_MOMENTUM_MAX_RANGE` | unset | unset | example blank | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._weak_momentum_stabilization_status()` | Max recent 5m range allowed for weak-momentum stabilization. | allows/scores/logs | scanner/bias, quiet, exhaustion, logs | Prevents stable-hold promotion during expanded range; future product-specific overrides can plug into product threshold resolver. | yes | `weak_momentum_stabilization_recent_5m_range_too_large`; logs `weak_momentum_stabilization_*`. |
| `LIVE_WEAK_MOMENTUM_MAX_PRICE` | unset | unset | example blank | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._weak_momentum_stabilization_status()` | Max scanner midpoint/entry price eligible for weak-momentum stabilization. | allows/scores/logs | scanner/bias, quiet, submission, logs | Keeps stabilization from lifting expensive dead moves; EV and execution price caps still apply later. | yes | `weak_momentum_stabilization_entry_price_above_limit`; logs `weak_momentum_stabilization_*`. |
| `LIVE_MINI_EXHAUSTION_ENABLED` | `false` | `false` | example `false` | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._mini_exhaustion_status()` | Enables conservative mini-exhaustion diagnostics and scanner confidence downgrade. | scores/logs | scanner/bias, exhaustion, logs | Does not hard-block by itself; requires small/moderate 3m move, recent spike, elevated 5m range, and near-strike distance. | yes | Scanner downgrade `mini_exhaustion`; logs `mini_exhaustion_*`. |
| `LIVE_MINI_EXHAUSTION_3M_BPS` | `12` | `12` | example `12` | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._mini_exhaustion_status()` | Max aligned 3m move considered small/moderate for mini-exhaustion. | scores/logs | scanner/bias, exhaustion, logs | Used only when mini-exhaustion is enabled; future product-specific overrides can plug into product threshold resolver. | yes | `mini_exhaustion_status=flagged` when paired with other mini-exhaustion conditions. |
| `LIVE_MINI_EXHAUSTION_RANGE_BPS` | `25` | `25` | example `25` | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._mini_exhaustion_status()` | Minimum recent 5m range required to flag mini-exhaustion. | scores/logs | scanner/bias, exhaustion, logs | Elevated range must coincide with recent spike and near-strike distance; no EV/risk bypass. | yes | `mini_exhaustion_reason=near_strike_recent_spike_elevated_range`. |
| `LIVE_MINI_EXHAUSTION_RECENT_BPS` | `6` | `6` | example `6` | `settings.load_settings`; `scanner_live_settings_kwargs`; `ContractScanner._mini_exhaustion_status()` | Minimum aligned recent spike required to flag mini-exhaustion. | scores/logs | scanner/bias, exhaustion, logs | Conservative downgrade only; avoids broad May 12-only hard blocking. | yes | Scanner downgrade `mini_exhaustion`; logs `mini_exhaustion_*`. |
| `LIVE_BIAS_RECENT_RETURN_MIN` | unset | unset | example blank | `settings.load_settings`; `BiasEngine.from_settings`; `classify_bias_state()` | Optional minimum recent return for mild aligned slow-trend bias relaxation. | allows/classifies/logs | scanner/bias | Active only with `LIVE_BIAS_LOOKBACK_RETURN_MIN`; does not remove neutral bias or activate reversals. | yes | `classification_reason=bias_relaxed_aligned_slow_trend`. |
| `LIVE_BIAS_LOOKBACK_RETURN_MIN` | unset | unset | example blank | `settings.load_settings`; `BiasEngine.from_settings`; `classify_bias_state()` | Optional minimum lookback return for mild aligned slow-trend bias relaxation. | allows/classifies/logs | scanner/bias | Active only with `LIVE_BIAS_RECENT_RETURN_MIN`; future product-specific overrides can plug into bias threshold resolver. | yes | `classification_reason=bias_relaxed_aligned_slow_trend`. |
| `LIVE_MIN_CROSS_DISTANCE_BPS` | `0` | `0` | example `0` | `settings.load_settings`; `scanner_live_settings_kwargs`; `_target_feasibility()`; `_needs_cross_status()` via scanner output | Optional tiny-cross/noise threshold. | allows/logs | cross/bps, scanner/bias, EV, composite, logs | `0` preserves strict needs-cross. When >0, only crosses at or below the threshold are treated as `noise_cross_ignored`; larger needs-cross entries remain blocked. | yes | `feasibility_status=noise_cross_ignored`; otherwise existing `needs_cross_blocked`. |
| `LIVE_QUIET_CONTINUATION_MAX_RECENT_BPS` | `6` | `6` | example `6` | `ContractScanner._quiet_continuation_signal_block_reason()` | Max absolute latest/recent move allowed for quiet continuation. | blocks/allows | quiet, scanner/bias | Active only when quiet continuation enabled. | yes | `quiet_continuation_recent_move_too_large`, `quiet_continuation_recent_opposite`. |
| `LIVE_QUIET_CONTINUATION_MAX_3M_ABS_BPS` | `12` | `12` | example `12` | `ContractScanner._quiet_continuation_signal_block_reason()` | Max aligned 3m move for quiet continuation. | blocks/allows | quiet | Works with strict-product exhaustion burst logic indirectly through deceleration. | yes | `quiet_continuation_3m_burst_too_large`. |
| `LIVE_QUIET_CONTINUATION_MAX_5M_ABS_BPS` | `20` | `20` | example `20` | `ContractScanner._quiet_continuation_signal_block_reason()` | Max aligned 5m move for quiet continuation. | blocks/allows | quiet | Separate from 5m range expansion threshold. | yes | `quiet_continuation_5m_burst_too_large`. |
| `LIVE_QUIET_CONTINUATION_MAX_5M_RANGE_BPS` | `25` | `25` | example `25` | `ContractScanner._quiet_continuation_signal_block_reason()` | Max 5m range for quiet continuation. | blocks/allows | quiet | Prevents quiet entries during expanded range. | yes | `quiet_continuation_range_expanded`. |
| `LIVE_QUIET_CONTINUATION_BLOCK_DECELERATION` | `true` | `true` | example `true` | `ContractScanner._quiet_continuation_signal_block_reason()` | Blocks quiet continuation after burst deceleration. | blocks | quiet, exhaustion | Uses exhaustion burst thresholds and deceleration threshold. | yes | `quiet_continuation_decelerating_after_burst`. |
| `LIVE_QUIET_CONTINUATION_BLOCK_NEAR_EXTREME` | `true` | `true` | example `true` | `ContractScanner._quiet_continuation_signal_block_reason()` | Blocks quiet continuation near recent extreme. | blocks | quiet, scanner/bias | Uses `LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS`. | yes | `quiet_continuation_near_recent_extreme`. |
| `LIVE_QUIET_CONTINUATION_MIN_DISTANCE_FROM_EXTREME_BPS` | `5` | `5` | example `5` | `ContractScanner._quiet_continuation_signal_block_reason()` | Distance threshold for near-extreme quiet block. | blocks | quiet | Active when near-extreme block enabled. | yes | `quiet_continuation_near_recent_extreme`. |
| `LIVE_EXHAUSTION_GUARD_ENABLED` | `true` | `true` | example `true` | `ContractScanner._signal_quality_fields()`; `_exhaustion_skip_reason()`; `_ev_filter_status()` | Enables exhaustion status and scanner skip for exhausted ITM trend entries. | blocks/logs | scanner/bias, exhaustion, EV | Also affects early momentum and EV exhaustion block. Progression override can only downgrade a base block to caution when separately enabled and strict ITM/no-cross continuation evidence passes. | yes | `exhaustion_guard_blocked`, `ev_exhaustion_blocked`. |
| `LIVE_EXHAUSTION_BURST_3M_BPS` | `20` | `20` | example `20` | `ContractScanner._product_exhaustion_burst_3m()` | Normal-product 3m burst threshold for deceleration exhaustion. | blocks/logs | exhaustion, scanner/bias | Overridden by strict threshold for products in `LIVE_EXHAUSTION_STRICT_PRODUCTS`. | yes | `exhaustion_guard_blocked`; diagnostic `momentum_deceleration_status=decelerating_after_burst`. |
| `LIVE_EXHAUSTION_BURST_5M_BPS` | `30` | `30` | example `30` | `ContractScanner._range_expansion_status()` | 5m range expansion threshold. | blocks/logs | exhaustion, scanner/bias | Blocks only when range expanded and near extreme. | yes | `exhaustion_guard_blocked`; diagnostic `range_expansion_status=expanded`. |
| `LIVE_EXHAUSTION_NEAR_EXTREME_BPS` | `3` | `3` | example `3` | `ContractScanner._near_recent_extreme()` | Near-recent-high/low threshold for exhaustion. | blocks/logs | exhaustion | Combines with 5m expanded range. | yes | `exhaustion_guard_blocked`; diagnostic `late_entry_risk_status=near_recent_extreme`. |
| `LIVE_EXHAUSTION_DECELERATION_RECENT_BPS` | `8` | `8` | example `8` | `ContractScanner._momentum_deceleration_status()` | Recent move threshold used to classify deceleration after burst. | blocks/logs | exhaustion, quiet | Used by exhaustion and quiet deceleration block. | yes | `exhaustion_guard_blocked`, `quiet_continuation_decelerating_after_burst`. |
| `LIVE_EXHAUSTION_STRICT_PRODUCTS` | `HYPE-USD,ETH-USD,XRP-USD` | `ETH-USD,HYPE-USD,XRP-USD,SOL-USD` | example `HYPE-USD,ETH-USD,XRP-USD` | `settings.load_settings`; `ContractScanner._product_exhaustion_burst_3m()` | Products using stricter 3m burst threshold. | blocks/logs | exhaustion, scanner/bias | Uses `LIVE_EXHAUSTION_STRICT_BURST_3M_BPS` instead of normal threshold. | yes | Same exhaustion/quiet deceleration reasons. |
| `LIVE_EXHAUSTION_STRICT_BURST_3M_BPS` | `15` | `15` | example `15` | `ContractScanner._product_exhaustion_burst_3m()` | Strict-product 3m burst threshold. | blocks/logs | exhaustion | Active only for strict products. | yes | `exhaustion_guard_blocked`. |
| `LIVE_EXHAUSTION_PROGRESSION_OVERRIDE_ENABLED` | `false` | unset/false unless explicitly enabled | example `false` | `settings.load_settings`; runner progression context; `ContractScanner._signal_quality_fields()` | Enables default-off progression-aware review of candidates that the base exhaustion guard would hard-block. | allows/logs | scanner/bias, exhaustion, EV, logs | Can only convert `exhaustion_status=blocked` into `progression_caution` for trend candidates that are already ITM/no-cross, require non-positive bps, have repeated aligned trend context, non-accelerating range, and no worsening near-extreme behavior. EV, needs-cross, pacing, risk, pricing, and execution safety still run normally. | yes | `exhaustion_guard_decision=overridden_to_caution`, `exhaustion_progression_*`. |
| `LIVE_EXHAUSTION_PROGRESSION_MIN_ALIGNED_CYCLES` | `2` | `2` unless explicitly changed | example `2` | `settings.load_settings`; `ContractScanner._signal_quality_fields()` | Minimum aligned normal-cycle samples, including current scan, needed before progression can downgrade an exhaustion block. | allows/logs | exhaustion, scanner/bias, logs | Fast scans do not add progression samples; they can only read the latest normal-cycle context. | yes | `exhaustion_progression_reason=insufficient_aligned_progression_samples`. |
| `LIVE_EARLY_MOMENTUM_ENABLED` | `true` | `true` | example `true` | `ContractScanner._early_momentum_status()`; `_mid_price_confirmation_status()` | Enables early momentum diagnostic and mid-price confirmation bypass. | allows/logs | early, scanner/bias, submission | Requires trend, recent momentum >= min, 3m burst <= max, exhaustion not blocked, and entry price <= max. | yes | `mid_price_confirmation_required`; diagnostics `early_momentum_status=*`. |
| `LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS` | `15` | `15` | example `15` | `ContractScanner._early_momentum_status()` | Minimum aligned recent move for early momentum confirmation. | allows/logs | early | Used only when early momentum enabled. | yes | `early_momentum_status=recent_momentum_too_weak`. |
| `LIVE_EARLY_MOMENTUM_MAX_3M_BURST_BPS` | `20` | `20` | example `20` | `ContractScanner._early_momentum_status()` | Maximum aligned 3m burst for early momentum. | blocks/logs | early, exhaustion | Prevents burst-chasing early momentum. | yes | `early_momentum_status=three_minute_burst_too_large`. |
| `LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE` | `0.50` | `0.50` | example `0.50` | `_mid_price_confirmation_status()` | Max executable entry price eligible for early-momentum mid-price confirmation bypass. | allows/blocks | early, submission | Needs `early_momentum_status=confirmed` and exhaustion not blocked. | yes | `mid_price_confirmation_required`. |
| `LIVE_EV_MAX_ACTUAL_COST` | `0.70` | `0.70` | example `0.70` | `_ev_filter_status()` | Max actual order cost accepted by EV filter. | blocks/allows | EV | Checked after candidate A/B match. | yes | `ev_actual_cost_above_limit`. |
| `LIVE_EV_MIN_REWARD_DOLLARS` | `0.30` | `0.30` | example `0.30` | `_ev_filter_status()` | Minimum `1 - cost_price` reward accepted by EV filter. | blocks/allows | EV | Tightens entries near high prices. | yes | `ev_reward_below_limit`. |
| `LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE` | `true` | `true` | example `true` | `_ev_filter_status()` | Requires probability minus actual cost to be non-negative. | blocks/allows | EV | Uses candidate A/B probabilities and actual cost. | yes | `ev_negative_cost_expected_value`. |
| `LIVE_EV_EXHAUSTION_BLOCK_ENABLED` | `true` | `true` | example `true` | `_ev_filter_status()` | Blocks EV candidates when scanner exhaustion status is blocked. | blocks | EV, exhaustion | Depends on exhaustion guard diagnostics. | yes | `ev_exhaustion_blocked`. |
| `LIVE_EV_FILTER_ENABLED` | `true` | `true` | example `true` | `_ev_filter_status()`; `process_contract_scan_snapshot()` | Enables EV candidate filter before risk/composite. | blocks/allows | EV, product pacing, segment, composite | EV eligibility can enable timing/composite/pacing overrides. | yes | `ev_filter_blocked`, `product_blocklisted`, `needs_cross_blocked`, `required_bps_per_minute_too_high`. |
| `LIVE_MIN_EXPECTED_VALUE` | `0.00` | `0.00` | example `0.00` | `_ev_filter_status()` | Minimum probability edge over market probability price. | blocks/allows/scores | EV | Uses candidate A/B probability minus market probability price. | yes | `ev_filter_blocked`, `candidate_not_matched`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | `0.70` | `0.60` | example `0.50` | `_ev_filter_status()` | Max market probability price for ITM/no-cross EV candidates. | blocks/allows | EV | Used for current EV entry price limit. | yes | `ev_filter_blocked`, `missing_entry_price_within_limit`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_BTC` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional BTC-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Overrides only BTC EV entry price cap when set; all EV, needs-cross, exhaustion, reward, cost, liquidity, pacing, and risk gates still apply. | yes | `ev_filter_blocked`, `missing_entry_price_within_limit`; logs `ev_product_price_cap_source=product:BTC-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_DOGE` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional DOGE-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Overrides only DOGE EV entry price cap when set; all existing EV and live safety gates still apply. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:DOGE-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_ETH` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional ETH-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Overrides only ETH EV entry price cap when set; intended for validated product caution without dynamic EV rewrite. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:ETH-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_SOL` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional SOL-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Overrides only SOL EV entry price cap when set; does not change segment/risk/pacing behavior. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:SOL-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_XRP` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional XRP-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Supports stricter XRP cap when validated; no reversal or needs-cross relaxation. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:XRP-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_HYPE` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional HYPE-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Supports stricter HYPE cap when validated; stacks with existing HYPE needs-cross caution and exhaustion rules. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:HYPE-USD`. |
| `LIVE_EV_PRICE_MAX_ITM_NO_CROSS_BNB` | unset; falls back to `LIVE_EV_PRICE_MAX_ITM_NO_CROSS` | unset | example blank | `settings.load_settings`; `_ev_price_max_itm_no_cross_for_product()`; `_ev_filter_status()` | Optional BNB-specific market probability cap for ITM/no-cross EV candidates. | blocks/allows/logs | EV | Overrides only BNB EV entry price cap when set; all existing EV and safety gates still apply. | yes | Same EV cap block reasons; logs `ev_product_price_cap_source=product:BNB-USD`. |
| `LIVE_EV_PRICE_MAX_NEEDS_CROSS` | `0.30` | `0.25` | example `0.30` | `settings.load_settings()` only | Parsed into settings but not used by current live EV filter code path. | none currently | EV, cross/bps | Current EV candidates require no cross; this value has no downstream behavioral effect found. | yes | None directly. |
| `LIVE_EV_REQUIRED_BPS_MAX` | `0.25` | `0.25` | example `0.25` | `_ev_filter_status()`; `_ev_filter_skip_reason()` | Max required bps per minute for EV candidates. | blocks/allows | EV, cross/bps | Separate from composite `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`; same live value here. | yes | `required_bps_per_minute_too_high`, `missing_required_bps_within_limit`. |
| `LIVE_EV_ALLOWED_SEGMENTS` | `10_to_5,5_to_3` | `10_to_5,5_to_3,3_to_1` | example `10_to_5,5_to_3` | `_ev_filter_status()` | Entry segments eligible for candidate A. | blocks/allows | EV, segment | Uses segment from end-window remaining seconds. | yes | `ev_filter_blocked`, `missing_entry_segment_allowed`. |
| `LIVE_EV_CONSERVATIVE_ALLOWED_SEGMENTS` | `10_to_5,5_to_3,3_to_1` | `10_to_5,5_to_3,3_to_1` | example same | `_ev_filter_status()` | Entry segments eligible for conservative candidate B. | blocks/allows | EV, segment | Candidate B also requires low price <= `LIVE_COMPOSITE_LOW_PRICE_MAX`. | yes | `ev_filter_blocked`, `candidate_not_matched`. |
| `LIVE_EV_ALLOW_REVERSAL` | `false` | `false` | example `false` | `_ev_filter_status()` | Allows reversal structure into EV candidate A when true. | blocks/allows | EV, reversal | Current live false means EV candidate A/B are trend-only. | yes | `ev_filter_blocked`, `missing_structure_trend`. |
| `LIVE_EV_CANDIDATE_A_WIN_PROBABILITY` | `0.87` | `0.87` | example `0.87` | `_ev_filter_status()` | Assumed win probability for broad EV candidate A. | scores/allows | EV | Drives EV score and cost expected value. | yes | `ev_filter_blocked`, `ev_negative_cost_expected_value`. |
| `LIVE_EV_CANDIDATE_B_WIN_PROBABILITY` | `0.92` | `0.92` | example `0.92` | `_ev_filter_status()` | Assumed win probability for lower-price conservative EV candidate B. | scores/allows | EV | Candidate B takes precedence over candidate A when matched. | yes | `ev_filter_blocked`, `ev_negative_cost_expected_value`. |
| `LIVE_PRODUCT_BLOCKLIST` | empty | empty | example `ETH-USD,XRP-USD` | `_ev_filter_status()`; `_ev_filter_skip_reason()` | Product blocklist for EV candidates. | blocks | EV | Empty current value blocks no products. | yes | `product_blocklisted`, `missing_product_not_blocklisted`. |
| `LIVE_CONDITIONAL_HIGH_PRICE_PASS_ENABLED` | `true` | `true` | example `true` | `_conditional_ev_override_denial()` | Enables EV-qualified conditional override for high/extreme execution safety blockers. | allows/blocks | EV, submission | Requires EV conditional eligibility and conditional spread/premium/liquidity checks. | yes | `conditional_high_price_pass_disabled`, `execution_safety_blocked`. |
| `LIVE_CONDITIONAL_MAX_PREMIUM_OVER_MIDPOINT` | `0.08` | `0.09` | example `0.08` | `_conditional_ev_override_denial()` | Max relaxed premium over scanner midpoint for conditional override. | blocks/allows | EV, submission | Not applied to scanner-premium blocker itself; scanner-premium has its own cap. | yes | `premium_above_relaxed_limit`. |
| `LIVE_CONDITIONAL_MAX_SPREAD` | `0.15` | `0.15` | example `0.15` | `_conditional_ev_override_denial()` | Max spread allowed for conditional high-price override. | blocks/allows | EV, submission | Requires spread to be available. | yes | `spread_unavailable`, `spread_above_relaxed_limit`. |
| `LIVE_CONDITIONAL_MAX_SCANNER_PREMIUM` | `0.12` | `0.12` | example `0.12` | `_conditional_ev_override_denial()` | Max executable price premium over scanner midpoint for conditional override. | blocks/allows | EV, submission | Applies to all conditional override blocker types. | yes | `scanner_premium_above_relaxed_limit`. |
| `LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY` | `false` | `true` | example `false` | `_conditional_ev_override_denial()` | Allows conditional override of extreme execution price asymmetry. | allows/blocks | EV, submission | Still capped by conditional ceiling, spread, premium, scanner premium, and liquidity. | yes | `extreme_asymmetry_bypass_disabled`, `executable_price_extreme_asymmetry`. |
| `LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS` | `false` | `true` | example `false` | `_conditional_ev_override_denial()` | Allows bypass of contextual high price ceiling blocker. | allows/blocks | EV, submission | Still cannot exceed `LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX`. | yes | `high_price_ceiling_bypass_disabled`, `entry_price_above_conditional_ceiling`. |
| `LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX` | `0.70` | `0.70` | example `0.70` | `_conditional_ev_override_denial()` | Absolute max price for conditional high-price override. | blocks/allows | EV, submission | Used after EV conditional eligibility. | yes | `entry_price_above_conditional_ceiling`. |
| `LIVE_EV_TIMING_BYPASS_ENABLED` | `true` | `true` | example `true` | `_deferred_timing_block_applies()`; `_composite_quality_status()` | Lets EV-qualified candidates bypass some deferred timing and outside-window composite blocks. | allows | EV, segment, composite | Requires EV conditional eligibility. | yes | Without it: `entry_timing_blocked`, `outside_end_window_blocked`. |
| `LIVE_EV_EXTRA_ENTRIES_PER_PRODUCT_PER_SESSION` | `0` | `1` | example `0` | `_product_session_pacing_status()` | Extra same-product/session entries available to EV-qualified candidates. | allows/paces | EV, product pacing | Only applies when EV conditional eligibility is true and base session cap is reached. | yes | `product_session_pacing_blocked`, `max_entries_per_product_session_reached`. |
| `LIVE_EV_EXTRA_OPEN_POSITIONS_PER_PRODUCT` | `0` | `1` | example `0` | `_product_session_pacing_status()` | Extra open positions per product available to EV-qualified candidates. | allows/paces | EV, product pacing | Only applies when EV conditional eligibility is true and base product cap is reached. | yes | `product_session_pacing_blocked`, `max_open_positions_per_product_reached`. |
| `LIVE_COMPOSITE_QUALITY_FILTER_ENABLED` | `true` | `true` | example `true` | `_composite_quality_status()`; `_deferred_timing_block_applies()` | Enables composite trend/ITM/no-cross/price/segment quality gate. | blocks/allows | composite, segment, cross/bps | EV-qualified candidates can override missing composite conditions. | yes | `composite_quality_blocked`, `outside_end_window_blocked`. |
| `LIVE_COMPOSITE_MAX_ENTRY_PRICE` | `0.70` | `0.60` | example `0.50` | `_composite_matched_conditions()` | Max entry price for composite quality. | blocks/allows | composite | Lower price can also match low-price cluster via `LIVE_COMPOSITE_LOW_PRICE_MAX`. | yes | `composite_quality_blocked`, `missing_entry_price_at_or_below_max`. |
| `LIVE_COMPOSITE_LOW_PRICE_MAX` | `0.30` | `0.10` | example `0.30` | `_composite_matched_conditions()`; `_ev_filter_status()` | Low-price cluster threshold and EV candidate B price threshold. | scores/allows | composite, EV | Tight current value makes candidate B stricter. | yes | `ev_filter_blocked`, `candidate_not_matched`. |
| `LIVE_COMPOSITE_ALLOWED_SEGMENTS` | `10_to_5,5_to_3` | `10_to_5,5_to_3,3_to_1` | example `10_to_5,5_to_3` | `_composite_matched_conditions()` | Entry segments eligible for composite quality. | blocks/allows | composite, segment | Uses segment from remaining seconds. | yes | `composite_quality_blocked`, `missing_entry_segment_allowed`. |
| `LIVE_COMPOSITE_REQUIRE_TREND` | `true` | `true` | example `true` | `_composite_required_conditions()` | Requires trend structure in composite quality. | blocks/allows | composite, scanner/bias | EV composite override can allow missing requirement. | yes | `composite_quality_blocked`, `missing_structure_trend`. |
| `LIVE_COMPOSITE_REQUIRE_ITM` | `true` | `true` | example `true` | `_composite_required_conditions()` | Requires side currently ITM in composite quality. | blocks/allows | composite, cross/bps | EV composite override can allow missing requirement, but other cross gates may still block. | yes | `composite_quality_blocked`, `missing_side_currently_itm`. |
| `LIVE_COMPOSITE_BLOCK_NEEDS_CROSS` | `true` | `true` | example `true` | `_composite_required_conditions()` | Adds no-cross as required composite condition. | blocks/allows | composite, cross/bps | Separate from hard `LIVE_BLOCK_NEEDS_CROSS`. | yes | `composite_quality_blocked`, `missing_side_needs_cross_false`. |
| `LIVE_REVERSAL_MAX_ENTRY_PRICE` | `0.10` | `0.30` | example `0.10` | `_composite_quality_status()` | Max entry price for reversal candidates before composite blocks. | blocks/allows | reversal, composite | Applies to reversal structure before normal composite conditions. | yes | `reversal_price_blocked`, `reversal_entry_price_too_high`. |
| `LIVE_BLOCK_NEEDS_CROSS` | `true` | `true` | example `true` | `_needs_cross_status()`; `_ev_filter_skip_reason()` | Hard live block for candidates requiring underlying price to cross target. | blocks | cross/bps, EV, composite | Separate from scanner score downgrades and composite no-cross condition. | yes | `needs_cross_blocked`, `side_needs_cross_blocked`. |
| `LIVE_MAX_REQUIRED_BPS_PER_MINUTE` | `0.25` | `0.25` | example `0.25` | scanner quiet kwargs; `_required_bps_per_minute_status()` | Max required bps/min for quiet continuation and composite quality. | blocks/allows | quiet, composite, cross/bps | Separate from EV-specific `LIVE_EV_REQUIRED_BPS_MAX`. | yes | `quiet_continuation_required_bps_too_high`, `required_bps_per_minute_too_high`. |
| `LIVE_OUTSIDE_END_WINDOW_EXCEPTION_ENABLED` | `false` | `true` | example `false` | `_outside_end_window_exception_status()` | Allows selected low-price trend entries outside the end window. | allows | segment, composite | Requires price <= max, trend, ITM, no cross. | yes | Without it: `outside_end_window_blocked`, `entry_timing_blocked`. |
| `LIVE_OUTSIDE_END_WINDOW_MAX_PRICE` | `0.30` | `0.30` | example `0.30` | `_outside_end_window_exception_status()` | Max price for outside-end-window exception. | blocks/allows | segment, composite | Active only when outside-window exception enabled. | yes | `outside_end_window_blocked`. |
| `LIVE_MAX_OPEN_POSITIONS` | `20` via risk default | `20` | example `2` | `RiskManager.from_live_settings()`; `evaluate_entry_risk()` | Global max open live positions. | blocks/risk | risk, submission | Reconciliation may run before risk when near this cap. | yes | `risk_max_open_positions`. |
| `LIVE_MIN_STAKE_DOLLARS` | `1` via risk default | `1` | example `0.10` | `RiskManager.from_live_settings()`; `compute_stake_from_confidence()` | Minimum computed live stake. | sizes/risk | risk | Clamps confidence-based stake; must be <= max stake at settings load. | yes | Settings error if greater than max; can cause larger count/exposure. |
| `LIVE_MAX_STAKE_DOLLARS` | `5` via risk default | `2` | example `3` | `RiskManager.from_live_settings()`; `compute_stake_from_confidence()` | Maximum computed live stake. | sizes/risk | risk | Clamps confidence-based stake; interacts with price to produce contract count. | yes | `risk_stake_unavailable`, `count_below_one`, settings error if below min. |
| `LIVE_MAX_CONTRACT_COUNT` | `1000` | `1000` | example `1000` | `RiskManager.from_live_settings()`; `evaluate_live_order()` | Max contract count per live order. | blocks/submits | submission, risk | Applied at final live safety evaluation. | yes | `order_count_exceeds_phase10_cap`. |
| `LIVE_MAX_EXPOSURE_DOLLARS` | `10` via risk default | `20` | example `10` | `RiskManager.from_live_settings()`; `evaluate_entry_risk()` | Max total live exposure. | blocks/risk | risk, submission | Uses current live ledger/reconciled exposure plus computed stake. | yes | `risk_max_total_exposure`. |
| `LIVE_PROFIT_CAPTURE_ENABLED` | `false` | `true` | example `false` | `process_profit_capture_exits()` | Enables exit orders when executable bid reaches capture price. | allows/submits | exit, submission | Runs only with live runner execution and market position data. | yes | `profit_capture_exit_skipped`, `live_safety_blocked`. |
| `LIVE_PROFIT_CAPTURE_PRICE` | `0.99` | `0.99` | example `0.99` | `_process_live_exit_position()`; `_live_exit_payload()` | Exit bid threshold for profit capture. | blocks/allows/submits | exit | Uses executable exit bid and visible liquidity. | yes | `executable_exit_bid_missing`, `exit_liquidity_missing`, `sell_count_unavailable`. |
| `LIVE_TRAILING_STOP_ENABLED` | `false` | `false` | example `false` | `process_profit_capture_exits()`; `_process_live_exit_position()` | Enables trailing-stop exit logic. | allows/submits | exit | Uses peak executable exit bid and trailing distance. | yes | `trailing_stop_exit_skipped`, `live_safety_blocked`. |
| `LIVE_TRAILING_STOP_DISTANCE` | `0.05` | `0.05` | example `0.05` | `_process_live_exit_position()`; `_live_exit_payload()` | Drop from peak exit bid that triggers trailing stop. | blocks/allows | exit | Active only when trailing stop enabled. | yes | `trailing_stop_exit_skipped`, `sell_count_unavailable`. |
| `LIVE_ENTRY_END_WINDOW_ONLY` | `false` | `true` | example `false` | `_entry_end_window_status()` | Requires live entries inside final configured minutes unless exception/bypass applies. | blocks/allows | segment, EV, composite | EV timing bypass and outside-window exception can defer/override selected timing blocks. | yes | `end_window_not_open`, `entry_timing_blocked`, `outside_end_window_blocked`. |
| `LIVE_ENTRY_END_WINDOW_MINUTES` | `5` | `8` | example `5` | `_entry_end_window_status()` | Width of final entry window. | blocks/allows | segment | With live value, window opens at 8 minutes remaining. | yes | `end_window_not_open`. |
| `LIVE_ENTRY_MIN_REMAINING_SECONDS` | `0` | `20` | example `180` | `_entry_end_window_status()` | Minimum seconds remaining for entry. | blocks | segment | Can still block even inside end window. | yes | `entry_min_remaining_seconds_not_met`. |
| `LIVE_FAST_SCAN_ENABLED` | `false` | `true` | example `false` | `KalshiBotRunner._fast_scan_available()` | Enables fast scan passes during sleep between normal cycles. | allows/paces | scanner/bias, submission | Requires live runner execution and live coordinator. | yes | `live_fast_scan_skipped`, `cooldown_active`. |
| `LIVE_FAST_SCAN_INTERVAL_SECONDS` | `2.0` | `2` | example `2` | `KalshiBotRunner._sleep_between_cycles()` | Delay between fast-scan opportunities. | paces | scanner/bias, submission | Runs inside normal runner loop interval. | yes | None directly. |
| `LIVE_FAST_SCAN_COOLDOWN_SECONDS` | `5.0` | `5` | example `5` | `KalshiBotRunner._run_fast_scan_pass()` | Cooldown after a fast scan submits an intent. | paces | submission | Cooldown is in-memory and resets on restart. | yes | `live_fast_scan_skipped`, `cooldown_active`. |
| `SIMULATION_ENABLED` | `true` | `false` | example `true` | `settings.load_settings`; `KalshiBotRunner.from_settings()` | Enables simulation engine. | allows/logs | scanner/bias | Current live disables simulation engine. | yes | None directly; simulation decisions absent. |
| `LIVE_VALIDATION_ENABLED` | `false` | `false` | example `false` | `settings.load_settings`; `RiskManager.evaluate_live_order()`; smoke tester | Enables standalone validation/smoke live submission. | blocks/submits | submission | Normal live runner risk manager overrides this to true internally; standalone smoke tester does not. | yes | `live_validation_disabled`; smoke error `LIVE_VALIDATION_ENABLED must be true`. |
| `LIVE_TRADING_ENABLED` | `false` | `true` | example `false` | `RiskManager.evaluate_live_order()` | Master live trading enable. | blocks/submits | submission | Still requires kill switch false, prod env, valid order, count cap, TIF. | yes | `live_trading_not_enabled`. |
| `LIVE_RUNNER_EXECUTION_ENABLED` | `false` | `true` | example `false` | `KalshiBotRunner.from_settings()`; `_run_single_cycle()`; `_fast_scan_available()` | Enables runner-driven live client, live risk manager, live intent processing, submission, exits, reconciliation, and fast scan. | allows/submits | submission, exit, scanner/bias | Does not alone bypass live trading or risk guardrails. | yes | If false, live intents are not submitted by runner. |
| `LIVE_KILL_SWITCH_ACTIVE` | `false` | `false` | example `false` | `RiskManager.evaluate_live_order()` | Hard kill switch for live order safety. | blocks/submits | submission | Checked before live trading enabled. | yes | `kill_switch_active`. |
| `LIVE_ENTRY_SEGMENT_PACING_ENABLED` | `false` | `true` | example `false` | `_entry_segment_status()` | Enables per-market entry budgets by time segment. | blocks/paces | segment | Counts are in-memory and increment after intent creation. | yes | `entry_segment_budget_exhausted`. |
| `LIVE_ENTRY_SEGMENT_MAX_10_TO_5` | `1` | `2` | example `1` | `_entry_segment_max_count()` | Max entries per market in 10-to-5 minute segment. | blocks/paces | segment | Active only when segment pacing enabled. | yes | `entry_segment_budget_exhausted`. |
| `LIVE_ENTRY_SEGMENT_MAX_5_TO_3` | `1` | `5` | example `1` | `_entry_segment_max_count()` | Max entries per market in 5-to-3 minute segment. | blocks/paces | segment | Active only when segment pacing enabled. | yes | `entry_segment_budget_exhausted`. |
| `LIVE_ENTRY_SEGMENT_MAX_3_TO_1` | `1` | `5` | example `1` | `_entry_segment_max_count()` | Max entries per market in 3-to-1 minute segment. | blocks/paces | segment | Active only when segment pacing enabled. | yes | `entry_segment_budget_exhausted`. |
| `LIVE_ENTRY_SEGMENT_MAX_FINAL_1` | `1` | `2` | example `1` | `_entry_segment_max_count()` | Max entries per market in final minute. | blocks/paces | segment | Active only when segment pacing enabled. | yes | `entry_segment_budget_exhausted`. |
| `LIVE_REVERSAL_CROSS_HOLD_ENABLED` | `true` | `true` | example `true` | `_reversal_cross_hold_status()` | Requires reversal candidates to hold ITM/no-cross for configured seconds. | blocks/allows | reversal, cross/bps | Depends on ITM persistence memory. | yes | `reversal_cross_hold_blocked`, `reversal_cross_hold_waiting`. |
| `LIVE_REVERSAL_CROSS_HOLD_SECONDS` | `60` | `90` | example `90` | `_reversal_cross_hold_status()` | Required reversal ITM hold time. | blocks/allows | reversal | Active only for reversal structure when cross-hold enabled. | yes | `reversal_cross_hold_waiting`. |
| `LIVE_MID_PRICE_TIGHTENING_ENABLED` | `true` | `true` | example `true` | `_mid_price_confirmation_status()` | Requires extra confirmation for entries inside configured mid-price band. | blocks/allows | submission, early, reversal | Allows confirmed trend, sustained ITM, early momentum, or confirmed reversal cross-hold. | yes | `mid_price_confirmation_required`. |
| `LIVE_MID_PRICE_MIN` | `0.50` | `0.52` | example `0.50` | `_mid_price_confirmation_status()` | Lower bound of mid-price confirmation band. | blocks/allows | submission | If price outside band, no confirmation required. | yes | `mid_price_confirmation_required`. |
| `LIVE_MID_PRICE_MAX` | `0.70` | `0.60` | example `0.70` | `_mid_price_confirmation_status()` | Upper bound of mid-price confirmation band. | blocks/allows | submission | Current band is 0.52-0.60. | yes | `mid_price_confirmation_required`. |
| `LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT` | `2` | `3` | example `2` | `_product_session_pacing_status()` | Max open live positions for one product. | blocks/paces | product pacing, risk | EV extra open capacity can extend this by configured amount for EV-eligible candidates. | yes | `product_session_pacing_blocked`, `max_open_positions_per_product_reached`. |
| `LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION` | `2` | `3` | example `2` | `_product_session_pacing_status()` | Max entries per product/market session. | blocks/paces | product pacing | EV extra session capacity can extend this for EV-eligible candidates. | yes | `product_session_pacing_blocked`, `max_entries_per_product_session_reached`. |
| `KALSHI_AUTO_MARKET_DISCOVERY_ENABLED` | `true` | `true` | example `true` | `settings.load_settings`; `KalshiBotRunner.from_settings()` | Uses runner-managed active crypto market discovery instead of static scanner markets. | allows/discovery | discovery, scanner/bias | Uses default or configured crypto market series and refresh cycles. | yes | Market discovery errors; no direct live candidate block reason. |

## Grouped Behavior Notes

### Quiet Continuation

Quiet continuation only runs after the normal scanner would skip a contract for `neutral_bias`. The scanner attempts to convert neutral chop/exhaustion into a trend-like bias when direction can be inferred from lookback/recent movement. It then requires target feasibility, no cross needed, required bps within `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`, bid/ask present, and all quiet thresholds to pass.

Current interpretation: enabled and narrow. It allows stable ITM/no-cross continuation candidates from otherwise neutral conditions, but blocks recent bursts, range expansion, deceleration after burst, and near-extreme continuation.

### Conservative Stabilization

Weak-momentum stabilization is disabled unless all three weak-momentum env thresholds are configured. When active, it only helps candidates already ITM/no-cross, sufficiently negative distance-to-target, inside the configured 5m range, and under the configured price cap. It can prevent the scanner weak-recent downgrade for stable ITM holds and can block quiet continuation that fails the stabilization test. It does not bypass needs-cross, EV, pacing, risk, exposure, or execution safety.

Mini-exhaustion is disabled by default. When enabled, it is a scanner confidence downgrade and diagnostic only. It flags near-strike trend candidates with small/moderate aligned 3m movement, an aligned recent spike, and elevated 5m range. It does not hard-block all candidates and does not activate any reversal logic.

Bias relaxation is disabled unless both `LIVE_BIAS_RECENT_RETURN_MIN` and `LIVE_BIAS_LOOKBACK_RETURN_MIN` are set. When active, it can classify aligned slow trends as `bias_relaxed_aligned_slow_trend`; neutral bias and reversal restrictions otherwise remain intact.

Noise-cross handling is off at `LIVE_MIN_CROSS_DISTANCE_BPS=0`. When configured above zero, only tiny positive crosses at or below the threshold are marked `noise_cross_ignored`; true needs-cross candidates still flow through existing scanner, EV, composite, and live blocks.

### Candidate Funnel Diagnostics

`LIVE_CANDIDATE_FUNNEL_DIAGNOSTICS_ENABLED=true` changes logging, not trading decisions. Runner cycle logs include detailed scanner diagnostics, and live funnel summaries include up to 20 live outcome records and scanner candidate diagnostics.

### Exhaustion Guard

The scanner computes range expansion, deceleration, near-extreme, and exhaustion status for candidates. When enabled, trend candidates that are already ITM/no-cross and have `exhaustion_status=blocked` are skipped at scanner level with `exhaustion_guard_blocked`. If `LIVE_EXHAUSTION_PROGRESSION_OVERRIDE_ENABLED=true`, the scanner first checks recent normal-cycle progression context; only sustained ITM/no-cross continuation with non-positive required bps, aligned returns, non-accelerating range, and no worsening near-extreme distance can downgrade the final status to `progression_caution`. EV filtering, needs-cross, pricing, pacing, risk, and execution safety still run after any downgrade.

### Early Momentum

Early momentum is a confirmation aid, not a standalone entry gate. A candidate must be a trend, have aligned recent movement above `LIVE_EARLY_MOMENTUM_MIN_RECENT_BPS`, avoid a too-large 3m burst, and avoid exhaustion. If confirmed and the executable entry price is at or below `LIVE_EARLY_MOMENTUM_MAX_ENTRY_PRICE`, it can satisfy mid-price confirmation.

### EV Filter and EV Extra Capacity

The EV filter currently matches trend, ITM, no-cross candidates with required bps within limit, allowed segment, non-blocklisted product, visible liquidity, and price within `LIVE_EV_PRICE_MAX_ITM_NO_CROSS`. Candidate B is stricter and uses `LIVE_COMPOSITE_LOW_PRICE_MAX`; candidate B probability takes precedence over candidate A.

EV-qualified candidates set `conditional_override_eligible=true`. That can allow timing bypass, composite override, and extra per-product/session capacity. `LIVE_EV_PRICE_MAX_NEEDS_CROSS` is parsed into settings but no downstream use was found in current code because current EV matching requires no cross.

Product-specific EV caps are optional and only replace the global ITM/no-cross price cap for their product. The EV filter logs the cap value and source used for each candidate.

### Conditional High-Price Overrides

Conditional overrides apply only when the EV filter allowed the candidate. They can override selected execution safety blockers for high/extreme prices when enabled and when spread, premium, scanner premium, ceiling, and visible-liquidity checks pass.

### Composite Quality

Composite quality checks trend, ITM, no-cross, max entry price, and allowed segment. Reversals are handled first by `LIVE_REVERSAL_MAX_ENTRY_PRICE`. EV-qualified candidates can override missing composite requirements, but hard needs-cross and required-bps checks can still block earlier in composite status.

### Reversal and Cross-Hold

Reversal candidates must pass low reversal entry price in composite quality. When cross-hold is enabled, reversals must be ITM, need no cross, and hold that state for `LIVE_REVERSAL_CROSS_HOLD_SECONDS`.

### Needs-Cross and Required-Bps Gates

The scanner computes `side_needs_cross` and `required_bps_per_minute` from current spot, target price, and remaining time. Needs-cross can downgrade scanner score, block quiet continuation, block EV, and block composite/live entry through `LIVE_BLOCK_NEEDS_CROSS`. Required-bps gates exist separately for scanner feasibility constants, quiet/composite `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`, and EV `LIVE_EV_REQUIRED_BPS_MAX`.

### Entry, End-Window, and Fast-Scan Pacing

Current live config requires entries in the final 8 minutes but not below 20 seconds remaining. Segment pacing is enabled with separate per-market budgets for 10-to-5, 5-to-3, 3-to-1, and final-1 minute segments. Fast scan is enabled every 2 seconds during normal loop sleep and uses a 5-second cooldown after a fast-scan submission.

### Exposure and Risk Sizing

Live risk sizing computes stake from confidence, then clamps between `LIVE_MIN_STAKE_DOLLARS=1` and `LIVE_MAX_STAKE_DOLLARS=2`. Entry risk blocks when global live open positions reach `LIVE_MAX_OPEN_POSITIONS=20`, exposure plus stake exceeds `LIVE_MAX_EXPOSURE_DOLLARS=20`, or the risk daily loss guard trips. Per-product/session pacing is separate from global risk limits.

### Profit Capture and Trailing Stop Exits

Profit capture is enabled at `0.99`; trailing stop is configured but disabled. Exit order submission still goes through live safety checks and can be blocked by unavailable positions client, missing market state, missing executable bid, missing liquidity, unavailable sell count, live safety block, unavailable client, submit failure, or poll failure.

### Live Submission Controls

Live runner execution is enabled and live trading is enabled, while the kill switch is off. Standalone `LIVE_VALIDATION_ENABLED=false` would block a smoke-test path, but the normal runner constructs its live risk manager with validation forced on and env forced to prod. The final submission path still checks kill switch, live trading flag, prod env, required fields, max contract count, and required time-in-force.

## All Known Blocker Reasons and Env Influence

Scanner and candidate blockers:

- `missing_bias_state`, `neutral_bias`, `non_positive_confidence`, `late_expansion_bias`, `unconfirmed_impulse_bias`: influenced by bias inputs, not current live env knobs except quiet continuation can rescue `neutral_bias`.
- `quiet_continuation_target_missing`, `quiet_continuation_current_spot_missing`, `quiet_continuation_needs_cross_blocked`, `quiet_continuation_required_bps_missing`, `quiet_continuation_required_bps_too_high`: influenced by `LIVE_QUIET_CONTINUATION_ENABLED` and `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`.
- `quiet_continuation_recent_move_too_large`, `quiet_continuation_recent_opposite`, `quiet_continuation_3m_burst_too_large`, `quiet_continuation_5m_burst_too_large`, `quiet_continuation_range_expanded`, `quiet_continuation_decelerating_after_burst`, `quiet_continuation_near_recent_extreme`: influenced by `LIVE_QUIET_CONTINUATION_*` and exhaustion thresholds.
- `weak_momentum_stabilization_*`: influenced by `LIVE_WEAK_MOMENTUM_*`; only affects configured weak-momentum stabilization and quiet continuation stabilization.
- `mini_exhaustion`: scanner confidence downgrade influenced by `LIVE_MINI_EXHAUSTION_*`; diagnostic/downgrade only.
- `bias_relaxed_aligned_slow_trend`: classification reason influenced by `LIVE_BIAS_RECENT_RETURN_MIN` and `LIVE_BIAS_LOOKBACK_RETURN_MIN`.
- `noise_cross_ignored`: feasibility status influenced by `LIVE_MIN_CROSS_DISTANCE_BPS`; larger needs-cross cases retain existing blockers.
- `target_feasibility_distance_too_far`, `target_feasibility_required_move_too_fast`, `target_feasibility_required_move_too_fast_tight`: scanner hard feasibility constants, not current env.
- `exhaustion_guard_blocked`: influenced by `LIVE_EXHAUSTION_*`; progression diagnostics show whether a base block stayed hard-blocked or was downgraded to caution.
- `exhaustion_progression_caution`: scanner confidence downgrade when default-off progression override is enabled and all sustained-continuation checks pass.

Live entry blockers:

- `invalid_direction`, `invalid_entry_price`, `stale_ticker_blocked`: data/contract validation.
- `reversal_cross_hold_blocked`: `LIVE_REVERSAL_CROSS_HOLD_ENABLED`, `LIVE_REVERSAL_CROSS_HOLD_SECONDS`.
- `end_window_not_open`, `entry_min_remaining_seconds_not_met`, `entry_timing_blocked`, `outside_end_window_blocked`: `LIVE_ENTRY_END_WINDOW_ONLY`, `LIVE_ENTRY_END_WINDOW_MINUTES`, `LIVE_ENTRY_MIN_REMAINING_SECONDS`, `LIVE_OUTSIDE_END_WINDOW_EXCEPTION_*`, `LIVE_EV_TIMING_BYPASS_ENABLED`.
- `entry_segment_budget_exhausted`: `LIVE_ENTRY_SEGMENT_PACING_ENABLED`, `LIVE_ENTRY_SEGMENT_MAX_*`.
- `flip_persistence_blocked`, `retry_persistence_blocked`: in-memory live-entry memory, not env-controlled.
- `product_session_pacing_blocked`: `LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT`, `LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION`, `LIVE_EV_EXTRA_*`.
- `product_blocklisted`: `LIVE_PRODUCT_BLOCKLIST`.
- `needs_cross_blocked`: `LIVE_BLOCK_NEEDS_CROSS`, plus EV/composite no-cross requirements.
- `required_bps_per_minute_too_high`: `LIVE_MAX_REQUIRED_BPS_PER_MINUTE` or `LIVE_EV_REQUIRED_BPS_MAX`, depending on stage.
- `ev_filter_blocked`, `ev_actual_cost_above_limit`, `ev_reward_below_limit`, `ev_negative_cost_expected_value`, `ev_exhaustion_blocked`: `LIVE_EV_*`, candidate probabilities, exhaustion status.
- `risk_max_open_positions`, `risk_max_total_exposure`, `risk_daily_loss_limit`, `risk_kill_switch_active`, `risk_stake_unavailable`: live/risk limits.
- `mid_price_confirmation_required`: `LIVE_MID_PRICE_TIGHTENING_ENABLED`, `LIVE_MID_PRICE_MIN`, `LIVE_MID_PRICE_MAX`, early momentum, sustained ITM, reversal cross-hold.
- `execution_safety_blocked`, `executable_price_below_minimum`, `executable_price_above_maximum`, `executable_price_extreme_asymmetry`, `executable_price_above_scanner_premium`, `executable_price_no_visible_liquidity`, `contextual_high_price_*`: hard execution safety constants plus `LIVE_CONDITIONAL_*`.
- `count_below_one`: stake too small relative to executable price.
- `composite_quality_blocked`, `reversal_price_blocked`: `LIVE_COMPOSITE_*`, `LIVE_REVERSAL_MAX_ENTRY_PRICE`, `LIVE_BLOCK_NEEDS_CROSS`, `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`.
- `live_intent_not_risk_approved`, `live_validation_disabled`, `live_trading_not_enabled`, `kill_switch_active`, `live_env_not_prod`, `missing_live_order_field`, `order_count_exceeds_phase10_cap`, `unsupported_time_in_force`, `live_client_unavailable`, `order_submit_failed`, `order_poll_failed`: final submission guardrails and client state.

Exit blockers:

- `positions_client_unavailable`, `positions_fetch_failed`, `invalid_position_side`, `market_state_missing`, `executable_exit_bid_missing`, `exit_liquidity_missing`, `sell_count_unavailable`, `live_safety_blocked`, `live_client_unavailable`, `order_submit_failed`, `order_poll_failed`: influenced by `LIVE_PROFIT_CAPTURE_*`, `LIVE_TRAILING_STOP_*`, live safety flags, and market/client state.

## Hard Safety Controls Not to Loosen Blindly

- `LIVE_TRADING_ENABLED`, `LIVE_RUNNER_EXECUTION_ENABLED`, `LIVE_KILL_SWITCH_ACTIVE`: govern whether runner live orders can be attempted.
- `LIVE_MAX_EXPOSURE_DOLLARS`, `LIVE_MAX_OPEN_POSITIONS`, `LIVE_MAX_CONTRACT_COUNT`, `LIVE_MIN_STAKE_DOLLARS`, `LIVE_MAX_STAKE_DOLLARS`: define live risk size and caps.
- `LIVE_BLOCK_NEEDS_CROSS`, `LIVE_MAX_REQUIRED_BPS_PER_MINUTE`, `LIVE_EV_REQUIRED_BPS_MAX`: prevent entries that require too much underlying movement.
- `LIVE_EV_MAX_ACTUAL_COST`, `LIVE_EV_MIN_REWARD_DOLLARS`, `LIVE_EV_REQUIRE_POSITIVE_COST_EXPECTED_VALUE`, `LIVE_EV_EXHAUSTION_BLOCK_ENABLED`: protect EV quality.
- `LIVE_CONDITIONAL_ALLOW_EXTREME_ASYMMETRY`, `LIVE_CONDITIONAL_ALLOW_HIGH_PRICE_CEILING_BYPASS`, `LIVE_CONDITIONAL_HIGH_PRICE_CEILING_MAX`: can bypass high-price safety only after EV qualification.
- `LIVE_ENTRY_MIN_REMAINING_SECONDS`, `LIVE_ENTRY_SEGMENT_*`, `LIVE_MAX_OPEN_POSITIONS_PER_PRODUCT`, `LIVE_MAX_ENTRIES_PER_PRODUCT_PER_SESSION`: control late-session overtrading.

## Backtesting Tuning Controls

Use these as primary strategy knobs in backtests:

- Scanner/bias tuning: quiet continuation thresholds, exhaustion thresholds, early momentum thresholds.
- Timing and pacing: end-window minutes, min remaining seconds, segment budgets, fast-scan interval/cooldown.
- EV tuning: EV price limits, required-bps limit, allowed segments, candidate probabilities, actual-cost/reward/cost-EV thresholds, product blocklist, EV extra capacity.
- Composite tuning: composite max price, low-price max, allowed segments, require-trend/ITM/no-cross flags.
- Reversal tuning: reversal max entry price and cross-hold seconds.
- Risk sizing: min/max stake, global exposure, global open positions, per-product open/session caps.
- Exit tuning: profit capture price and trailing stop distance.

## Current Known Strategy Interpretation Based on Code

The current live configuration is a late-window crypto duration strategy that primarily wants ITM/no-cross trend candidates with low required movement, visible liquidity, and positive modeled EV. It permits quiet continuation from neutral chop/exhaustion when price action is stable and already favorable. It actively avoids exhaustion, recent burst deceleration, near-extreme quiet continuation, needs-cross entries, and high required bps/minute.

Live execution is intentionally layered: scanner ranking finds candidates, EV and composite filters qualify them, pacing prevents repeated entries in the same product/session/segment, risk limits size and exposure, and final live safety checks protect actual order submission. Conditional high-price overrides are available in the current live env, but only for EV-qualified candidates that pass spread, premium, scanner premium, ceiling, and visible-liquidity checks.

## Env Audit Summary

- Variables in `CURRENTENV.md`: 94.
- Variables in `CURRENTENV.md` missing from `.env.example` / `.env.production.example`: none.
- Variables in `CURRENTENV.md` missing from `kalshi_bot/config/settings.py`: none.
- Variables in examples that are not settings-backed: none.
- Settings-backed env vars missing from examples: `RUNNER_ENABLED`, `RUNNER_FAIL_FAST_ON_STARTUP`, `RUNNER_LOOP_INTERVAL_SECONDS`, `RUNNER_MAX_CYCLES`, `RUNNER_STATUS_LOG_EVERY_N_CYCLES`.
