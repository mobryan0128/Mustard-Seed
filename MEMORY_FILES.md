---

# **MEMORY_FILES.md**

## MASTER_STRATEGY.md

* Purpose: core system strategy
* Updated when: major logic changes
* Contains: high-level system logic
* NOT: raw notes or logs

---

## SIGNAL_RULES.md

* Purpose: signal definitions
* Updated when: detection logic changes
* Contains: rules for trend/reversal/etc
* NOT: execution logic

---

## EXECUTION_RULES.md

* Purpose: order handling
* Updated when: execution changes
* Contains: entry/exit logic
* NOT: strategy reasoning

---

## RISK_RULES.md

* Purpose: protection system
* Updated when: risk parameters change
* Contains: limits, caps, stops
* NOT: trade signals

---

## RESEARCH_LOG.md

* Purpose: store findings
* Updated when: new insight discovered
* Contains: experiments, observations
* NOT: finalized rules

---

## TRADE_LOG.md

* Purpose: record trades
* Updated: every trade
* Contains: entry, exit, result
* NOT: analysis

---

## KNOWN_FAILURES.md

* Purpose: track system weaknesses
* Updated when: failures found
* Contains: patterns that caused losses
* NOT: general notes

---

## MARKET_NOTES.md

* Purpose: market-specific behavior
* Updated when: patterns observed
* Contains: liquidity quirks, timing edges
* NOT: trades or logs

---

## Final Note

This structure ensures:

* no memory loss
* no drift
* clean build process
* Codex clarity
* scalable architecture

---
