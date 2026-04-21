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

## 3. Core Philosophy

* **Do not predict blindly → confirm structure**
* **Do not trade often → trade selectively**
* **Execution quality = signal quality**
* **Skip > Force trades**
* **State-based decision system (not indicator-based)**

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

---

## 13. Design Rules

* modular architecture only
* no giant files
* no mixed responsibilities
* no hidden state
* no silent failures

---