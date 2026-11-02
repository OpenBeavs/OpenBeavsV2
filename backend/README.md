# OpenBeavs V2: Local Development Setup

_Oct 29, 2026 · @Jiya_

You do not need Cloud SQL to develop locally. The backend reads one setting, `DATABASE_URL`, and if it is unset it uses a SQLite file on your machine. That file is a real database with the same tables, so you can run the app and the real agents without any cloud setup.

## Prerequisites

- Python (version pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/). If `uv` is not recognized, install it with `pip install uv`.
- A Gemini API key (see step 3)

## Setup

### 1. Open the backend folder

```powershell
cd C:\Users\pradh\OpenBeavsV2\backend
```

### 2. Create and activate a virtual environment

A virtual environment keeps this project's packages separate from your other Python projects. Create it once:

```powershell
python -m venv .venv --prompt openbeavs-backend
```

Then activate it. Do this in every new terminal. Your prompt should start with `(openbeavs-backend)`:

```powershell
.\.venv\Scripts\Activate.ps1
```

> **Notes**
> - If PowerShell says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.
> - If you already have the `backend\.venv` folder, skip the create command and only activate it.
> - `uv sync` in the next step also creates `.venv` if it does not exist.

### 3. Install dependencies

```powershell
uv sync
```

This installs everything from `uv.lock` into `backend\.venv`.

### 4. Create your `.env` file

```powershell
Copy-Item .env.example .env
```

Then open `backend/.env` and set:

| Variable | What to do |
| --- | --- |
| `GEMINI_API_KEY` | Your key. Get it from a teammate through a private channel. |
| `DATABASE_URL` | Leave unset (or commented out) to use the local SQLite file. The default is `sqlite:///./openbeavs.db`. |
| Anything else in `.env.example` | Fill in any value that has no default. |

> **Warning:** `GEMINI_API_KEY` is a secret. Never paste it in chat, a doc, or a commit.

### 5. Create the tables and seed the agents

This runs the Alembic migrations, then inserts the default agents into your local database.

```powershell
python -m app.db.init_db
```

It creates the file `openbeavs.db` in `backend/`. That file is your local database.

### 6. Start the server

```powershell
uvicorn app.main:app --reload
```

### 7. Check that it works

In a second terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/chris/agents
```

`/chris/agents` should list the seeded agents.

To try the API in your browser, open the Swagger docs at http://127.0.0.1:8000/docs. It lists every endpoint and lets you run requests from the page.

### 8. View the database (tables, columns, and rows)

To browse your local database without writing SQL, use the **SQLite Viewer** extension in VS Code.

1. In VS Code, open the Extensions panel (`Ctrl+Shift+X`).
2. Search for **SQLite Viewer** and click **Install**.
3. In the Explorer sidebar, click `openbeavs.db` in the `backend/` folder.
4. The viewer opens the file and lists every table. Click a table to see its columns and rows.

> **Note:** Use the viewer to look, not to edit. Stop the server before changing any data by hand, and re-run `python -m app.db.init_db` if you want to reset the seeded agents.
