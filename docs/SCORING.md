# Lead scoring

## What the score is and is not
The lead score (0–100) is a **targeting-fit indicator**: how closely a company matches the
configured ideal customer profile, given *documented evidence*.

It is **not**:
* a probability of conversion. Nothing is calibrated against outcomes, and calling it a
  probability would be misleading;
* a **cybersecurity risk or vulnerability assessment**. A company's sector or technology
  says nothing about its actual security posture, so the score never implies weakness;
* an LLM judgement. The engine is plain, deterministic Python.

## Signature
```python
calculate_lead_score(company: CompanyProfile, evidence: list[EvidenceItem], rules: RuleSet,
                     *, now: datetime | None = None) -> LeadScoreResult
```
`LeadScoreResult` fields: `total_score`, `max_score`, `priority`, `breakdown` (one
`CriterionResult` per criterion with points, max, status, reason and evidence fact ids),
`rules_version`, `explanation`, `missing_information`, `data_completeness`,
`evidence_confidence` and `calculated_at`.

## Default rules (v1)
| Criterion | Max | Default rule |
|---|---|---|
| Industry fit | 30 | Manufacturing / healthcare / financial 30 · energy 28 · technology 25 · telecom 22 · logistics 20 · public 18 · retail 15 · professional services 12 · education 10 · other 5 |
| Company size | 20 | 1–49: 4 · 50–249: 12 · 250–999: 20 · 1000–4999: 16 · 5000+: 10 |
| Documented need | 35 | ≥1 approved *explicit, sourced need*: 35 · else ≥1 approved *security signal* or *regulatory context*: 20 · else 0 |
| Geography | 15 | Primary (FR, BE, CH, LU): 15 · secondary (DE, NL, ES, IT, GB, MA, TN): 8 · other: 0 |
| Priority | — | high ≥ 70 · medium ≥ 45 · low otherwise |

Validation rules: the maxima must total 100, size bands must not overlap, `none ≤ signal ≤
explicit ≤ max`, and a country cannot be both primary and secondary.

## Missing data vs negative evidence
| Status | Meaning | Example |
|---|---|---|
| `matched` | Full fit | Healthcare → 30/30 |
| `partial` | Some fit | Technology → 25/30; signal-only need |
| `no_match` | Known, does not fit | Country outside markets |
| `no_evidence` | Facts were reviewed, none documents a need | 2 approved business facts, no signal |
| `missing` | **Unknown**. Not scored, not negative, listed in *missing information* | Employee count empty |

**Data completeness** is the share of criteria that are not `missing`. **Evidence
confidence** is *high* when completeness is 100% and the need evidence comes from verified
sources, *medium* when completeness is at least 75%, and *low* otherwise. The UI shows both
separately from the score, so a 65 with 50% completeness reads very differently from a 65
with 100% completeness.

## What counts as evidence
Only facts that are **approved** by a human, whose source is **not rejected** (optionally:
must be *verified*). Pending facts are listed as "awaiting review" and contribute nothing.

## Versioning and recalculation
* Rules are stored as JSON rows in `scoring_rules`, with exactly one active row.
* *Settings → Scoring rules* shows an **impact preview** (before/after per company) computed
  without saving anything.
* Publishing creates version *n+1* and recalculates all active companies **in the same
  transaction**. Old results stay in history (`is_current = false`).
* Companies whose current score uses an older version are counted as "stale" on the
  qualification page, with a recalculate button.
* Scores are also recalculated automatically when a company is created or edited, or when
  a fact or source review changes the evidence.

## Fairness and data protection
Scoring uses company firmographics and company-level facts only. No attributes of
individuals (age, gender, nationality and so on) are ever inputs.

## Tests
`tests/unit/test_scoring_engine.py` covers perfect fit, missing vs negative evidence,
signal vs explicit, ignored pending or rejected evidence, verified-only mode, every size-band
boundary, priority thresholds, determinism under input reordering, the wording of the
explanation, and configuration validation.
