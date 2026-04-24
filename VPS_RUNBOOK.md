# VPS Runbook

## Purpose
Operator checklist for safe VPS setup, validation, supervision, and shutdown.

## 1. Initial Setup
- create deploy user
- clone repo into `/opt/kalshi-bot`
- create `.venv`
- install `requirements.txt`
- create `logs/` and `replay/`
- create `.env` from `.env.production.example`
- store Kalshi private key outside world-readable paths

## 2. Preflight Checks
- `python --version`
- `pip --version`
- `test -d logs && test -w logs`
- `test -d replay && test -w replay`
- `git status --short --untracked-files=all`

Do not continue if:
- dependencies are missing
- `.env` is incomplete
- private key path is wrong
- runner market discovery settings are invalid when overridden:
  - `KALSHI_AUTO_MARKET_DISCOVERY_ENABLED=true`
  - `KALSHI_MARKET_DISCOVERY_REFRESH_CYCLES` is a bounded positive integer
- working directories are not writable

## 3. Validation Checklist
Run in order:

```bash
source .venv/bin/activate
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

If any step fails:
- stop
- inspect the exact script output
- inspect `logs/` and `replay/`
- do not advance to live validation

## 4. Manual Supervision With tmux
Create a session:

```bash
tmux new -s kalshi-bot
cd /opt/kalshi-bot
source .venv/bin/activate
```

Run readiness checks manually inside tmux. Keep one pane tailing logs if desired:

```bash
python scripts/run_kalshi_bot.py --env-file .env --max-cycles 3
```

Confirm bounded runner output shows active discovered market tickers and that
`last_discovery_cycle` stays stable between refresh intervals.

For continuous supervised simulation:

```bash
python scripts/run_kalshi_bot.py --env-file .env
```

Optional second pane:

```bash
tail -f logs/runtime.jsonl
```

Detach:

```bash
Ctrl-b d
```

Reattach:

```bash
tmux attach -t kalshi-bot
```

## 5. Live Safety Procedure
Default safe state:
- `LIVE_VALIDATION_ENABLED=false`
- `LIVE_TRADING_ENABLED=false`
- `LIVE_KILL_SWITCH_ACTIVE=false`

Intentional tiny live validation window only:
1. set explicit live validation target in `.env`
2. set `LIVE_VALIDATION_ENABLED=true`
3. set `LIVE_TRADING_ENABLED=true`
4. confirm `LIVE_KILL_SWITCH_ACTIVE=false`
5. run:

```bash
python scripts/check_phase10_live_guardrails.py --live --env-file .env
```

6. immediately return to blocked state after the test:
- `LIVE_TRADING_ENABLED=false`
- optionally `LIVE_KILL_SWITCH_ACTIVE=true` during post-test review

## 6. Emergency Stop
Immediate operator action:
1. set `LIVE_KILL_SWITCH_ACTIVE=true`
2. set `LIVE_TRADING_ENABLED=false`
3. stop any active tmux/manual validation process
4. verify no new live submission attempts are possible

## 7. Log And Replay Verification
After any validation run:
- confirm `logs/runtime.jsonl` exists and is growing when expected
- confirm `replay/replay.jsonl` exists and is growing when expected
- inspect the latest events for:
  - auth checks
  - websocket activity
  - balance fetches
  - live safeguard blocks, if tested

## 8. Systemd Note
`systemd/kalshi-bot.service.example` points at the simulation-first runner.

Do **not** interpret it as approval for autonomous live trading. The runner does not auto-submit live orders and the explicit live smoke path remains separate.

## 9. Shutdown Procedure
- stop any tmux/manual process
- verify no validation script is still running
- set `LIVE_TRADING_ENABLED=false`
- set `LIVE_KILL_SWITCH_ACTIVE=true` if you want an explicit hard stop state
- archive relevant log and replay excerpts if investigating issues
