# Convenience targets (Linux/macOS/Git Bash). PowerShell equivalents are in docs/DEPLOYMENT.md.
.PHONY: install init seed run test lint format check docker-up docker-down

install:  ## install locked dependencies (incl. dev tools)
	uv sync --all-extras

init:     ## create / upgrade the database schema
	uv run python scripts/initialize_database.py

seed:     ## (re)load deterministic fictional demo data
	uv run python scripts/seed_demo.py --reset

run:      ## start the Streamlit app on http://localhost:8501
	uv run streamlit run app.py

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test
	uv run python scripts/verify_setup.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
