---

# **BUILD_PHASES.md**

## Phase 0 — Scaffold

**Objective:**
Create repo structure and memory system.

**Create:**

* folder structure
* memory files
* AGENTS.md

**Test:**

* repo loads cleanly

**Success:**

* structure exists, no logic yet

**Do NOT:**

* add trading logic

---

## Phase 1 — Auth & Environment

**Objective:**
Implement Kalshi authentication + env config.

**Create:**

* auth_manager
* env handling

**Test:**

* successful authenticated request

**Success:**

* valid API connection

**Do NOT:**

* trade or fetch markets yet

---

## Phase 2 — WebSocket + Market State

**Objective:**
Build real-time market data layer.

**Create:**

* websocket client
* local cache

**Test:**

* real-time updates received

**Success:**

* stable local orderbook/ticker

**Do NOT:**

* scoring or trading logic

---

## Phase 3 — External Crypto Feed

**Objective:**
Add underlying price data.

**Create:**

* crypto feed module

**Test:**

* real-time price updates

**Success:**

* feed sync working

---

## Phase 4 — Logging + Time Sync

**Objective:**
Add observability + timing accuracy.

**Create:**

* logger
* replay storage
* time sync checker

**Test:**

* logs written correctly

**Success:**

* full traceability

---

## Phase 5 — Bias Engine

**Objective:**
Implement 30-minute directional model.

**Create:**

* bias_engine
* state outputs

**Test:**

* consistent outputs

**Success:**

* stable classification

---

## Phase 6 — Contract Scanner

**Objective:**
Scan and score contracts.

**Create:**

* scanner
* scoring engine

**Test:**

* ranking output

---

## Phase 7 — Execution Engine (SIMULATION)

**Objective:**
Simulated trading logic.

**Create:**

* execution logic
* position tracking

**Test:**

* simulated trades behave correctly

---

## Phase 8 — Exit Logic

**Objective:**
Implement early exit + hold logic.

---

## Phase 9 — Live Mode Prep

**Objective:**
Enable real trading safely.

**Add:**

* kill switch
* safeguards

**Test:**

* small live trades only

---