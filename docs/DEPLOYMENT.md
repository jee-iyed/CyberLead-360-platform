# Deployment

## 1. Local development on Windows (PowerShell)
```powershell
# Install uv once (official installer), then reopen the terminal
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

cd D:\cyberlead-360
uv python install 3.12            # uv manages the interpreter
uv sync --all-extras              # .venv + locked dependencies (runtime + postgres + dev)
Copy-Item .env.example .env       # then edit .env if needed
uv run python scripts/initialize_database.py
uv run python scripts/seed_demo.py            # add --reset to recreate the demo data
uv run python scripts/verify_setup.py
uv run streamlit run app.py                   # http://localhost:8501

# Quality checks
uv run pytest -q
uv run ruff check . ; uv run ruff format --check .
```
**Without uv (pip):**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[postgres]" pytest pytest-cov ruff
python scripts\initialize_database.py
streamlit run app.py
```
A pip install resolves the newest compatible versions instead of the locked ones. Use
`uv export --format requirements-txt > requirements.txt` to pin them.

## 2. Local development on Linux / macOS
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --all-extras
cp .env.example .env
make init seed run        # or the uv run commands above
```

## 3. What a virtual environment is
`.venv/` is an isolated Python installation for this project. Packages installed there do
not affect other projects or the system Python. `uv sync` creates it and installs exactly
the versions in `uv.lock`, so every machine gets the same dependency tree. `uv run <cmd>`
runs a command inside it without activating it.

## 4. Docker
```powershell
docker compose up --build -d           # SQLite stored in the named volume cyberlead-data
docker compose logs -f app
docker compose exec app python scripts/seed_demo.py      # optional demo data
docker compose down                    # the volume (data) is kept; add -v to delete it
```
**PostgreSQL:**
```powershell
$env:POSTGRES_PASSWORD = "a-long-random-password"
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```
Docker networking: Compose creates a private network where the `app` container reaches
PostgreSQL at hostname `db:5432`. The database port is **not** published to the host. The
app port is published on `127.0.0.1:8501` only, so it is not reachable from other machines.

**Health check:** the image probes `http://127.0.0.1:8501/_stcore/health` every 30 s.
`docker ps` shows `healthy` once Streamlit is serving.

**Optional hardening:** a read-only root filesystem (`read_only: true` plus a `tmpfs` for
`/tmp`) can be added to `docker-compose.yml` after you have tested that Streamlit runs
correctly with it in your environment.

## 5. Local vs production
| Aspect | Local demonstrator | Production requirement |
|---|---|---|
| Users | One operator, no login | SSO/OIDC authentication, roles, per-record authorization |
| Network | localhost only | Reverse proxy (TLS/HTTPS, HSTS), WAF / rate limiting, no direct exposure of Streamlit |
| Database | SQLite file | Managed PostgreSQL, least-privilege DB user, encrypted at rest, automated **backups** with restore tests |
| Secrets | `.env` file | Secret manager (Vault, cloud KMS/Secrets Manager), rotation |
| Migrations | `AUTO_MIGRATE=true` at start | Run `alembic upgrade head` as a release step, `AUTO_MIGRATE=false` |
| Observability | Console logs | JSON logs shipped to a SIEM/log platform, metrics, uptime and error alerting (e.g. OpenTelemetry) |
| Egress | Unrestricted | Egress allow-list (LLM API, retrieval proxy); block metadata IPs at the network layer |
| Privacy | Manual retention runs | DPIA, records of processing, scheduled retention, processor agreements (DPA) with LLM vendors |
| Updates | Manual | CI/CD with tests, image scanning, signed images, dependency update policy |

Passing tests on a laptop does **not** make the application production-ready. The items in
the right-hand column are prerequisites.

## 6. CI/CD (GitHub Actions)
`.github/workflows/ci.yml` runs on every push and pull request:
1. `uv sync --frozen --all-extras` (fails if `uv.lock` is out of date);
2. `ruff check` and `ruff format --check`;
3. unit tests, then integration tests (migrations, services, page rendering);
4. a security job: Bandit on `src/` and pip-audit on the locked dependencies.
Continuous *deployment* is deliberately not configured, because a deployment target
requires the production controls above.
