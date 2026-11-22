# Shared PostgreSQL server

`owners.sql` gives each owner one schema and one login, and gives each login rights to its own schema alone. The Chat System's login cannot read the Registry's tables, and the Registry's login cannot read the Chat System's. PostgreSQL enforces this, so the boundary holds even when a developer forgets it.

Passwords are set outside this file, from Secret Manager, or replaced by Cloud SQL IAM sign-in.

To add an owner, copy one owner's block in `owners.sql`.

## Apply it

Run `owners.sql` once, as an admin user that owns the `openbeavs` database and holds CREATEROLE. Cloud SQL's `postgres` user is such a user. It is not a superuser, and the file needs none. From the repository's root, with `ADMIN_DATABASE_URL` set to that user's connection (`postgresql://<admin>:<password>@<host>:5432/openbeavs`):

```bash
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f shared-resources/postgres/owners.sql
```

Each login is created without a password and cannot sign in until it has one. The same admin user sets them:

```bash
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -v chat_system="$CHAT_SYSTEM_PASSWORD" -v registry="$REGISTRY_PASSWORD" <<'SQL'
ALTER ROLE chat_system PASSWORD :'chat_system';
ALTER ROLE registry PASSWORD :'registry';
SQL
```

Each login's `search_path` is its own schema, so the tables it creates land there and the code names no schema.

## Test against it

The backend and Agent Registry tests run on SQLite unless they are given a PostgreSQL server prepared as above. Give them one URL per login, and they create each owner's tables signed in as that owner and run each owner's code under its own login:

```bash
export TEST_CHAT_SYSTEM_DATABASE_URL="postgresql+psycopg2://chat_system:$CHAT_SYSTEM_PASSWORD@127.0.0.1:5432/openbeavs"
export TEST_REGISTRY_DATABASE_URL="postgresql+psycopg2://registry:$REGISTRY_PASSWORD@127.0.0.1:5432/openbeavs"
(cd agent-registry && uv run pytest)
(cd backend && uv run pytest)
```

The registry's own tests read only `TEST_REGISTRY_DATABASE_URL`. These two URLs begin `postgresql+psycopg2://` because SQLAlchemy reads them, and `psycopg2` is the PostgreSQL driver both packages install. A URL that begins `postgresql://` asks SQLAlchemy for a driver they lack.

`tests/test_database_grants.py` tests the boundary itself: each login works in its own schema and is refused on the other's. Without the two URLs those tests are skipped, and the rest of the suite runs on SQLite. With the same two variables set, `npm run test:pipeline` in `frontend/` runs the browser pipeline against the server as well.

The tests drop and recreate each owner's tables, so give them a database kept for testing.

## A local server for testing

`docker run -d -e POSTGRES_PASSWORD=<password> -p 127.0.0.1:5432:5432 postgres:16` starts PostgreSQL 16 on this machine. Its `postgres` user is a superuser, which skips the permission checks Cloud SQL applies, so use it for one thing: creating an admin user with the rights Cloud SQL's has, and the database that user owns.

```sql
CREATE ROLE openbeavs_admin LOGIN CREATEROLE CREATEDB PASSWORD '<password>';
CREATE DATABASE openbeavs OWNER openbeavs_admin;
```

Then apply `owners.sql` as `openbeavs_admin`. Applied as the superuser it would succeed even where Cloud SQL would refuse it.
