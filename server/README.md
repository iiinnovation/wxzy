# Server

FastAPI card + FSRS review API.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Apply database migrations from the repository root before starting a production instance:

```bash
alembic -c server/alembic.ini upgrade head
```

For an existing prototype SQLite database that matches the four-table baseline, make a backup,
record the baseline, then confirm that metadata and schema have no drift:

```bash
cp server/wxzy.db /tmp/wxzy-before-migration.db
alembic -c server/alembic.ini stamp 20260722_0001
alembic -c server/alembic.ini upgrade head
alembic -c server/alembic.ini check
```

`stamp 20260722_0001` is only for a database that already matches the original four-table
baseline schema. Never stamp an existing prototype database directly to `head`: doing so would
skip later table creation. Future schema changes must use a new migration revision rather than
`create_all` or a manual table edit.

The production image includes the migration files. With Docker Compose, apply them explicitly
before starting or updating the API service:

```bash
docker compose run --rm api alembic -c alembic.ini upgrade head
docker compose up -d api
```

Install the development toolchain and run the current quality checks from the repository root:

```bash
pip install -r server/requirements-dev.txt
ruff check server tools
ruff format --check server tools
pytest -q
mypy server/app server/migrations tools
coverage run -m pytest -q
coverage report
```

`pyproject.toml` defines the Python 3.12 baseline and tool configuration. The requirements files
mirror its compatible dependency ranges for the server Docker build.

Env:

- `API_TOKEN` (required in prod)
- `DATABASE_URL` (default SQLite file `./wxzy.db`)
