# Interview guide

## 60-second pitch
> "CyberLead 360 is a sales-intelligence platform I built for cybersecurity service
> providers. It imports and deduplicates target companies, records public facts *with their
> sources*, and scores accounts with a transparent rule engine. Every point is explained,
> and missing data is never treated as a negative. It drafts personalized outreach with an
> LLM or with deterministic templates, grounded only in human-approved facts, and a person
> must approve every message, since the app never sends anything. It also covers a CRM
> pipeline, analytics with documented denominators, and GDPR-oriented controls: a
> suppression list, objections, anonymization, retention and an audit log. Technically it's
> a layered Python modular monolith (Streamlit, SQLAlchemy, Alembic, Pydantic, Pandas,
> Plotly) with 190 automated tests, Docker and CI."

## Lead scoring vs cybersecurity risk assessment (key distinction)
| | Lead score (this app) | Security risk assessment |
|---|---|---|
| Question | Is this company a good *commercial* target for us? | How exposed is this organization to threats? |
| Inputs | Sector, size, geography, *publicly documented* needs | Asset inventory, vulnerabilities, controls, threat intel. Requires authorization |
| Method | Configurable points, deterministic | Testing, audits, frameworks (ISO 27005, NIST) |
| Output | Prioritization for sales | Risk register and remediation |
| Ethics | Public information only, no testing of prospects | Only with the client's explicit authorization |

Saying a prospect is "vulnerable" because it is a hospital is both inaccurate and damaging.
The app therefore blocks such claims in AI output and explains that the score is not a risk rating.

## Design decisions and trade-offs
| Decision | Why | Trade-off / alternative |
|---|---|---|
| Modular monolith | One deployable, simple ops, easy demo | Scaling is vertical. A FastAPI layer and workers can be added later because services are UI-agnostic |
| Rule-based scoring, no ML | No labelled outcomes; explainability; configurable by sales ops | Can't learn patterns. Could later calibrate weights from won/lost data |
| `missing` ≠ `no_evidence` | Avoids penalizing under-researched accounts | Needs an extra status and a completeness metric in the UI |
| Facts need human approval | Quality and injection defence; nothing unreviewed affects scores or prompts | Slower ingestion. Retrieval creates pending facts to reduce the manual work |
| LLM optional + template fallback | Demo without keys; resilient to provider outages | Templates are less fluent |
| `{{first_name}}` placeholder | Personal data never leaves the system | The model can't adapt to the person's name, a negligible loss |
| Hash-only suppression list | Honour objections without keeping the e-mail | Can't display which e-mail was suppressed |
| Archive instead of delete; merge archives the duplicate | No silent data loss, auditability | More rows; hard delete exists for erasure |
| Distinct-company KPIs | 3 e-mails to one company ≠ 3 contacts | Message-level metrics need separate views |
| SQLite default, PostgreSQL supported | Zero-setup demo | Automated tests run on SQLite; PostgreSQL verified manually via Docker Compose |
| Streamlit | Very fast to build data apps | Rerun model; limited fine-grained UI control; no built-in auth |

## Likely questions and answers
**How do you prevent prompt injection?** Facts must be human-approved before they reach a
prompt. Source text is sanitized so it cannot close the `<untrusted_company_data>`
delimiter, and the system rules say the block is data to be ignored as instructions. Output
must match a schema, citations are restricted to known fact ids, a risk-claim filter
rejects outputs that assert weaknesses, and a human approves every draft. None of these
layers is perfect alone, which is why there are several.

**How is SSRF prevented in retrieval?** Only http(s) on ports 80 and 443, every resolved IP
must be global (blocking RFC 1918, loopback, link-local including 169.254.169.254, CGNAT,
IPv4-mapped IPv6), redirects are followed manually and re-validated, and retrieval is
limited to the company's own domain by default and disabled by default. The residual risk is
DNS rebinding, which I'd close with network egress controls.

**How do you avoid double counting?** KPIs are computed on sets of company ids. A reply only
counts if the company was contacted, and cancelled meetings are excluded. Zero denominators
return "n/a", never 0%.

**What happens when scoring rules change?** A new version is stored, an impact preview is
shown first, and publishing recalculates all active scores in one transaction. History
keeps the old results with their version numbers.

**What would you do next for production?** SSO and role-based authorization in the service
layer, PostgreSQL with backups, a secret manager, HTTPS behind a proxy, egress filtering, a
background worker for bulk jobs, scheduled retention, and observability.

**What did testing reveal?** Several real bugs: Pydantic doesn't validate defaults (the
country lists weren't normalized, so the settings page would have reported phantom
changes); CSV delimiter sniffing split single-column files on spaces; a pandas 3 `melt`
name clash; and Streamlit hot-reload keeping stale modules. Each was fixed and is now
covered by a test where applicable.

## Suggested LinkedIn project description
> **CyberLead 360: AI-assisted B2B sales intelligence for cybersecurity providers.**
> Built a full-stack Python application (Streamlit, SQLAlchemy 2, Alembic, Pydantic, Pandas,
> Plotly) that qualifies prospects with an explainable, versioned scoring engine, tracks
> sourced company intelligence, and generates evidence-grounded outreach drafts with
> optional LLMs (Claude / OpenAI-compatible), guarded against prompt injection and
> unsupported security claims, with mandatory human approval. Includes a CRM pipeline,
> conversion analytics with explicit denominators, GDPR-oriented controls (suppression,
> anonymization, retention, audit), an SSRF-hardened web fetcher, 190 automated tests,
> Docker and GitHub Actions CI.

## CV bullet points
* Designed and built **CyberLead 360**, a layered Python modular monolith for cybersecurity B2B prospecting (Streamlit, SQLAlchemy 2, Alembic, Pydantic 2, Pandas, Plotly).
* Implemented a **deterministic, explainable lead-scoring engine** with versioned configuration, controlled recalculation and a clear separation of missing vs negative evidence.
* Integrated **LLMs behind a provider interface** (Anthropic structured outputs, OpenAI-compatible), with grounding, prompt-injection defences, output guardrails, PII minimization and a template fallback.
* Engineered **privacy and security controls**: hashed suppression list, anonymization, retention, audit log, CSV formula-injection protection, and an SSRF-safe HTTP fetcher.
* Delivered **190 automated tests** (unit, integration, migrations, headless UI) with Ruff, Bandit, pip-audit, Docker and GitHub Actions CI.
