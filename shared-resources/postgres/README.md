# Shared PostgreSQL server

`owners.sql` gives each owner one schema and one login, and gives each login rights to its own schema alone. The Chat System's login cannot read the Registry's tables, and the Registry's login cannot read the Chat System's. PostgreSQL enforces this, so the boundary holds even when a developer forgets it.

Passwords are set outside this file, from Secret Manager, or replaced by Cloud SQL IAM sign-in.

To add an owner, copy one owner's block in `owners.sql`.

## Test against it

The Agent Registry's, Application Services', and end-to-end tests run on SQLite unless they are given a PostgreSQL server prepared by `owners.sql`. Given one URL per login, they create each owner's tables signed in as that owner and run each owner's code under its own login. `tests/end-to-end/tests/test_database_grants.py` tests the boundary itself: each login works in its own schema and is refused on the other's. Without the two URLs those tests are skipped.

These commands run PostgreSQL 16 in Docker on this machine and use the container's own `psql`, so the machine needs Docker and no PostgreSQL client. Run them from the repository's root, after the packages are installed as the root README says. Port 5432 must be free.

Start the server, and wait until it accepts connections:

```zsh
PG=openbeavs-postgres
docker run -d --name "$PG" -e POSTGRES_PASSWORD=local-superuser -p 127.0.0.1:5432:5432 postgres:16
until docker exec "$PG" pg_isready -h 127.0.0.1 -U postgres -q; do sleep 1; done
```

The container's `postgres` user is a superuser, which skips the permission checks Cloud SQL applies, so use it for one thing: creating an admin user with the rights Cloud SQL's `postgres` user has (CREATEROLE and CREATEDB, no superuser), and the database that user owns. That admin user then applies `owners.sql` and sets the two owners' passwords. Applied as the superuser, `owners.sql` would succeed even where Cloud SQL would refuse it.

```zsh
docker exec -i "$PG" psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE openbeavs_admin LOGIN CREATEROLE CREATEDB PASSWORD 'local-admin';
CREATE DATABASE openbeavs OWNER openbeavs_admin;
SQL
docker exec -i "$PG" psql -U openbeavs_admin -d openbeavs -v ON_ERROR_STOP=1 --single-transaction -f - < shared-resources/postgres/owners.sql
docker exec -i "$PG" psql -U openbeavs_admin -d openbeavs -v ON_ERROR_STOP=1 <<'SQL'
ALTER ROLE chat_system PASSWORD 'local-chat-system';
ALTER ROLE registry PASSWORD 'local-registry';
SQL
```

These passwords guard a throwaway server that listens only on this machine. Give each suite one URL per login, and run the grants test, then every suite and the browser pipeline:

```zsh
export TEST_CHAT_SYSTEM_DATABASE_URL='postgresql+psycopg2://chat_system:local-chat-system@127.0.0.1:5432/openbeavs'
export TEST_REGISTRY_DATABASE_URL='postgresql+psycopg2://registry:local-registry@127.0.0.1:5432/openbeavs'
(cd tests/end-to-end && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest tests/test_database_grants.py)
(cd agent-registry && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd chat-system/application-services && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd tests/end-to-end && PYTHON_DOTENV_DISABLED=1 DATABASE_URL='sqlite:///:memory:' uv run pytest)
(cd chat-system/web-ui && npm run test:pipeline)
```

With the two URLs set, the end-to-end suite skips nothing. The registry's own tests read only `TEST_REGISTRY_DATABASE_URL`, and Application Services' only `TEST_CHAT_SYSTEM_DATABASE_URL`; the Conversation Agent has no database, so its tests are the same on either server. The URLs begin `postgresql+psycopg2://` because SQLAlchemy reads them, and `psycopg2` is the PostgreSQL driver the packages install; a URL that begins `postgresql://` asks SQLAlchemy 2.1 for a driver they lack. The tests drop and recreate each owner's tables, so give them a database kept for testing.

Stop the server when you are done:

```zsh
docker stop "$PG"
```

`docker start openbeavs-postgres` starts the same server again later, with its logins and passwords. In a new terminal, set `PG=openbeavs-postgres` again, wait with the `until` line, and run the test commands. To start over, `docker rm openbeavs-postgres` removes the stopped server, and the first block creates a new one.

## Apply it to a hosted server

Run `owners.sql` once, as an admin user that owns the database the services use and holds CREATEROLE. Cloud SQL's `postgres` user is such a user. It is not a superuser, and the file needs none. The file names no database: it acts on the one the session is connected to.

These commands run `psql` on your own machine against the remote server (on macOS, `brew install libpq` provides it). From the repository's root, with `ADMIN_DATABASE_URL` set to that user's connection to that database (`postgresql://<admin>:<password>@<host>:5432/<database>`):

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

Each login's `search_path` is its own schema, so the tables it creates land there and the code names no schema. Each service then connects as its own login: the Agent Registry's `DATABASE_URL` as `registry`, and Application Services' as `chat_system`, each beginning `postgresql+psycopg2://`.

`owners.sql` closes the schema `public` and the database to every login it does not name. If the database already holds tables there, created by the migrations the owners once shared, stop the services before applying it and follow [the next section](#a-database-built-by-the-earlier-shared-migrations).

## A database built by the earlier, shared migrations

Before each owner had its own migrations, one history (`backend/alembic/`, since removed) created every owner's tables in the schema `public` and kept one `alembic_version` table for all of them. `owners.sql` confines each login to its own schema, so in such a database neither owner finds its tables until they are moved there. The move changes no row. Both owners move together, in one transaction.

1. Stop every service that uses the database: the single backend server that ran before the owners had services of their own, or Application Services and the Agent Registry. Leave them stopped until step 7. Step 4 takes away the access of the login they have been using, unless that login owns the database, and step 5 moves the tables out of the schema where they look for them.
2. Take a backup (on Cloud SQL, a backup of the instance).
3. As the admin user, check that the earlier history is at its head: `SELECT version_num FROM public.alembic_version;` returns `e6b2c4a9f815`. Note `SELECT count(*)` for `agents`, `users`, `chats`, `messages`, and `tickets`, for step 7. The tables belong to the login that created them. If the admin user is not that login, PostgreSQL refuses it here, and will again in step 5, until it is a member of that login: `GRANT <that login> TO CURRENT_USER;`. If the revision is an earlier one, bring the database to the head with the shared migrations now, signed in as the login that has been running them. The [Agent Registry's README](../../agent-registry/README.md#a-database-built-by-the-earlier-shared-migrations), step 2, says where to find them.
4. Apply `owners.sql` and set the two passwords, as [Apply it to a hosted server](#apply-it-to-a-hosted-server) says, if that is not already done.
5. As the admin user, move each owner's tables into its schema and give them to its login:

```bash
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction <<'SQL'
DO $$ BEGIN
  IF (SELECT version_num FROM public.alembic_version) IS DISTINCT FROM 'e6b2c4a9f815' THEN
    RAISE EXCEPTION 'the shared migrations are not at their head, e6b2c4a9f815';
  END IF;
END $$;
ALTER TABLE public.users    SET SCHEMA chat_system;
ALTER TABLE public.chats    SET SCHEMA chat_system;
ALTER TABLE public.messages SET SCHEMA chat_system;
ALTER TABLE public.tickets  SET SCHEMA chat_system;
ALTER TABLE chat_system.users    OWNER TO chat_system;
ALTER TABLE chat_system.chats    OWNER TO chat_system;
ALTER TABLE chat_system.messages OWNER TO chat_system;
ALTER TABLE chat_system.tickets  OWNER TO chat_system;
ALTER TABLE public.agents   SET SCHEMA registry;
ALTER TABLE registry.agents OWNER TO registry;
DROP TABLE public.alembic_version;
SQL
```

`SET SCHEMA` moves a table with its rows, indexes, and constraints, and `OWNER TO` gives it to the owner's login. The admin user may do both because `owners.sql` made it a member of both logins. The first statement stops the transaction unless the earlier history is at its head. The last drops the shared `alembic_version` table: its one row names a revision neither owner's history knows, and from step 6 each owner keeps a version table of its own in its own schema. The transaction does all of this or none of it.

6. Record each owner's first revision, signed in as that owner, and check it. With `REGISTRY_DATABASE_URL` and `CHAT_SYSTEM_DATABASE_URL` set to each login's connection (`postgresql+psycopg2://registry:<password>@<host>:5432/<database>`, and the same for `chat_system`), from the repository's root:

```bash
(cd agent-registry && export DATABASE_URL="$REGISTRY_DATABASE_URL" && uv run alembic stamp --purge 182d32a2edcd && uv run alembic current && uv run alembic check)
(cd chat-system/application-services && export DATABASE_URL="$CHAT_SYSTEM_DATABASE_URL" && uv run alembic stamp --purge 34fddc6e996d && uv run alembic current && uv run alembic check)
```

`stamp` creates the owner's `alembic_version` table in its schema and writes the revision there without running it. `current` then prints `182d32a2edcd (head)` for the registry and `34fddc6e996d (head)` for the chat system, and each `check` reports no new upgrade operations: the moved tables are the ones the owner's first revision creates.

7. Verify, then start each service with its own login in `DATABASE_URL`. Signed in as `registry`, `SELECT count(*) FROM agents;` returns the count from step 3, and signed in as `chat_system` so do `users`, `chats`, `messages`, and `tickets`. As the admin user, `SELECT tablename FROM pg_tables WHERE schemaname = 'public';` returns no rows.
