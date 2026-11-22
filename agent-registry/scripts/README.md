# Registry scripts

Tools for working with a local registry. Run each from `agent-registry/` with the
registry's own environment (`uv run python scripts/<name>.py`, or
`.venv\Scripts\python.exe scripts\<name>.py` on Windows).

- `registry_a2a_client.py "<question>"`: asks a running registry, over A2A with the
  official SDK, which expert fits a question, and prints its reply. The default address
  is `http://127.0.0.1:8001/a2a/registry`; pass `--url` for another. For a registry that
  requires a token, set `REGISTRY_A2A_TOKEN` privately in the environment.
- `seed_demo_agents.py`: adds two demo experts (math and weather) to a local SQLite
  database, so the registry's model has something to choose between; `--remove` deletes
  them. Their endpoints are placeholders that are never called. It refuses any database
  that is not SQLite.
