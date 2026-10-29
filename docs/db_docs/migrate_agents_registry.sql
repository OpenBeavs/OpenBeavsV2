-- =============================================================================
-- OpenBeavs v2: add the agent registry review columns to an EXISTING database
-- Database: openbeavs_v2 (PostgreSQL / Cloud SQL)
-- Equivalent of Alembic revision a7c3e91d5b02 (backend/alembic/versions/).
--
-- Use this file ONLY if the database was created from create_tables_cloud.sql
-- (no alembic_version table). If it was created with Alembic, run
-- `alembic upgrade head` instead and do not run this file.
--
-- Safe for existing data: every agent already in the table becomes 'approved',
-- so Chris keeps routing to the same agents as before. The default is then
-- removed so new rows must state a status explicitly.
--
-- Run it once. A second run fails on the first ADD COLUMN, which is harmless
-- because the transaction rolls back.
-- =============================================================================

-- BEFORE: confirm the columns are not there yet (expect 0 rows)
--   SELECT column_name FROM information_schema.columns
--   WHERE table_name = 'agents' AND column_name IN ('status', 'submitted_by');
--
-- BEFORE: confirm no two agents share a card_url (expect 0 rows), otherwise the
-- unique constraint below will fail:
--   SELECT card_url, COUNT(*) FROM agents WHERE card_url IS NOT NULL
--   GROUP BY card_url HAVING COUNT(*) > 1;

BEGIN;

ALTER TABLE agents ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'approved';
ALTER TABLE agents ALTER COLUMN status DROP DEFAULT;
ALTER TABLE agents ADD COLUMN submitted_by VARCHAR(255);
ALTER TABLE agents ADD COLUMN reviewed_by VARCHAR(255);
ALTER TABLE agents ADD COLUMN reviewed_at BIGINT;
ALTER TABLE agents ADD COLUMN review_note TEXT;
ALTER TABLE agents ADD CONSTRAINT uq_agents_card_url UNIQUE (card_url);

COMMIT;

-- AFTER: every existing agent should be approved (expect only 'approved' rows)
--   SELECT id, name, status, is_active FROM agents ORDER BY name;
--
-- If the database is managed with Alembic from now on, record the revision so
-- `alembic upgrade head` does not try to run it again:
--   alembic stamp a7c3e91d5b02

-- ROLLBACK (only if you must undo this change):
--   BEGIN;
--   ALTER TABLE agents DROP CONSTRAINT uq_agents_card_url;
--   ALTER TABLE agents DROP COLUMN review_note;
--   ALTER TABLE agents DROP COLUMN reviewed_at;
--   ALTER TABLE agents DROP COLUMN reviewed_by;
--   ALTER TABLE agents DROP COLUMN submitted_by;
--   ALTER TABLE agents DROP COLUMN status;
--   COMMIT;
