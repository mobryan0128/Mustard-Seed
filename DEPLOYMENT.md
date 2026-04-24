# Deployment Readiness

## Summary
This repository now has a single supervised runner entrypoint for continuous **simulation-first** coordination: `python scripts/run_kalshi_bot.py`. Treat this document as a deployment-readiness guide for Linux VPS setup, validation, and supervised operation. It is **not** approval to enable unattended autonomous live trading.

Live trading must remain explicitly blocked by default.

## Current Capabilities
- Kalshi auth and REST connectivity
- Kalshi WebSocket market data and local market state
- External crypto feed ingestion
- Structured logs and replay output
- Bias, scanner, simulation, exit, and live smoke-test surfaces
- Runner-managed active BTC/ETH crypto market discovery and rollover
- Phase 10 live guardrails:
  - `LIVE_TRADING_ENABLED`
  - `LIVE_KILL_SWITCH_ACTIVE`

## Current Gaps
- The continuous runner is simulation-only and does not auto-submit live orders
- The explicit live smoke path remains operator-invoked and separate
- Systemd should still be treated as supervised infrastructure, not as proof of autonomous live deployment

## Linux VPS Prerequisites
- Ubuntu/Debian-class Linux VPS
- non-root deploy user
- Python 3.11+ recommended
- `python3-venv`
- `tmux`
- `systemd`
- outbound network access for Kalshi and crypto feed endpoints

## Filesystem Layout
Recommended deployment target:

```text
/opt/kalshi-bot/
  repo checkout
  .venv/
  logs/
  replay/
```

Recommended permissions:
- repo readable by deploy user
- `logs/` and `replay/` writable by deploy user
- private key file readable only by deploy user

## Install Steps
From the VPS:

```bash
sudo mkdir -p /opt/kalshi-bot
sudo chown -R "$USER":"$USER" /opt/kalshi-bot
cd /opt/kalshi-bot
git clone <repo-url> .
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p logs replay
```

## Environment Setup
Use `.env.production.example` as the starting point. Create `.env` manually on the VPS and fill in real values there only.

Required checks:
- `KALSHI_ENV=prod`
- valid `KALSHI_API_KEY_ID`
- valid `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY_PEM`
- explicit market ticker values for standalone validation scripts, if used
- `KALSHI_AUTO_MARKET_DISCOVERY_ENABLED=true` for runner-managed active BTC/ETH crypto markets
- optional `KALSHI_CRYPTO_MARKET_SERIES_JSON` override for BTC/ETH 15m/30m series candidates
- `KALSHI_MARKET_DISCOVERY_REFRESH_CYCLES` set high enough to avoid excessive REST discovery calls
- explicit live smoke target only when intentionally testing

Safety defaults that must stay blocked unless intentionally testing:
- `LIVE_VALIDATION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `LIVE_KILL_SWITCH_ACTIVE=false`

Emergency stop:
- set `LIVE_KILL_SWITCH_ACTIVE=true`
- keep `LIVE_TRADING_ENABLED=false` when not actively validating

## Validation Sequence
Run these from the repo root inside the virtualenv.

Static hygiene:

```bash
git status --short --untracked-files=all
python -m pip --version
python -c "import httpx, cryptography, websockets"
```

Connectivity and phase checks:

```bash
python scripts/check_kalshi_auth.py
python scripts/check_kalshi_websocket.py --market-ticker <explicit_kalshi_ticker>
python scripts/check_crypto_feed.py
python scripts/check_phase4_observability.py
python scripts/check_phase5_bias_engine.py
python scripts/check_phase6_contract_scanner.py
python scripts/check_phase7_simulation.py
python scripts/check_phase8_exit_logic.py
python scripts/check_phase9_live_execution.py
python scripts/check_phase10_live_guardrails.py
python scripts/check_runner_lifecycle.py
```

Expected outcome:
- all scripts pass
- `logs/` receives JSONL output where applicable
- `replay/` receives JSONL output where applicable

## Live Safety Checklist
Before any live smoke run:
- confirm `KALSHI_ENV=prod`
- confirm `LIVE_VALIDATION_ENV=prod`
- confirm `LIVE_VALIDATION_COUNT=1`
- confirm `LIVE_VALIDATION_TIME_IN_FORCE=immediate_or_cancel`
- confirm `LIVE_TRADING_ENABLED=true` only for the test window
- confirm `LIVE_KILL_SWITCH_ACTIVE=false` only for the test window

Fail-closed checks:
- with `LIVE_KILL_SWITCH_ACTIVE=true`, `check_phase10_live_guardrails.py --live` must block submission
- with `LIVE_TRADING_ENABLED=false`, live submission must block
- with missing explicit live flags, live submission must block

## Supervised Dry Run
Current repo state supports a supervised continuous **simulation** runner.

Use `tmux`:

```bash
tmux new -s kalshi-bot
cd /opt/kalshi-bot
source .venv/bin/activate
python scripts/run_kalshi_bot.py --env-file .env --max-cycles 3
```

For continuous supervised simulation:

```bash
python scripts/run_kalshi_bot.py --env-file .env
```

The runner discovers active configured crypto markets, updates its WebSocket subscriptions and scanner mapping, and drops stale market state on rollover. Do not treat this as autonomous live trading. The runner remains simulation-only and does not submit live orders automatically.

## Git Status Expectation
For this documentation task, a clean status means:
- only the new deployment-readiness files are added
- existing tracked `__pycache__` noise may still appear because it predates this task and is out of scope here
