-- One schema and one login per owner, each with rights to its own schema alone.
-- Run as the server's admin user, connected to the database the services use.
-- The admin user must own that database and hold CREATEROLE. It need not be a
-- superuser, so Cloud SQL's postgres user can run this file.
-- Each login is created without a password; README.md says how to set one.

-- The file names no database: it acts on the one this session is connected to.
-- GRANT and REVOKE take a database's name written out, so each statement that needs
-- the name is built from current_database() in a DO block, which any client can run.

-- Nobody gets anything by default.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database()); END $$;

-- In each block, the admin user joins the new role before creating its schema.
-- PostgreSQL lets a user hand a schema only to a role it can SET ROLE to, and since
-- PostgreSQL 16 creating a role no longer gives its creator that right.

-- OpenBeavs Chat System
CREATE ROLE chat_system LOGIN;
GRANT chat_system TO CURRENT_USER;
CREATE SCHEMA chat_system AUTHORIZATION chat_system;
DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO chat_system', current_database()); END $$;
ALTER ROLE chat_system SET search_path = chat_system;

-- Agent Registry
CREATE ROLE registry LOGIN;
GRANT registry TO CURRENT_USER;
CREATE SCHEMA registry AUTHORIZATION registry;
DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO registry', current_database()); END $$;
ALTER ROLE registry SET search_path = registry;

-- Each login owns its schema and so holds every right inside it.
-- Neither holds USAGE on the other's schema, so neither can reach the other's tables.
