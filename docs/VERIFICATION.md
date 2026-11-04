# Verification report

Environment: Windows 11, Python 3.12.14 (managed by uv 0.12.19), run on 2026-11-04.
Resolved versions: streamlit 1.66.1, pandas 3.1.0, SQLAlchemy 2.1.7, Alembic 1.20.1,
Pydantic 2.14.2, Plotly 7.1.0, httpx 0.28.1, anthropic 2.4.0, openai 3.44.0.

## Commands and actual results
| # | Command | Result |
|---|---|---|
| 1 | `uv lock --check` | `Resolved 71 packages` (lockfile consistent) |
| 2 | `uv run ruff check .` | `All checks passed!` |
| 3 | `uv run ruff format --check .` | `89 files already formatted` |
| 4 | `uv run pytest -q --cov=cyberlead360` | **190 passed**, line coverage **89 %** (measured, 3671 statements) |
| 5 | `uvx bandit -q -r src -ll` | No medium/high findings (exit 0) |
| 6 | `uvx pip-audit -r <uv export>` | `No known vulnerabilities found` |
| 7 | `uv run python scripts/initialize_database.py` (fresh file) | `Database ready (SQLite). Active scoring rules: v1.` |
| 8 | `uv run python scripts/seed_demo.py` | `companies=84, contacts=149, facts=176, activities=401, opportunities=12, meetings=13, drafts=4` |
| 9 | Re-running the seed without `--reset` | Refused: `Database already contains 84 companies` (exit 1) |
| 10 | `uv run python scripts/verify_setup.py` | 6/6 checks OK |
| 11 | `docker compose config -q` (both variants) | Valid |
| 12 | Alembic offline SQL for PostgreSQL (`upgrade head --sql`) | 13 `CREATE TABLE` (12 + `alembic_version`), `TIMESTAMP WITH TIME ZONE` columns |
| 13 | Manual run: `streamlit run app.py`, browser | Home, Dashboard, Lead Qualification, AI Outreach (draft generated through the UI) and Analytics rendered with seeded data |

## Acceptance criteria
| Criterion | Status | Evidence |
|---|---|---|
| Start the application locally | ✅ | Manual run (13); page render tests |
| Initialize the database | ✅ | (7); migration test |
| Load fictional demonstration companies | ✅ | (8); seed tests |
| View a professional dashboard | ✅ | Manual run; `docs/screenshots/` |
| Import companies from CSV | ✅ | `test_csv_import_reports_every_row`, sample CSV preview |
| Add and edit companies | ✅ | integration tests |
| Detect duplicates | ✅ | domain/name/in-file tests, merge test |
| Manage contacts | ✅ | contact and privacy tests |
| Calculate explainable lead scores / view breakdowns | ✅ | 35 scoring tests; Lead Qualification page |
| Store public company facts with sources | ✅ | NOT NULL FK + tests |
| Generate an outreach draft without an API key | ✅ | template tests; manual UI generation |
| Optionally use a configured LLM API | ⚠️ Implemented, tested with stubs | Adapters tested with stubbed SDK clients; **no live API call was made** (no key available) |
| Record interactions; move opportunities; track replies and meetings | ✅ | pipeline tests |
| Accurate conversion metrics | ✅ | KPI unit tests with hand-computed expectations |
| Export data | ✅ | export tests |
| Run automated tests | ✅ | (4) |
| Use Docker Compose | ⚠️ Config validated, image **not built** | Docker daemon was not running during verification |
| Understand the architecture from documentation | ✅ | README + docs/ |

## Not verified / known gaps
* **Docker image build and container run**: not executed (Docker Desktop daemon unavailable).
  Run `docker compose up --build` to validate.
* **PostgreSQL runtime**: DDL compiled offline only. The test suite runs on SQLite.
* **Live LLM calls** (Anthropic / OpenAI-compatible): no API key was used. The request
  shapes follow the installed SDKs (`messages.parse`, `chat.completions.create`).
* **GitHub Actions**: the workflow was written, but it has not run, because no remote
  repository exists yet.
* UI interactions beyond the manual walkthrough are covered by service-level tests and
  headless page rendering (initial state), not by end-to-end browser automation.
