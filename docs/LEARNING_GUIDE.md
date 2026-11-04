# Learning guide: the concepts behind CyberLead 360

Each section explains a concept briefly, with a concrete example from this repository.

## Python modules and packages
A **module** is a `.py` file and a **package** is a folder of modules with an `__init__.py`.
The code uses the *src layout*: `src/cyberlead360/…` is installed into the virtual
environment (`uv sync`), so `from cyberlead360.services.scoring_service import
ScoringService` works from pages, scripts and tests. It also means tests import the
installed package rather than files that happen to sit in the current folder.

## Virtual environments
See DEPLOYMENT.md §3. Each project gets its own interpreter and packages, pinned by `uv.lock`.

## Streamlit execution model
A Streamlit page is a script that **reruns from top to bottom** after every widget
interaction. Widgets return their current value:
```python
industries = st.multiselect("Industry", INDUSTRIES)  # returns the current selection
rows = CompanyService(s, actor()).search(CompanyFilters(industries=industries))
```
State that must survive a rerun goes into `st.session_state` (for example the selected
company id), and expensive objects into `@st.cache_resource` (the database engine).
`st.form` batches inputs so that the rerun only happens on submit.

## Pandas DataFrames
A DataFrame is an in-memory table with named, typed columns. The analytics code loads
activities into a DataFrame and computes *distinct companies* with set operations:
```python
contacted = set(a.loc[a["activity_type"].isin(OUTBOUND_TYPES), "company_id"])
replied = set(a.loc[a["activity_type"] == "reply_received", "company_id"]) & contacted
response_rate = len(replied) / len(contacted) if contacted else None
```

## SQL databases, primary and foreign keys
A relational database stores rows in tables. A **primary key** (`companies.id`) uniquely
identifies a row. A **foreign key** (`contacts.company_id → companies.id`) links rows and is
enforced by the database: a contact cannot point to a company that does not exist. Other
constraints (`UNIQUE normalized_domain`, `CHECK total_score BETWEEN 0 AND 100`) protect
integrity even if application code has a bug.

## SQLAlchemy ORM and CRUD
The ORM maps classes to tables:
```python
company = Company(company_name="Acme", normalized_name="acme")  # Create
session.add(company)
session.flush()  # INSERT, id assigned
session.get(Company, 1)  # Read
company.city = "Lyon"  # Update (on commit)
session.delete(company)  # Delete
```
Queries are built with `select(...)` and always sent with **bound parameters**, so user
input is never concatenated into SQL. That is what prevents SQL injection.

## Database migrations
Alembic stores each schema change as a versioned script (`alembic/versions/…`).
`alembic upgrade head` applies the missing ones in order, so every environment can be
brought to the same schema and changes are reviewable in Git. Use `--autogenerate` to
compare the models with the database, and always review the generated script before
committing it.

## Business logic separation
Rules live in `domain/` and `services/`, never in pages. For example, Streamlit only *calls*
`PipelineService.change_stage`, and the allowed transitions live in `pipeline_rules.py`. You
can then unit-test the rules without a browser, and reuse them from an API later.

## Lead scoring
Rule-based, explainable points per criterion (see SCORING.md). Deliberately not a machine
learning model: there is no outcome data to train on, and sales teams need to see *why* an
account is prioritized.

## REST APIs and HTTP
HTTP is a request/response protocol: a method (`GET`, `POST`), a URL, headers and a body,
answered with a status code (`200`, `302` redirect, `404`, `429` rate limit, `500`) plus
headers and a body. A **REST API** exposes resources at URLs (`POST /v1/messages`). The safe
fetcher shows the details that matter for security: timeouts, redirects (`Location`
header), content types and size limits.

## LLM APIs, prompt engineering and structured outputs
An LLM API takes a system prompt (rules), user content (task and data) and limits, and
returns generated text with token usage. Prompt engineering here means three things: clear
rules, data in an explicit delimited block, and an exact output contract. **Structured
output** means the response must match a schema (a Pydantic model) and is validated. If it
doesn't match, the code falls back to the template instead of showing broken output (see
AI_DESIGN.md).

## Data provenance
Every fact points to a source (type, URL, publication and collection dates, verification
status, collector). Scores list the fact ids they used, and drafts list the fact ids they
cite. When someone asks *"why did we contact them?"*, the record answers it.

## Docker networking
Containers in one Compose project share a private network and reach each other by service
name (`db:5432`). Publishing a port (`127.0.0.1:8501:8501`) maps a container port to the
host. Binding to `127.0.0.1` keeps it private to your machine.

## Unit vs integration testing
* **Unit tests** check one function in isolation, fast and without I/O (the scoring engine,
  KPI formulas, guardrails, the fetcher with a mocked transport).
* **Integration tests** run several layers together against a real (in-memory SQLite)
  database: services + repositories + constraints, Alembic migrations, and Streamlit pages
  rendered headlessly with `streamlit.testing.v1.AppTest`.
* External systems are **mocked**: `httpx.MockTransport` for HTTP and `FakeProvider` for LLMs.

## GitHub Actions and CI/CD
**Continuous integration** runs lint, tests and security checks automatically on every
push or pull request, so broken code is caught before merge. **Continuous delivery /
deployment** would then build and ship an image. It is intentionally not configured here
(see DEPLOYMENT.md §6).
