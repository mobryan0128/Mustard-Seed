# Commit History Implementation Log

This file was generated from git history for ChatGPT Project Sources. It summarizes implementation changes to reduce project drift. It does not replace source code, CURRENT_KALSHI_BOT_SOURCE_OF_TRUTH.txt, or live audit results.

## Current Status Summary

- The bot is in live post-fix audit/refinement mode based on the latest commits through `d1cc4a6` on 2026-05-18.
- Final scoring/gating calibration added cold-start, high-ratio, and overextension danger detection.
- High-score danger cap and normalized distance/burst telemetry were added to the scoring, runner, replay, and audit paths.
- Reversal remains shadow-only by default.
- Needs-cross, EV/risk/liquidity, stake, and exposure controls remain hard protections.
- This document is a historical trace for ChatGPT Project Sources, not a live trading recommendation.

## Commit History

### 1. `ead4492` - 2026-04-21 - Initial clean architecture setup

- Body/description: None beyond subject.
- Files added: `AGENTS.md`, `BUILD_PHASES.md`, `MASTER_SPEC.md`, `MEMORY_FILES.md`.
- Files modified: None.
- Files deleted: None.
- Stats: 4 files changed, 585 insertions.
- High-level summary: Inference from diff. Established initial repository guidance and memory/spec documents before runtime implementation existed.
- System areas affected: docs.
- Likely behavior impact: No runtime behavior; created project governance and planning references.
- Historical/current status: Historical foundation; later implementation commits supersede parts of the early planning docs.

### 2. `42483df` - 2026-04-22 - Phase 0 complete: scaffold + memory system (no logic)

- Body/description: None beyond subject.
- Files added: `EXECUTION_RULES.md`, `KNOWN_FAILURES.md`, `MARKET_NOTES.md`, `MASTER_STRATEGY.md`, `RESEARCH_LOG.md`, `RISK_RULES.md`, `SIGNAL_RULES.md`, `TRADE_LOG.md`, `kalshi_bot/__init__.py`, `kalshi_bot/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/auth/__init__.py`, `kalshi_bot/auth/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/auth/__pycache__/auth_manager.cpython-313.pyc`, `kalshi_bot/auth/auth_manager.py`, `kalshi_bot/clients/__init__.py`, `kalshi_bot/clients/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/crypto_feed_client.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/kalshi_client.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/websocket_client.cpython-313.pyc`, `kalshi_bot/clients/crypto_feed_client.py`, `kalshi_bot/clients/kalshi_client.py`, `kalshi_bot/clients/websocket_client.py`, `kalshi_bot/contracts/__init__.py`, `kalshi_bot/contracts/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/contracts/__pycache__/contract_scanner.cpython-313.pyc`, `kalshi_bot/contracts/__pycache__/contract_scorer.cpython-313.pyc`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/contracts/contract_scorer.py`, `kalshi_bot/execution/__init__.py`, `kalshi_bot/execution/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/execution/__pycache__/execution_engine.cpython-313.pyc`, `kalshi_bot/execution/__pycache__/exit_manager.cpython-313.pyc`, `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/exit_manager.py`, `kalshi_bot/forecast/__init__.py`, `kalshi_bot/forecast/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/forecast/__pycache__/bias_engine.cpython-313.pyc`, `kalshi_bot/forecast/__pycache__/state_classifier.cpython-313.pyc`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/forecast/state_classifier.py`, `kalshi_bot/market/__init__.py`, `kalshi_bot/market/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/market/__pycache__/market_state_cache.cpython-313.pyc`, `kalshi_bot/market/market_state_cache.py`, `kalshi_bot/observability/__init__.py`, `kalshi_bot/observability/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/observability/__pycache__/logger.cpython-313.pyc`, `kalshi_bot/observability/__pycache__/replay_engine.cpython-313.pyc`, `kalshi_bot/observability/logger.py`, `kalshi_bot/observability/replay_engine.py`, `kalshi_bot/risk/__init__.py`, `kalshi_bot/risk/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/risk/__pycache__/risk_manager.cpython-313.pyc`, `kalshi_bot/risk/risk_manager.py`, `kalshi_bot/timing/__init__.py`, `kalshi_bot/timing/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/timing/__pycache__/time_sync_checker.cpython-313.pyc`, `kalshi_bot/timing/time_sync_checker.py`.
- Files modified: `AGENTS.md`, `BUILD_PHASES.md`, `MASTER_SPEC.md`.
- Files deleted: None.
- Stats: 61 files changed, 296 insertions, 14 deletions.
- High-level summary: Inference from diff. Added the initial Python package/module skeleton and supporting memory docs without meaningful strategy logic.
- System areas affected: config/env, scanner, scoring, bias/direction, execution, risk, replay/audit scripts, docs, telemetry/logging.
- Likely behavior impact: Minimal runtime behavior; mostly placeholders and structure.
- Historical/current status: Current package layout foundation; tracked `__pycache__` artifacts were later removed.

### 3. `d68ef29` - 2026-04-23 - Phase 1 complete: auth + environment validated against Kalshi demo

- Body/description: None beyond subject.
- Files added: `.env.example`, `.gitignore`, `kalshi_bot/config/__init__.py`, `kalshi_bot/config/settings.py`, `requirements.txt`, `scripts/check_kalshi_auth.py`.
- Files modified: `kalshi_bot/auth/auth_manager.py`, `kalshi_bot/clients/kalshi_client.py`.
- Files deleted: None.
- Stats: 8 files changed, 386 insertions, 6 deletions.
- High-level summary: Inference from diff. Introduced environment loading, dependencies, Kalshi auth/client wiring, and an auth validation script.
- System areas affected: config/env, execution, tests.
- Likely behavior impact: Enabled demo-auth validation; no live trading enabled by default.
- Historical/current status: Still current as auth/settings foundation, though env controls changed many times later.

### 4. `cc6518e` - 2026-04-23 - Phase 2 complete: WebSocket + market state cache validated on Kalshi demo

- Body/description: None beyond subject.
- Files added: `scripts/check_kalshi_websocket.py`.
- Files modified: `.env.example`, `kalshi_bot/clients/websocket_client.py`, `kalshi_bot/config/settings.py`, `kalshi_bot/market/market_state_cache.py`, `requirements.txt`.
- Files deleted: None.
- Stats: 6 files changed, 979 insertions, 8 deletions.
- High-level summary: Inference from diff. Added Kalshi WebSocket connectivity and market state cache validation.
- System areas affected: config/env, scanner, telemetry/logging, tests.
- Likely behavior impact: Enabled streaming market updates into cache for later scanner/runner use.
- Historical/current status: Current subsystem foundation, refined by later market normalization and rollover commits.

### 5. `0ab1723` - 2026-04-23 - Phase 3 complete: external crypto feed validated with Coinbase WebSocket

- Body/description: None beyond subject.
- Files added: `scripts/check_crypto_feed.py`.
- Files modified: `.env.example`, `kalshi_bot/clients/crypto_feed_client.py`, `kalshi_bot/config/settings.py`.
- Files deleted: None.
- Stats: 4 files changed, 540 insertions, 3 deletions.
- High-level summary: Inference from diff. Added external crypto feed support and validation.
- System areas affected: config/env, scanner, telemetry/logging, tests.
- Likely behavior impact: Provided external crypto price inputs for bias and market scanning.
- Historical/current status: Still current as feed foundation, refined by later latency and recovery work.

### 6. `7c525d8` - 2026-04-23 - Phase 4 complete: logging, replay storage, and time sync implemented and validated

- Body/description: None beyond subject.
- Files added: `scripts/check_phase4_observability.py`.
- Files modified: `.env.example`, `.gitignore`, `kalshi_bot/config/settings.py`, `kalshi_bot/observability/logger.py`, `kalshi_bot/observability/replay_engine.py`, `kalshi_bot/timing/time_sync_checker.py`.
- Files deleted: None.
- Stats: 7 files changed, 541 insertions, 9 deletions.
- High-level summary: Inference from diff. Added logging, replay persistence, time-sync checks, and validation.
- System areas affected: config/env, replay/audit scripts, telemetry/logging, tests.
- Likely behavior impact: Improved auditability and timing safety diagnostics.
- Historical/current status: Still current as observability base, extended later by replay roadmap and latency diagnostics.

### 7. `b7b1576` - 2026-04-23 - Phase 5 complete: bias engine implemented with stateful history and validated via fixtures

- Body/description: None beyond subject.
- Files added: `scripts/check_phase5_bias_engine.py`.
- Files modified: `.env.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/forecast/state_classifier.py`.
- Files deleted: None.
- Stats: 5 files changed, 726 insertions, 6 deletions.
- High-level summary: Inference from diff. Implemented the first stateful bias/direction engine and tests.
- System areas affected: config/env, bias/direction, tests.
- Likely behavior impact: Added directional bias classification used by later scanner ranking.
- Historical/current status: Current foundation, heavily refined by impulse, quiet continuation, stabilization, and progression commits.

### 8. `c803876` - 2026-04-23 - Phase 6 complete: contract scanner and core ranking implemented and validated

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/contracts/contract_scorer.py`.
- Files deleted: None.
- Stats: 4 files changed, 246 insertions, 6 deletions.
- High-level summary: Inference from diff. Added initial scanner and core contract ranking/scoring.
- System areas affected: config/env, scanner, scoring.
- Likely behavior impact: Enabled contract candidate discovery and ranking.
- Historical/current status: Foundation still present; scoring/gating behavior was substantially superseded by later calibration commits.

### 9. `bc4737a` - 2026-04-23 - Phase 6 fix: add missing validation script

- Body/description: None beyond subject.
- Files added: `scripts/check_phase6_contract_scanner.py`.
- Files modified: None.
- Files deleted: None.
- Stats: 1 file changed, 305 insertions.
- High-level summary: Added the missing scanner validation script.
- System areas affected: scanner, scoring, tests.
- Likely behavior impact: No direct bot behavior change; added scanner verification coverage.
- Historical/current status: Still current test lineage, updated many times later.

### 10. `b8db0b6` - 2026-04-23 - Phase 7 complete: simulation execution engine implemented and validated

- Body/description: None beyond subject.
- Files added: `scripts/check_phase7_simulation.py`.
- Files modified: `.env.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`.
- Files deleted: None.
- Stats: 4 files changed, 563 insertions, 3 deletions.
- High-level summary: Inference from diff. Implemented simulation entry/execution behavior and validation.
- System areas affected: config/env, execution, tests.
- Likely behavior impact: Enabled simulated trade execution path.
- Historical/current status: Simulation path became less central after direct live execution was added.

### 11. `e02deae` - 2026-04-23 - Phase 8 complete: simulation exit logic implemented and validated

- Body/description: None beyond subject.
- Files added: `scripts/check_phase8_exit_logic.py`.
- Files modified: `.env.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/exit_manager.py`.
- Files deleted: None.
- Stats: 5 files changed, 647 insertions, 34 deletions.
- High-level summary: Inference from diff. Added simulation exit management and tests.
- System areas affected: config/env, execution, tests.
- Likely behavior impact: Added simulated position lifecycle and exit decisions.
- Historical/current status: Partly superseded by later controlled exits, live exits, and direct live execution.

### 12. `3a290e8` - 2026-04-23 - Phase 9 complete: live execution smoke test with IOC order, polling, classification, and balance verification"

- Body/description: None beyond subject.
- Files added: `scripts/check_phase9_live_execution.py`.
- Files modified: `.env.example`, `kalshi_bot/clients/kalshi_client.py`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`.
- Files deleted: None.
- Stats: 5 files changed, 1034 insertions, 12 deletions.
- High-level summary: Inference from diff. Added live execution smoke-test support around IOC order flow, polling, classification, and balance checks.
- System areas affected: config/env, execution, risk, tests.
- Likely behavior impact: Introduced live-order-capable code paths guarded by configuration/testing controls.
- Historical/current status: Live execution foundation; superseded by later guarded live coordinator and direct live execution path.

### 13. `814046c` - 2026-04-23 - Phase 10 complete: live guardrails, kill switch, and safeguarded execution path

- Body/description: None beyond subject.
- Files added: `scripts/check_phase10_live_guardrails.py`.
- Files modified: `.env.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/risk/risk_manager.py`.
- Files deleted: None.
- Stats: 5 files changed, 514 insertions, 3 deletions.
- High-level summary: Inference from diff. Added live guardrails, kill switch controls, and guarded execution checks.
- System areas affected: config/env, execution, risk, tests.
- Likely behavior impact: Strengthened protection around any live execution path.
- Historical/current status: Still current guardrail lineage, extended by later risk/env controls.

### 14. `e15e41c` - 2026-04-23 - Add post-Phase-10 VPS deployment readiness docs

- Body/description: None beyond subject.
- Files added: `.env.production.example`, `DEPLOYMENT.md`, `VPS_RUNBOOK.md`, `systemd/kalshi-bot.service.example`.
- Files modified: `.gitignore`.
- Files deleted: None.
- Stats: 5 files changed, 373 insertions.
- High-level summary: Added deployment-oriented docs, production env example, and systemd example.
- System areas affected: config/env, docs, runner/orchestrator.
- Likely behavior impact: No bot logic change; documented operational deployment.
- Historical/current status: Likely partially stale because runtime controls changed extensively after this commit.

### 15. `65b0d32` - 2026-04-24 - Add continuous simulation runner and ranking diagnostics

- Body/description: None beyond subject.
- Files added: `kalshi_bot/runner/__init__.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`, `scripts/run_kalshi_bot.py`.
- Files modified: `DEPLOYMENT.md`, `VPS_RUNBOOK.md`, `kalshi_bot/config/settings.py`, `systemd/kalshi-bot.service.example`.
- Files deleted: None.
- Stats: 8 files changed, 1172 insertions, 17 deletions.
- High-level summary: Inference from diff. Added the continuous runner/orchestrator and ranking diagnostics.
- System areas affected: config/env, runner/orchestrator, scanner, scoring, telemetry/logging, tests, docs.
- Likely behavior impact: Enabled continuous simulation lifecycle around scanning and ranking.
- Historical/current status: Runner foundation still current; simulation-first assumptions later superseded by direct live path.

### 16. `62ff436` - 2026-04-24 - Complete market discovery, websocket wiring, and market state normalization

- Body/description: None beyond subject.
- Files added: `kalshi_bot/market/crypto_market_discovery.py`.
- Files modified: `.env.example`, `.env.production.example`, `DEPLOYMENT.md`, `VPS_RUNBOOK.md`, `kalshi_bot/clients/kalshi_client.py`, `kalshi_bot/clients/websocket_client.py`, `kalshi_bot/config/settings.py`, `kalshi_bot/market/market_state_cache.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`, `scripts/run_kalshi_bot.py`.
- Files deleted: None.
- Stats: 12 files changed, 1094 insertions, 133 deletions.
- High-level summary: Inference from diff. Added market discovery and normalized market state wiring into the runner.
- System areas affected: config/env, scanner, runner/orchestrator, telemetry/logging, tests, docs.
- Likely behavior impact: Improved automatic market discovery and cache normalization.
- Historical/current status: Still current foundation, refined by later rollover and recovery commits.

### 17. `aa68008` - 2026-04-25 - Add simulation trade lifecycle logging

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 2 files changed, 258 insertions, 9 deletions.
- High-level summary: Inference from diff. Added lifecycle logging for simulated trades in the runner.
- System areas affected: runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Improved traceability for simulation decisions.
- Historical/current status: Historical for simulation path; logging pattern remains relevant.

### 18. `6baaffc` - 2026-04-25 - Phase A: add hold and controlled simulation exits

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/exit_manager.py`, `scripts/check_phase7_simulation.py`, `scripts/check_phase8_exit_logic.py`.
- Files deleted: None.
- Stats: 3 files changed, 211 insertions, 21 deletions.
- High-level summary: Inference from diff. Added hold behavior and controlled exits for simulation positions.
- System areas affected: execution, tests.
- Likely behavior impact: Simulation exits became more controlled and less immediate.
- Historical/current status: Partly superseded by later live exit logic.

### 19. `55219b5` - 2026-04-25 - Phase B: add entry price protection

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/execution_engine.py`, `scripts/check_phase7_simulation.py`.
- Files deleted: None.
- Stats: 2 files changed, 109 insertions.
- High-level summary: Inference from diff. Added entry price protection to the execution engine.
- System areas affected: execution, risk, tests.
- Likely behavior impact: Reduced unsafe or unfavorable simulated entries.
- Historical/current status: Superseded/refined by later live IOC pricing and EV/risk protections.

### 20. `11036f0` - 2026-04-25 - Phase D1: make bias diagnostics dynamic

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/runner/orchestrator.py`.
- Files deleted: None.
- Stats: 1 file changed, 17 insertions, 3 deletions.
- High-level summary: Inference from diff. Made runner bias diagnostics dynamic rather than static.
- System areas affected: bias/direction, runner/orchestrator, telemetry/logging.
- Likely behavior impact: More accurate diagnostic output for bias state.
- Historical/current status: Current diagnostic lineage, expanded later.

### 21. `dedfa49` - 2026-04-25 - "Phase D3: add SOL and XRP market defaults"

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`.
- Files deleted: None.
- Stats: 3 files changed, 10 insertions, 8 deletions.
- High-level summary: Inference from diff. Added SOL and XRP to default market configuration.
- System areas affected: config/env, scanner.
- Likely behavior impact: Expanded default tracked crypto markets.
- Historical/current status: Later expanded again by DOGE, BNB, and HYPE defaults.

### 22. `74563cd` - 2026-04-25 - Phase E1: add percentage-based risk model

- Body/description: None beyond subject.
- Files added: `scripts/check_phaseE1_risk_model.py`.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/risk/risk_manager.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 6 files changed, 474 insertions.
- High-level summary: Inference from diff. Added percentage-based risk sizing and validation.
- System areas affected: config/env, risk, tests.
- Likely behavior impact: Introduced risk sizing based on configured percentage/exposure constraints.
- Historical/current status: Risk foundation current, with many later stake/exposure refinements.

### 23. `60de9be` - 2026-04-25 - Phase E2: wire risk engine into simulation entries

- Body/description: None beyond subject.
- Files added: `scripts/check_phaseE2_simulation_risk.py`.
- Files modified: `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/exit_manager.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase7_simulation.py`, `scripts/check_phase8_exit_logic.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 7 files changed, 389 insertions, 3 deletions.
- High-level summary: Inference from diff. Connected risk decisions to simulation entries and exits.
- System areas affected: execution, risk, runner/orchestrator, tests.
- Likely behavior impact: Simulation entries became risk-approved.
- Historical/current status: Partly historical; live paths later required risk approval too.

### 24. `8fe99ce` - 2026-04-25 - Phase E3: refine exposure daily loss and risk logging

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseE2_simulation_risk.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 4 files changed, 253 insertions, 9 deletions.
- High-level summary: Inference from diff. Refined exposure, daily loss handling, and risk logging.
- System areas affected: execution, risk, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Improved risk traceability and loss/exposure enforcement.
- Historical/current status: Still current risk lineage, modified by later live risk env controls.

### 25. `af55217` - 2026-04-25 - Phase F1: add live order intent model

- Body/description: None beyond subject.
- Files added: `scripts/check_phaseF1_live_order_intent.py`.
- Files modified: `kalshi_bot/execution/execution_engine.py`.
- Files deleted: None.
- Stats: 2 files changed, 210 insertions.
- High-level summary: Inference from diff. Added live order intent representation and tests.
- System areas affected: execution, tests.
- Likely behavior impact: Created a safer intermediate representation before live order submission.
- Historical/current status: Still current concept, later moved through live coordinator path.

### 26. `82f6d74` - 2026-04-25 - Phase F2: add dry-run live execution coordinator

- Body/description: None beyond subject.
- Files added: `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`.
- Files modified: None.
- Files deleted: None.
- Stats: 2 files changed, 327 insertions.
- High-level summary: Inference from diff. Added live execution coordinator in dry-run mode with tests.
- System areas affected: execution, risk, tests.
- Likely behavior impact: Introduced coordinator boundary for live-order decisions without enabling live submission by default.
- Historical/current status: Current central live execution module, heavily expanded later.

### 27. `5f5b6a0` - 2026-04-25 - Phase F3: wire dry-run live coordinator into runner

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 2 files changed, 148 insertions.
- High-level summary: Inference from diff. Connected the dry-run live coordinator to runner lifecycle.
- System areas affected: execution, runner/orchestrator, tests.
- Likely behavior impact: Runner could exercise live-intent flow in guarded/dry-run form.
- Historical/current status: Current wiring lineage; live path later became direct and more guarded.

### 28. `354006c` - 2026-04-25 - Phase F4: add guarded live submission path

- Body/description: None beyond subject.
- Files added: `scripts/check_phaseF4_live_submission.py`.
- Files modified: `kalshi_bot/execution/live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 2 files changed, 633 insertions, 4 deletions.
- High-level summary: Inference from diff. Added guarded live order submission behavior and tests.
- System areas affected: execution, risk, tests.
- Likely behavior impact: Live submission became possible only through guard checks.
- Historical/current status: Still current guardrail lineage, refined repeatedly.

### 29. `c163c40` - 2026-04-25 - Phase F5: add live position ledger reconciliation

- Body/description: None beyond subject.
- Files added: `scripts/check_phaseF5_live_position_ledger.py`.
- Files modified: `kalshi_bot/execution/live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 2 files changed, 524 insertions, 4 deletions.
- High-level summary: Inference from diff. Added live position ledger reconciliation.
- System areas affected: execution, risk, telemetry/logging, tests.
- Likely behavior impact: Improved live exposure/accounting consistency.
- Historical/current status: Still current, expanded by later live reconciliation changes.

### 30. `b43465f` - 2026-04-25 - Phase F6A: require risk-approved live intents

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phaseF1_live_order_intent.py`, `scripts/check_phaseF4_live_submission.py`, `scripts/check_phaseF5_live_position_ledger.py`.
- Files deleted: None.
- Stats: 5 files changed, 65 insertions, 5 deletions.
- High-level summary: Inference from diff. Required live intents to carry risk approval.
- System areas affected: execution, risk, tests.
- Likely behavior impact: Hardened live execution so risk approval is mandatory.
- Historical/current status: Current hard protection lineage.

### 31. `8762f71` - 2026-04-25 - Phase G2: enable guarded autonomous runner live execution

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`, `scripts/run_kalshi_bot.py`.
- Files deleted: None.
- Stats: 6 files changed, 273 insertions, 5 deletions.
- High-level summary: Inference from diff. Added config and runner support for guarded autonomous live execution.
- System areas affected: config/env, execution, risk, runner/orchestrator, tests.
- Likely behavior impact: Allowed autonomous live execution only behind live settings and guardrails.
- Historical/current status: Current lineage; later direct-live and guard refinements supersede details.

### 32. `25d59bc` - 2026-04-26 - "Phase J1: add impulse diagnostics to bias engine"

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase5_bias_engine.py`, `scripts/run_kalshi_bot.py`.
- Files deleted: None.
- Stats: 4 files changed, 190 insertions.
- High-level summary: Inference from diff. Added impulse diagnostics to bias engine and runner output.
- System areas affected: bias/direction, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Improved visibility into short-term impulse context.
- Historical/current status: Still current diagnostic lineage, later refined by weak impulse filtering and progression memory.

### 33. `4a8b859` - 2026-04-26 - Phase J2: enable impulse override for neutral chop bias

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/forecast/bias_engine.py`, `scripts/check_phase5_bias_engine.py`.
- Files deleted: None.
- Stats: 2 files changed, 173 insertions, 1 deletion.
- High-level summary: Inference from diff. Allowed impulse logic to override neutral/chop bias under tested conditions.
- System areas affected: bias/direction, tests.
- Likely behavior impact: Could produce directional bias in otherwise neutral chop conditions.
- Historical/current status: Later commits downgraded weak impulse noise and added stronger gating.

### 34. `6384f04` - 2026-04-26 - Phase J3: add late expansion scanner guard

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/contracts/contract_scanner.py`, `scripts/check_phase6_contract_scanner.py`.
- Files deleted: `kalshi_bot/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/auth/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/auth/__pycache__/auth_manager.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/crypto_feed_client.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/kalshi_client.cpython-313.pyc`, `kalshi_bot/clients/__pycache__/websocket_client.cpython-313.pyc`, `kalshi_bot/contracts/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/contracts/__pycache__/contract_scanner.cpython-313.pyc`, `kalshi_bot/contracts/__pycache__/contract_scorer.cpython-313.pyc`, `kalshi_bot/execution/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/execution/__pycache__/execution_engine.cpython-313.pyc`, `kalshi_bot/execution/__pycache__/exit_manager.cpython-313.pyc`, `kalshi_bot/forecast/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/forecast/__pycache__/bias_engine.cpython-313.pyc`, `kalshi_bot/forecast/__pycache__/state_classifier.cpython-313.pyc`, `kalshi_bot/market/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/market/__pycache__/market_state_cache.cpython-313.pyc`, `kalshi_bot/observability/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/observability/__pycache__/logger.cpython-313.pyc`, `kalshi_bot/observability/__pycache__/replay_engine.cpython-313.pyc`, `kalshi_bot/risk/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/risk/__pycache__/risk_manager.cpython-313.pyc`, `kalshi_bot/timing/__pycache__/__init__.cpython-313.pyc`, `kalshi_bot/timing/__pycache__/time_sync_checker.cpython-313.pyc`.
- Stats: 27 files changed, 128 insertions.
- High-level summary: Inference from diff. Added a late-expansion scanner guard and removed tracked generated Python cache artifacts.
- System areas affected: scanner, tests.
- Likely behavior impact: Scanner could reject late expansion conditions; cleanup removed generated artifacts from source history.
- Historical/current status: Guard lineage current, later expanded by exhaustion and progression guards.

### 35. `1a115c9` - 2026-04-26 - Phase J4: add impulse continuation confirmation guard

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/contracts/contract_scanner.py`, `scripts/check_phase6_contract_scanner.py`.
- Files deleted: None.
- Stats: 2 files changed, 189 insertions.
- High-level summary: Inference from diff. Added scanner confirmation requirements for impulse continuation.
- System areas affected: scanner, bias/direction, tests.
- Likely behavior impact: Reduced continuation entries without sufficient impulse confirmation.
- Historical/current status: Current gating lineage, refined by later trend/exhaustion checks.

### 36. `fbad615` - 2026-04-26 - fix: enable direct live execution path and remove simulation dependency

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseF1_live_order_intent.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_phaseF4_live_submission.py`, `scripts/check_runner_lifecycle.py`, `scripts/run_kalshi_bot.py`.
- Files deleted: None.
- Stats: 8 files changed, 613 insertions, 34 deletions.
- High-level summary: Inference from diff. Removed dependency on simulation execution for direct live execution flow.
- System areas affected: execution, runner/orchestrator, tests.
- Likely behavior impact: Live execution path became more direct while still using coordinator/guard checks.
- Historical/current status: Current architectural pivot; earlier simulation-first execution assumptions are superseded.

### 37. `2fde7be` - 2026-05-02 - Changed stake min + contract cap

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/risk/risk_manager.py`.
- Files deleted: None.
- Stats: 1 file changed, 11 insertions, 11 deletions.
- High-level summary: Inference from diff. Adjusted minimum stake and contract cap risk values.
- System areas affected: risk.
- Likely behavior impact: Changed order sizing/count limits.
- Historical/current status: Likely superseded by later stake/cap commits.

### 38. `0efb948` - 2026-05-02 - feat: add DOGE BNB HYPE to OG market tracking

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/market/crypto_market_discovery.py`.
- Files deleted: None.
- Stats: 4 files changed, 49 insertions, 10 deletions.
- High-level summary: Inference from diff. Expanded tracked crypto products to DOGE, BNB, and HYPE.
- System areas affected: config/env, scanner.
- Likely behavior impact: Broadened market discovery/tracking universe.
- Historical/current status: Still current if these products remain configured.

### 39. `792848f` - 2026-05-02 - Fix for stake min

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/config/settings.py`, `kalshi_bot/risk/risk_manager.py`.
- Files deleted: None.
- Stats: 2 files changed, 11 insertions, 11 deletions.
- High-level summary: Inference from diff. Corrected stake minimum handling in settings/risk.
- System areas affected: config/env, risk.
- Likely behavior impact: Adjusted minimum stake enforcement.
- Historical/current status: Likely superseded by `c2af004` and later live risk controls.

### 40. `5cd561a` - 2026-05-02 - Fix contract cap to 1000

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/risk/risk_manager.py`, `kalshi_bot/runner/orchestrator.py`.
- Files deleted: None.
- Stats: 2 files changed, 3 insertions, 3 deletions.
- High-level summary: Inference from diff. Set contract cap to 1000 in risk/runner behavior.
- System areas affected: risk, runner/orchestrator.
- Likely behavior impact: Changed max contract count constraint.
- Historical/current status: May be superseded by later stake/exposure controls; current status depends on settings/risk code.

### 41. `6101a69` - 2026-05-02 - "fix: price live IOC orders from executable side ask

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/risk/risk_manager.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 7 files changed, 286 insertions, 16 deletions.
- High-level summary: Inference from diff. Changed live IOC pricing to use the executable side ask.
- System areas affected: config/env, execution, risk, runner/orchestrator, tests.
- Likely behavior impact: Live order pricing aligned with executable side liquidity instead of stale or non-executable reference pricing.
- Historical/current status: Current pricing lineage, refined by later risk/reward bound and side-aware EV pricing.

### 42. `9d833dd` - 2026-05-02 - fix: bound executable IOC pricing to preserve risk reward

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/config/settings.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/risk/risk_manager.py`, `scripts/check_phaseF2_live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 4 files changed, 213 insertions, 25 deletions.
- High-level summary: Inference from diff. Added bounds around executable IOC pricing to preserve risk/reward.
- System areas affected: config/env, execution, risk, tests.
- Likely behavior impact: Prevented live orders from accepting executable prices outside risk/reward limits.
- Historical/current status: Current hard-protection lineage.

### 43. `d865627` - 2026-05-03 - feat: add live exits end-window entries and feed recovery

- Body/description: None beyond subject.
- Files added: `scripts/check_live_profit_capture_exit.py`.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/clients/kalshi_client.py`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 1498 insertions, 10 deletions.
- High-level summary: Inference from diff. Added live exit handling, end-window entries, and feed recovery behavior.
- System areas affected: config/env, scanner, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Expanded live lifecycle handling and recovery resilience.
- Historical/current status: Still current lineage, refined by later pacing/reconciliation/rollover commits.

### 44. `ceedf3b` - 2026-05-03 - feat: live reconciliation + cache-only fast scan

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/risk/risk_manager.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseF5_live_position_ledger.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 8 files changed, 551 insertions, 20 deletions.
- High-level summary: Inference from diff. Added live reconciliation improvements and cache-only fast scan support.
- System areas affected: config/env, scanner, execution, risk, runner/orchestrator, tests.
- Likely behavior impact: Improved live position/exposure reconciliation and scan speed.
- Historical/current status: Still current.

### 45. `c2af004` - 2026-05-04 - UPDATE TO STAKE MIN

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/config/settings.py`, `kalshi_bot/risk/risk_manager.py`.
- Files deleted: None.
- Stats: 2 files changed, 4 insertions, 4 deletions.
- High-level summary: Inference from diff. Updated minimum stake configuration/risk enforcement.
- System areas affected: config/env, risk.
- Likely behavior impact: Changed live/simulation stake floor behavior.
- Historical/current status: Later stake/exposure controls may supersede exact values.

### 46. `ad73b72` - 2026-05-05 - prevent weak impulse noise, scale confidence, and expose full bias diagnostics in live intents

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase5_bias_engine.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 217 insertions, 3 deletions.
- High-level summary: Inference from diff. Filtered weak impulse noise, scaled confidence, and propagated fuller bias diagnostics into live intents.
- System areas affected: config/env, scanner, scoring, bias/direction, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Reduced noisy directional triggers and improved live decision diagnostics.
- Historical/current status: Current lineage, refined by later trend/exhaustion/composite scoring.

### 47. `b3ef9bc` - 2026-05-05 - Min stake/Max exposure

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/config/settings.py`, `kalshi_bot/risk/risk_manager.py`.
- Files deleted: None.
- Stats: 2 files changed, 6 insertions, 6 deletions.
- High-level summary: Inference from diff. Adjusted minimum stake and maximum exposure settings/risk behavior.
- System areas affected: config/env, risk.
- Likely behavior impact: Changed stake/exposure limits.
- Historical/current status: Partly superseded by later live risk env controls.

### 48. `2d9009b` - 2026-05-06 - fix: add target-feasibility diagnostics and downgrade noisy reversals

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/clients/kalshi_client.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/market/crypto_market_discovery.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 8 files changed, 609 insertions, 9 deletions.
- High-level summary: Inference from diff. Added target-feasibility diagnostics and downgraded noisy reversal candidates.
- System areas affected: scanner, bias/direction, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Made reversal handling more conservative and improved feasibility traceability.
- Historical/current status: Current reversal caution lineage, later made shadow-only by default.

### 49. `7121efe` - 2026-05-07 - refine: tighten feasibility gating, trend confirmation, and live flip persistence

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 5 files changed, 740 insertions, 15 deletions.
- High-level summary: Inference from diff. Tightened feasibility gates, trend confirmation, and live flip persistence.
- System areas affected: scanner, bias/direction, execution, runner/orchestrator, tests.
- Likely behavior impact: Reduced weak flips and required stronger trend/feasibility evidence.
- Historical/current status: Current gating lineage.

### 50. `606a4fd` - 2026-05-07 - chore: add live risk env controls

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/execution_engine.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/risk/risk_manager.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase10_live_guardrails.py`, `scripts/check_phaseE1_risk_model.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 371 insertions, 26 deletions.
- High-level summary: Inference from diff. Added environment controls for live risk constraints.
- System areas affected: config/env, execution, risk, runner/orchestrator, tests.
- Likely behavior impact: Made live risk limits externally configurable while retaining guardrails.
- Historical/current status: Current hard-protection lineage.

### 51. `bf73d4e` - 2026-05-07 - chore: add default-off latency diagnostics logging

- Body/description: None beyond subject.
- Files added: `kalshi_bot/observability/latency_diagnostics.py`, `scripts/check_latency_diagnostics.py`.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/clients/crypto_feed_client.py`, `kalshi_bot/clients/websocket_client.py`, `kalshi_bot/config/settings.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 9 files changed, 688 insertions, 2 deletions.
- High-level summary: Inference from diff. Added latency diagnostics logging that is default-off.
- System areas affected: config/env, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Added optional latency observability without changing default behavior.
- Historical/current status: Still current; fixed by next latency commit.

### 52. `2efbe11` - 2026-05-07 - chore: fix latency diagnostics orderbook top-of-book logging

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/observability/latency_diagnostics.py`, `scripts/check_latency_diagnostics.py`.
- Files deleted: None.
- Stats: 2 files changed, 232 insertions, 20 deletions.
- High-level summary: Inference from diff. Fixed top-of-book orderbook fields in latency diagnostics.
- System areas affected: telemetry/logging, tests.
- Likely behavior impact: Made latency diagnostics more accurate.
- Historical/current status: Current.

### 53. `bc6d821` - 2026-05-07 - refine: add settlement-quality entry gates

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 4 files changed, 695 insertions, 21 deletions.
- High-level summary: Inference from diff. Added settlement-quality gates for entries.
- System areas affected: scanner, execution, risk, tests.
- Likely behavior impact: Reduced entries with poor settlement-quality characteristics.
- Historical/current status: Current gating lineage.

### 54. `eeff79a` - 2026-05-08 - chore: add official Kalshi outcome export utility

- Body/description: None beyond subject.
- Files added: `scripts/export_official_kalshi_outcomes.py`.
- Files modified: None.
- Files deleted: None.
- Stats: 1 file changed, 707 insertions.
- High-level summary: Added utility for exporting official Kalshi outcomes.
- System areas affected: replay/audit scripts.
- Likely behavior impact: No live bot behavior; improved audit/outcome tooling.
- Historical/current status: Current utility, later modified by roadmap replay work.

### 55. `2458a5e` - 2026-05-08 - refine live signal quality with reversal hold and entry pacing

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase10_live_guardrails.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 1077 insertions, 12 deletions.
- High-level summary: Inference from diff. Added reversal hold behavior and entry pacing controls.
- System areas affected: config/env, scanner, bias/direction, execution, runner/orchestrator, tests.
- Likely behavior impact: Made live entries less aggressive around reversals and pacing.
- Historical/current status: Current lineage, later refined by shadow-only reversal and composite gates.

### 56. `6255489` - 2026-05-08 - fix: refresh expired Kalshi markets on rollover

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 6 files changed, 442 insertions, 8 deletions.
- High-level summary: Inference from diff. Refreshed expired Kalshi markets during rollover.
- System areas affected: scanner, execution, runner/orchestrator, tests.
- Likely behavior impact: Reduced stale market use around market rollover.
- Historical/current status: Current.

### 57. `d7c0152` - 2026-05-08 - refine live entry quality with composite trend and distance filters

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phase10_live_guardrails.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 7 files changed, 1039 insertions, 3 deletions.
- High-level summary: Inference from diff. Added composite trend and distance filters to live entry quality checks.
- System areas affected: config/env, scoring, execution, risk, tests.
- Likely behavior impact: Raised quality threshold for live entries.
- Historical/current status: Superseded/refined by later progression-aware composite scoring and danger calibration.

### 58. `670ff05` - 2026-05-09 - implement EV-aware ITM trade overrides and conditional blocker bypass

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phase10_live_guardrails.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 7 files changed, 1191 insertions, 22 deletions.
- High-level summary: Inference from diff. Added EV-aware in-the-money trade overrides and conditional bypass of some blockers.
- System areas affected: config/env, execution, risk, tests.
- Likely behavior impact: Allowed some EV-qualified candidates to bypass selected blockers while retaining EV/risk constraints.
- Historical/current status: Current EV lineage, later adjusted by side-aware pricing and EV cap semantics.

### 59. `c6edd69` - 2026-05-09 - fix side-aware EV pricing for BUY NO candidates

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`.
- Files deleted: None.
- Stats: 2 files changed, 346 insertions, 6 deletions.
- High-level summary: Inference from diff. Fixed EV pricing to handle BUY NO side correctly.
- System areas affected: execution, risk, tests.
- Likely behavior impact: Corrected EV/risk calculations for BUY NO candidates.
- Historical/current status: Current.

### 60. `a7513f0` - 2026-05-09 - add quiet continuation scanner path with enhanced bias diagnostics

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/forecast/state_classifier.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase5_bias_engine.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 11 files changed, 735 insertions, 30 deletions.
- High-level summary: Inference from diff. Added quiet continuation scanner path and richer bias diagnostics.
- System areas affected: config/env, scanner, bias/direction, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Added a lower-noise continuation path with diagnostic support.
- Historical/current status: Current lineage, tightened by later quiet continuation/exhaustion commits.

### 61. `d8e1c8d` - 2026-05-09 - fix quiet continuation runner wiring and add candidate funnel diagnostics

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase10_live_guardrails.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 8 files changed, 636 insertions, 13 deletions.
- High-level summary: Inference from diff. Fixed quiet continuation runner integration and added candidate funnel diagnostics.
- System areas affected: config/env, scanner, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Made quiet continuation decisions observable through runner diagnostics.
- Historical/current status: Current lineage.

### 62. `58b28da` - 2026-05-10 - add exhaustion-aware momentum guards and tighten quiet continuation logic

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 1376 insertions, 24 deletions.
- High-level summary: Inference from diff. Added exhaustion-aware momentum guards and tightened quiet continuation behavior.
- System areas affected: config/env, scanner, scoring, bias/direction, execution, runner/orchestrator, tests.
- Likely behavior impact: Reduced burst/exhaustion chasing and made quiet continuation more conservative.
- Historical/current status: Current guard lineage, refined by progression-aware exhaustion.

### 63. `6e5617e` - 2026-05-12 - add conservative state stabilization controls

- Body/description: None beyond subject.
- Files added: `CURRENT_ENV_BEHAVIOR_REFERENCE.md`.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/forecast/bias_engine.py`, `kalshi_bot/forecast/state_classifier.py`, `scripts/check_phase5_bias_engine.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 12 files changed, 1190 insertions, 57 deletions.
- High-level summary: Inference from diff. Added conservative stabilization controls and a current environment behavior reference.
- System areas affected: config/env, scanner, bias/direction, execution, docs, tests.
- Likely behavior impact: Added conservative stabilization paths without bypassing existing EV/risk protections.
- Historical/current status: Current lineage; reference doc updated later and is a better source than older docs.

### 64. `f05c5ef` - 2026-05-13 - Add progression-aware exhaustion guard refinement

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.example`, `.env.production.example`, `CURRENT_ENV_BEHAVIOR_REFERENCE.md`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 1064 insertions, 19 deletions.
- High-level summary: Inference from diff. Refined exhaustion guard behavior using progression-aware context.
- System areas affected: config/env, scanner, scoring, execution, runner/orchestrator, docs, tests.
- Likely behavior impact: Allowed more nuanced treatment of exhaustion while retaining downstream gates.
- Historical/current status: Current lineage, expanded by roadmap scoring.

### 65. `08b9481` - 2026-05-15 - Implement progression-aware composite scoring roadmap

- Body/description: None beyond subject.
- Files added: `kalshi_bot/contracts/reversal_classifier.py`, `kalshi_bot/forecast/adaptive_thresholds.py`, `kalshi_bot/forecast/progression_memory.py`, `scripts/__init__.py`, `scripts/check_phaseG1_adaptive_thresholds.py`, `scripts/check_phaseG2_progression_memory.py`, `scripts/check_phaseG3_composite_scoring.py`, `scripts/check_phaseG4_reversal_candidate_path.py`, `scripts/check_phaseG5_roadmap_replay.py`, `scripts/compare_roadmap_vs_live.py`, `scripts/inspect_reversal_candidates.py`, `scripts/replay_roadmap_decisions.py`, `scripts/validate_progression_memory.py`.
- Files modified: `.env.example`, `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/contracts/contract_scorer.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/observability/replay_engine.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/export_official_kalshi_outcomes.py`.
- Files deleted: None.
- Stats: 22 files changed, 3144 insertions, 50 deletions.
- High-level summary: Inference from diff. Added progression memory, adaptive thresholds, reversal classification, composite scoring, and roadmap replay/audit scripts.
- System areas affected: config/env, scanner, scoring, bias/direction, execution, runner/orchestrator, replay/audit scripts, tests.
- Likely behavior impact: Introduced major scoring/gating roadmap and audit tooling; reversal candidate path added but not necessarily live-enabled.
- Historical/current status: Current architecture, but details repaired/calibrated by later commits.

### 66. `ea2b78d` - 2026-05-15 - Fix roadmap live integration and EV telemetry

- Body/description: None beyond subject.
- Files added: None.
- Files modified: `.env.production.example`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/forecast/progression_memory.py`, `kalshi_bot/market/crypto_market_discovery.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phase6_contract_scanner.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_phaseG2_progression_memory.py`, `scripts/check_runner_lifecycle.py`.
- Files deleted: None.
- Stats: 10 files changed, 823 insertions, 20 deletions.
- High-level summary: Inference from diff. Fixed roadmap/live integration and EV telemetry propagation.
- System areas affected: config/env, scanner, scoring, execution, runner/orchestrator, telemetry/logging, tests.
- Likely behavior impact: Made roadmap scoring data and EV telemetry better aligned with live decisions.
- Historical/current status: Current lineage, refined by scoring/gating repair and final calibration.

### 67. `17e8d18` - 2026-05-16 - Repair roadmap scoring and gating calibration

- Body/description: None beyond subject.
- Files added: `scripts/check_scoring_gating_repair.py`.
- Files modified: `.env.production.example`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/contracts/contract_scorer.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_phaseG3_composite_scoring.py`, `scripts/check_phaseG4_reversal_candidate_path.py`, `scripts/check_runner_lifecycle.py`, `scripts/replay_roadmap_decisions.py`.
- Files deleted: None.
- Stats: 11 files changed, 1262 insertions, 27 deletions.
- High-level summary: Inference from diff. Repaired roadmap scoring and gating calibration and added a scoring/gating repair check.
- System areas affected: config/env, scanner, scoring, execution, runner/orchestrator, replay/audit scripts, tests.
- Likely behavior impact: Tightened or corrected live scoring/gating behavior after roadmap integration.
- Historical/current status: Current but superseded in part by final cold-start/high-ratio calibration.

### 68. `d1cc4a6` - 2026-05-18 - Add cold-start high-ratio danger calibration

- Body/description: None beyond subject.
- Files added: `scripts/check_final_scoring_calibration.py`.
- Files modified: `.env.example`, `.env.production.example`, `CURRENT_ENV_BEHAVIOR_REFERENCE.md`, `kalshi_bot/config/settings.py`, `kalshi_bot/contracts/contract_scanner.py`, `kalshi_bot/contracts/contract_scorer.py`, `kalshi_bot/execution/live_execution_coordinator.py`, `kalshi_bot/runner/orchestrator.py`, `scripts/check_phaseF2_live_execution_coordinator.py`, `scripts/check_phaseG3_composite_scoring.py`, `scripts/check_phaseG4_reversal_candidate_path.py`, `scripts/check_phaseG5_roadmap_replay.py`, `scripts/check_runner_lifecycle.py`, `scripts/check_scoring_gating_repair.py`, `scripts/replay_roadmap_decisions.py`.
- Files deleted: None.
- Stats: 16 files changed, 1411 insertions, 117 deletions.
- High-level summary: Inference from diff. Added final scoring calibration for cold-start high-ratio overextension danger, high-score danger caps, and replay/audit telemetry.
- System areas affected: config/env, scanner, scoring, execution, runner/orchestrator, replay/audit scripts, docs, tests, telemetry/logging.
- Likely behavior impact: Makes high-scoring but dangerous continuation setups more likely to be capped or blocked; adds normalized distance/burst telemetry for audit.
- Historical/current status: Latest current implementation at generation time.

## Potentially Superseded Areas

- Early planning docs from `ead4492` and `42483df` (`MASTER_SPEC.md`, `MASTER_STRATEGY.md`, `BUILD_PHASES.md`, `EXECUTION_RULES.md`, `SIGNAL_RULES.md`, `RISK_RULES.md`) appear partially superseded by later live execution, EV, reversal, and scoring/gating commits.
- Simulation-first execution assumptions from `b8db0b6`, `e02deae`, `65b0d32`, and related tests were superseded in part by `fbad615`, which enabled a direct live execution path without simulation dependency.
- Older stake minimum and contract cap changes from `2fde7be`, `792848f`, `5cd561a`, `c2af004`, and `b3ef9bc` appear superseded or refined by later live risk env controls in `606a4fd` and subsequent risk/execution changes.
- Older near-extreme, trend-distance, and composite scoring behavior from `d7c0152`, `08b9481`, and `17e8d18` was refined by `d1cc4a6` with cold-start/high-ratio overextension danger calibration and high-score danger caps.
- Older reversal assumptions from `2d9009b`, `2458a5e`, and `08b9481` appear refined by later defaults where reversal remains shadow-only and EV reversal remains disabled unless configured.
- EV cap semantics from `670ff05` were refined by `c6edd69`, `17e8d18`, and `d1cc4a6`, including side-aware pricing, scoring/gating repair, and danger telemetry.
- Older replay/audit scripts added in `08b9481` were modified by `ea2b78d`, `17e8d18`, and `d1cc4a6`; current replay conclusions should use the latest versions.
- Tracked generated `__pycache__/*.pyc` files added in `42483df` were deleted by `6384f04` and should be treated as historical noise.
- Deployment docs from `e15e41c` and `65b0d32` may be stale because many live env controls and guardrails were added afterward.

## Files Frequently Modified

- `kalshi_bot/config/settings.py` - 37 commits; central config/env parser and live control surface.
- `.env.example` - 30 commits; development/example env defaults, not secret source.
- `kalshi_bot/execution/live_execution_coordinator.py` - 28 commits; live decision coordination, guardrails, EV checks, pricing, and position handling.
- `scripts/check_runner_lifecycle.py` - 28 commits; runner integration and lifecycle regression coverage.
- `kalshi_bot/runner/orchestrator.py` - 28 commits; scan loop, live coordination, diagnostics, and lifecycle wiring.
- `.env.production.example` - 23 commits; production example defaults, not secret source.
- `scripts/check_phaseF2_live_execution_coordinator.py` - 21 commits; live coordinator regression coverage.
- `kalshi_bot/contracts/contract_scanner.py` - 19 commits; scanner gates, feasibility, exhaustion, quiet continuation, and danger diagnostics.
- `scripts/check_phase6_contract_scanner.py` - 13 commits; scanner regression coverage.
- `kalshi_bot/execution/execution_engine.py` - 13 commits; early simulation/live intent execution path.
- `kalshi_bot/risk/risk_manager.py` - 12 commits; stake, exposure, risk sizing, and order risk checks.
- `kalshi_bot/forecast/bias_engine.py` - 8 commits; bias, impulse, stabilization, and diagnostic logic.

## Validation Notes

- Commit count included: 68.
- Date range covered: 2026-04-21 through 2026-05-18.
- Latest commit included: `d1cc4a6` - Add cold-start high-ratio danger calibration.
- Full code diffs and patch contents are intentionally omitted.
- `.env` contents were not read or copied. Only example env filenames are listed.
- Binary/generated file contents were not embedded; historical `__pycache__` paths are listed only as changed/deleted files.
- Commits with unclear or vague purpose from message alone: `2fde7be`, `792848f`, `5cd561a`, `c2af004`, `b3ef9bc`, plus malformed quoted subjects `3a290e8`, `dedfa49`, `25d59bc`, and `6101a69`. Summaries for these are labeled as inference from changed files.
- Docs that appear stale compared with current implementation: `MASTER_SPEC.md`, `MASTER_STRATEGY.md`, `BUILD_PHASES.md`, `EXECUTION_RULES.md`, `SIGNAL_RULES.md`, `RISK_RULES.md`, `DEPLOYMENT.md`, and `VPS_RUNBOOK.md`.
- Safe for ChatGPT Project Sources: yes, based on metadata/path summaries only and no embedded secrets or full diffs.
