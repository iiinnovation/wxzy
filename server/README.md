# server

FastAPI card + FSRS review API.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Env:

- `API_TOKEN` (required in prod)
- `DATABASE_URL` (default SQLite file `./wxzy.db`)
