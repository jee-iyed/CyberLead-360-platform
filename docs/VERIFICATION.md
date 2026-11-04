# Verification report

Environment: Windows 11, Python 3.12.14 (managed by uv 0.12.19), run on 2026-11-04.
Container runs: Docker Engine 29.6.2, `python:3.12-slim` (Python 3.12.16), `postgres:17-alpine`.
Resolved versions: streamlit 1.66.1, pandas 3.1.0, SQLAlchemy 2.1.7, Alembic 1.20.1,
Pydantic 2.14.2, Plotly 7.1.0, httpx 0.28.1, anthropic 2.4.0, openai 3.44.0.

## Commands and actual results
| # | Command | Result |
|---|---|---|
| 1 | `uv lock --check` | `Resolved 71 packages` (lockfile consistent) |
| 2 | `uv run ruff check .` | `All checks passed!` |
| 3 | `uv run ruff format --check .` | `89 files already formatted` |
| 4 | `uv run pytest -q --cov=cyberlead360` | **776 passed**, line coverage **89 %** (measured, 3683 statements) |
| 5 | `uvx bandit -q -r src -ll` | No medium/high findings (exit 0) |
| 6 | `uvx pip-audit -r <uv export>` | `No known vulnerabilities found` |
| 7 | `uv run python scripts/initialize_database.py` (fresh file) | `Database ready (SQLite). Active scoring rules: v1.` |
| 8 | `uv run python scripts/seed_demo.py` | `companies=84, contacts=149, facts=176, activities=401, opportunities=12, meetings=13, drafts=4` |
| 9 | Re-running the seed without `--reset` | Refused: `Database already contains 84 companies` (exit 1) |
| 10 | `uv run python scripts/verify_setup.py` | 6/6 checks OK |
| 11 | `docker compose config -q` (both variants) | Valid |
| 12 | Alembic offline SQL for PostgreSQL (`upgrade head --sql`) | 13 `CREATE TABLE` (12 + `alembic_version`), `TIMESTAMP WITH TIME ZONE` columns |
| 13 | Manual run: `streamlit run app.py`, browser | Home, Dashboard, Lead Qualification, AI Outreach (draft generated through the UI) and Analytics rendered with seeded data |
| 14 | `docker compose build` (Docker Engine 29.6.2) | Image `cyberlead360:latest` built (about 4 min cold, 1.9 GB unpacked) |
| 15 | `docker compose up -d` | Container `healthy`; `/_stcore/health` returns `ok`; runs as `uid=10001(appuser)`; published only on `127.0.0.1:8501` |
| 16 | In container: `seed_demo.py`, then `verify_setup.py` | Seed counts identical to (8); 6/6 checks OK; Dashboard rendered in the browser |
| 17 | `docker compose -f docker-compose.yml -f docker-compose.postgres.yml up -d` (random `POSTGRES_PASSWORD`) | `db` healthy, then `app` healthy |
| 18 | On PostgreSQL 17: `initialize_database.py`, `seed_demo.py`, `verify_setup.py` | `Database ready (postgresql+psycopg)`; same seed counts; 6/6 OK |
| 19 | `psql` checks | `alembic_version` = `44bf92bc38e9`; 13 tables; `companies` = 84; `created_at` is `timestamp with time zone` |
| 20 | Browser walkthrough of all 11 pages on PostgreSQL | All pages rendered without exceptions; template draft #5 created through the UI (write path) |
| 21 | GitHub Actions run [41795993231](https://github.com/jee-iyed/CyberLead-360-platform/actions/runs/41795993231) on `371ac11` | `quality` (Ruff lint + format, unit tests, integration tests) and `security` (Bandit, pip-audit): **success** |
| 22 | Live LLM via the OpenAI-compatible connector: Google Gemini `gemini-3.5-flash`, free tier | Summary, opportunity analysis, EN cold e-mail and FR LinkedIn note all returned schema-valid output, cited only approved fact ids, and passed the risk-claim filter. `gemini-2.5-flash` returned 404 (retired); 503 and 429 responses fell back to templates as designed |
| 23 | Draft generated in the browser with "Use LLM" on | Draft stored with `generation_mode=llm`, model `gemini-3.5-flash`, 812 input / 261 output tokens |

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
| Optionally use a configured LLM API | ✅ (OpenAI-compatible) / ⚠️ (Anthropic) | (22)–(23) live with Gemini; the Anthropic adapter is tested with stubbed SDK clients only |
| Record interactions; move opportunities; track replies and meetings | ✅ | pipeline tests |
| Accurate conversion metrics | ✅ | KPI unit tests with hand-computed expectations |
| Export data | ✅ | export tests |
| Run automated tests | ✅ | (4) |
| Use Docker Compose | ✅ | (14)–(20): SQLite and PostgreSQL variants built, started and exercised |
| Understand the architecture from documentation | ✅ | README + docs/ |

## Not verified / known gaps
* **PostgreSQL in the automated suite**: PostgreSQL was verified manually through Docker
  (18)–(20); the pytest suite itself still runs on SQLite.
* **Live Anthropic calls**: no Anthropic key was used. The request shape follows the
  installed SDK (`messages.parse`). The OpenAI-compatible path was verified live with Gemini.
* **Bugs found by the live run and fixed**: summaries and analyses opened with
  "Hello {{first_name}}" (greeting rule now outreach-only), and French templates mixed in
  English industry/service labels (French labels added). Both have regression tests.
* UI interactions beyond the manual walkthrough are covered by service-level tests and
  headless page rendering (initial state), not by end-to-end browser automation.
