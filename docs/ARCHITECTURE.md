# Architecture

CyberLead 360 is a **modular monolith**: a single deployable Python application whose code
is split into layers with one-way dependencies.

```
Presentation (app.py, pages/, ui/)          ← Streamlit only
        ↓ calls
Application services (services/)            ← use cases, transactions, orchestration
        ↓ uses
Domain (domain/)                            ← pure rules: scoring, transitions, schemas, enums
        ↓ persisted by
Repositories (database/repositories/)       ← queries only, no business rules
        ↓
ORM models + session (database/)            ← SQLAlchemy 2.x, Alembic migrations
External adapters (integrations/)           ← LLM providers, safe web fetcher
```

## Why a modular monolith?
A demonstrator and early product needs one process, one database and simple deployment.
Microservices would add network failure modes, distributed transactions and operational
cost without a matching benefit. The layering still keeps services independent of Streamlit,
so they can later be exposed through an API without a rewrite.

**When to split it**
* **Separate API (FastAPI):** when a second client (CRM connector, mobile app, partner
  integration) needs the same use cases, or when the UI moves to a JS framework. The services
  are already UI-agnostic, so the API would be a thin layer over them.
* **Background worker (Celery/RQ + Redis):** when work exceeds an interactive request, for
  example rescoring 100k companies, batch LLM generation or scheduled retention jobs.
  Streamlit reruns the script per interaction, so long jobs should not run in it.

## Request lifecycle (Streamlit execution model)
Streamlit **re-executes the whole page script** from top to bottom on every interaction.
That has three consequences for the design:
1. Expensive resources are cached across reruns with `@st.cache_resource` (the `Database`
   engine and the LLM provider in `ui/bootstrap.py`).
2. Reads open a short session (`with db().session() as s:`) and copy the values the page
   needs into plain dicts or DataFrames before the session closes, so no lazy-loading
   happens on detached objects.
3. Writes go through `run_action(fn)`. It opens a transaction, calls one service method,
   commits, and maps expected errors (`CyberLeadError`, Pydantic `ValidationError`) to a
   readable `st.error`. Unexpected errors are logged and shown generically, and the
   transaction is rolled back.

## Components

The table below covers the main components. For each, it states the problem it solves, the
technology chosen and the alternatives, its inputs and outputs, how it handles errors and
security, and how it is tested.

| Component | Problem solved | Choice & alternatives | In → Out | Errors | Security risks | Tests |
|---|---|---|---|---|---|---|
| `config/settings.py` | One validated source of configuration | pydantic-settings (alt: os.environ, dynaconf) | env/.env → `Settings` | Invalid values fail at start | Secrets as `SecretStr`, never displayed | Used in every test |
| `config/logging.py` | Structured, safe logs | stdlib logging + JSON formatter (alt: structlog) | log calls → text/JSON lines | — | Redacts e-mails and API keys | indirectly |
| `database/models.py` | Persistent, constrained data | SQLAlchemy 2 typed ORM (alt: SQLModel, raw SQL) | Python objects ↔ rows | `IntegrityError` on constraint breach | Parameterized SQL; CHECK/UNIQUE/FK constraints | `test_database_enforces_constraints` |
| `database/base.py` `UTCDateTime` | Timezone-aware timestamps on SQLite and PG | TypeDecorator | aware datetimes ↔ UTC storage | Rejects naive datetimes | — | all integration tests |
| Alembic | Versioned schema changes | Alembic (alt: `create_all`, Flyway) | models → migration scripts | Migration failure stops startup | — | migration-vs-model drift test |
| Repositories | Keep queries out of services and pages | Plain classes per aggregate | filters → ORM objects/rows | None returned for missing | LIKE wildcards escaped | via services |
| `domain/scoring_rules.py` | Explainable, deterministic scoring | Pure functions + Pydantic config (alt: ML model → rejected: opaque) | profile + evidence + rules → `LeadScoreResult` | Invalid config raises `ValidationError` | No personal attributes used | 35 unit tests |
| `domain/pipeline_rules.py` | Valid stage changes | Transition tables as data | (current, target) → ok / `InvalidTransitionError` | Explicit message with allowed targets | — | unit tests |
| `services/company_service.py` | CRUD, dedup, merge | Domain + fuzzy name match (difflib) | `CompanyCreate` → `Company` | `DuplicateCompanyError`, `ValidationFailedError` | No silent overwrite; audited | integration |
| `services/import_service.py` | Safe bulk import | Pandas CSV + Pydantic per row | bytes → preview → result | Every invalid row reported | Size/row limits, encoding check | integration |
| `services/scoring_service.py` | Rule versions, persistence, recalculation | Wraps the pure engine | company id → `ScoringResult` | — | Recalculation is explicit | integration |
| `services/enrichment_service.py` | Sources, facts, review, retrieval | — | source/fact input → rows; URL → pending facts | `RetrievalBlockedError` | Domain-restricted retrieval; facts start pending | integration + mocked HTTP |
| `services/ai_service.py` | Grounded summaries/analysis | Provider interface + templates | approved facts → structured output | Falls back to template on any provider error | Injection delimiting, risk-claim filter, PII minimization | unit + fake provider |
| `services/outreach_service.py` | Draft lifecycle | — | `OutreachRequest` → `OutreachDraft` | `SuppressedContactError` | Never sends; approval required | integration |
| `services/pipeline_service.py` | Stages, deals, activities, meetings | — | commands → rows + stage-change activities | Transition / validation errors | Suppression checked on outbound touches | integration |
| `services/analytics_service.py` | Correct KPIs | Pandas on loaded frames (alt: SQL views) | DB → DataFrames → `KPIs` | Zero denominators → `None` | — | unit tests with hand-built frames |
| `services/compliance_service.py` | Privacy rights and suppression | SHA-256 e-mail hashes | contact id → anonymized/deleted/exported | — | Hash-only suppression list | integration |
| `services/export_service.py` | Trustworthy exports | Pandas → CSV | queries → CSV bytes | Bad names rejected | Formula-injection neutralization, path confinement | integration |
| `integrations/llm/*` | Vendor isolation | Official SDKs behind a Protocol | prompts + schema → validated model | Typed SDK errors → `AIProviderError` | Keys from env only; prompts not logged | fake provider |
| `integrations/public_sources/*` | Polite, safe retrieval | httpx + BeautifulSoup | URL → inert text | Every refusal is explicit | SSRF, size, robots, scripts | mocked transport |
| `ui/*` + `pages/*` | Presentation | Streamlit | user input → service calls | `run_action` error mapping | Untrusted text via `st.text`/escaped markdown; only static CSS uses `unsafe_allow_html` | `AppTest` renders every page |

## Dependency injection
Services receive their collaborators explicitly: a `Session`, an `actor` string and, for AI,
a `Settings` object and an optional `LLMProvider`. Tests therefore pass an in-memory
session and a `FakeProvider` without any patching of globals.

## Transaction boundaries
One user action is one transaction (`session_scope`), and services call `flush()` when they
need generated ids. Composite operations, such as a merge (re-pointing seven child tables,
releasing the unique domain, archiving the duplicate) or *publish rules + recalculate all*,
are atomic: either all of it is committed or nothing is.
