---

# **AGENTS.md**

## Purpose

Define strict behavioral rules for Codex when interacting with this repository.

---

## Core Behavior Rules

1. Always explain plan before making changes
2. Make minimal, precise edits
3. Never perform large rewrites unless explicitly requested
4. Do not create unnecessary files
5. Do not modify unrelated modules

---

## Safety Rules

* NEVER enable live trading by default
* NEVER remove or bypass guardrails
* NEVER hardcode credentials
* NEVER place real orders in development mode

---

## Scope Control

* Do not drift outside Kalshi crypto duration trading
* Do not introduce unrelated trading systems
* Do not add features not explicitly requested

---

## File Usage Rules

* Treat repository files as the only memory source
* Do NOT rely on chat history
* Only read files relevant to the current task

---

## Context Efficiency

* Do NOT scan entire repo unnecessarily
* Load minimal required context
* Avoid redundant reads

---

## Coding Discipline

* Use decimal/fixed-point safe math
* Avoid float-based calculations for trading
* Keep functions small and focused
* Maintain clear separation of modules

---

## Uncertainty Handling

* If unclear → STOP and ask
* Do not assume behavior not defined in spec

---

## Logging Rules

* Preserve all logs
* Do not delete historical data
* Ensure traceability of decisions

---