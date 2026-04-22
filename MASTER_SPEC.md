---

# **MASTER_SPEC.md**

## 1. Purpose

Define a complete, modular, Codex-readable blueprint for a Kalshi-based automated crypto duration trading system. This file is the authoritative description of system architecture, behavior, and constraints.

---

## 2. System Overview

A fully automated trading system operating on Kalshi crypto duration markets (primarily 15-minute).

The system:

* Continuously monitors live Kalshi markets
* Tracks external crypto price feeds (ground truth)
* Maintains a rolling ~30-minute directional bias
* Selects contracts based on risk/reward + alignment
* Executes trades only under strict conditions
* Manages positions dynamically (exit early or hold to settlement)

---

## 🖥 ENVIRONMENT & DEPLOYMENT ASSUMPTIONS

These assumptions are mandatory and must be followed throughout the build.

### Development Environment
- Primary development environment: local machine using Visual Studio Code
- Initial implementation, testing, and debugging must happen locally first
- Do not assume the system is being built directly on the deployment server
- Do not skip local validation just because the final runtime target is different

### Target Runtime Environment
- Final runtime target: Linux VPS
- The system must be written so it can run reliably on a Linux VPS later
- Avoid platform-specific assumptions unless explicitly documented
- Prefer portable paths, standard Python tooling, and environment-based configuration

### Python & Project Setup
- Use a Python virtual environment
- Keep dependency installation explicit and reproducible
- Do not hardcode machine-specific paths
- Do not rely on editor-only behavior or local GUI assumptions
- Assume headless runtime in deployment

### Secrets & Configuration
- All secrets must come from environment variables or `.env` files
- Never hardcode API keys, private keys, or credentials
- Never print secrets into logs
- Keep configuration separated from trading logic

### Build & Validation Expectations
- Every phase must be testable locally before moving to the next phase
- Every phase must define what success looks like
- Dry-run / simulation mode must be available before any live execution path exists
- If a phase cannot be validated locally, it is not complete

### Deployment Assumptions
- Deployment to VPS is a later phase, not an excuse to skip clean local architecture
- The codebase must be structured so deployment is straightforward once local testing passes
- The system must be able to run continuously in a non-interactive environment
- Logging, reconnect behavior, and failure handling must assume long-running execution

### Codex Behavior Under These Assumptions
- Codex must build for local development first, while keeping Linux VPS compatibility in mind
- Codex must not assume live deployment is already active
- Codex must not introduce OS-specific behavior without documenting it
- Codex must preserve clean separation between:
  - local development workflow
  - simulation workflow
  - future VPS deployment workflow
  
---

## 3. Core Philosophy

* **Do not predict blindly → confirm structure**
* **Do not trade often → trade selectively**
* **Execution quality = signal quality**
* **Skip > Force trades**
* **State-based decision system (not indicator-based)**

---

## 3.5 System Objective and Edge Definition

Primary objective:
Exploit short-duration opportunities in Kalshi crypto duration markets through strict state classification, selective contract scoring, disciplined execution, and strong risk controls.

The system operates as a hybrid model combining:

1. Directional Bias
   - The Forecast Layer establishes overall market context (up / down / neutral)
   - Directional bias determines whether a trade is allowed in principle

2. Timing / Mispricing Edge
   - The Opportunity Layer identifies contract-specific short-lived pricing inefficiencies or favorable execution windows
   - Timing / mispricing determines whether a specific contract is actionable

Directional bias provides context.
Timing / mispricing provides trade-specific opportunity.

If these are misaligned, unclear, or degraded, the system must skip the trade.

---

## 4. System Layers

### A. Forecast Layer (Bias Engine)

Maintains rolling directional outlook.

Outputs:

* direction: up / down / neutral
* confidence: 0–100
* structure: trend / reversal / chop / exhaustion
* risk flags: boolean indicators

Inputs:

* external price movement (last 30–60 sec + recent history)
* volatility behavior
* structure transitions

---

### B. Opportunity Layer (Contract Engine)

Scans all active 15-minute Kalshi contracts.

Scores each contract:

* alignment with forecast
* payout vs confidence (ROI efficiency)
* liquidity / volume
* spread quality
* time remaining
* execution feasibility

Outputs:

* ranked candidate list
* best actionable contract (if any)

---

### C. Execution Layer

Only triggers when BOTH:

* forecast confidence passes threshold
* contract score passes threshold

Handles:

* entry decision
* early exit logic
* hold-to-settlement decision
* trade lifecycle tracking

---

## 5. Trade Playbooks

### Intrawindow Trading

* Enter during contract window
* Exit when pricing advantage captured
* Focus: mispricing + momentum

### Hold-to-Settlement

* Enter late or mid-window
* Hold through expiration
* Focus: high certainty confirmation

---

## 6. Market State Classification

System must classify:

* Trend continuation
* Reversal
* Exhaustion
* Fakeout rejection
* Compression / expansion
* Chop (no-trade)
* Mispricing condition

---

## 7. Hard No-Trade Rules

System MUST skip trade if ANY:

* chop / unclear structure
* conflicting signals
* exhaustion detected
* high reversal probability
* low liquidity
* uncertain fills
* time sync failure
* account state unknown
* data mismatch between feeds

---

## 8. Required Modules

* kalshi_client
* auth_manager (RSA signing)
* websocket_client
* market_state_cache (orderbook + ticker)
* crypto_feed_client
* time_sync_checker
* bias_engine
* state_classifier
* contract_scanner
* contract_scorer
* execution_engine
* exit_manager
* risk_manager
* logger
* replay_engine

---

## 9. Kalshi-Specific Design Constraints

* Authenticated WebSocket required
* Local orderbook reconstruction required
* Rate limits must be respected
* Fixed-point math only (no float risk)
* Private key security mandatory
* Live vs historical separation
* Partial fills must be handled
* Snapshot + delta recovery required
* Market lifecycle tracking required

---

## 10. Execution Reality

System must assume:

* latency exists
* fills are not guaranteed
* prices move during execution
* orders may fail or partially fill

### Signal Freshness and Edge Decay
- Trade opportunities must be revalidated immediately before order submission
- The system must assume short-duration opportunities can decay quickly
- A detected setup must be canceled if conditions materially worsen before execution
- A signal is considered stale if price has already moved, spread has widened excessively, liquidity has degraded, or time remaining is no longer sufficient for the intended trade type

### Fill Feasibility as Hard Gate
- Execution feasibility is a hard requirement, not a soft preference
- A trade must not be executed if expected fill quality is insufficient
- The system must reject trades where poor depth, wide spread, likely slippage, or partial-fill risk would materially damage the expected edge
- Partial fills must trigger explicit handling and possible reassessment rather than blind continuation
---

## 11. System State

The system is NOT stateless.

Persistent state must include:

* current bias
* open trades
* recent decisions
* risk metrics
* known failures

---

## 12. Guardrails (Must Exist Before Strategy)

* simulation mode (default)
* live mode toggle
* max position size
* daily loss cap
* kill switch
* API failure handling
* time sync validation

### Position Sizing Requirements
- Trade size must be determined by explicit sizing rules rather than ad hoc judgment
- Sizing must remain conservative by default
- A minimum trade size may be used for validation and testing
- A maximum position cap must always be respected regardless of account balance growth
- Live validation phases must keep position size artificially small even if the account balance increases
- Position sizing must not scale aggressively unless explicitly defined in repository files
- Drawdown or instability may require size reduction or frozen sizing

---

## 13. Design Rules

* modular architecture only
* no giant files
* no mixed responsibilities
* no hidden state
* no silent failures

---