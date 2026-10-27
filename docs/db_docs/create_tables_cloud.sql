-- =============================================================================
-- OpenBeavs v2: Cloud SQL PostgreSQL Schema Definition (REFERENCE EXPORT ONLY)
-- Database: openbeavs_v2
-- NOTE: Do NOT run this file manually as a setup step. Database schemas are
-- managed exclusively via Alembic migrations (run: `alembic upgrade head`).
-- This file is generated from SQLAlchemy 2.0 declarative models and serves
-- strictly as an architectural and DDL reference export.
-- =============================================================================

-- 1. Agents Table (A2A Registry)
CREATE TABLE IF NOT EXISTS agents (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    endpoint_url VARCHAR(512) NOT NULL,
    card_url VARCHAR(512),
    trust_tier VARCHAR(32) NOT NULL DEFAULT 'public',
    required_role VARCHAR(64),
    skills JSON DEFAULT '[]'::json,
    capabilities JSON DEFAULT '{}'::json,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

-- 2. Users Table (OSU Microsoft SSO / OIDC)
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    display_name VARCHAR(255),
    role VARCHAR(64) NOT NULL DEFAULT 'student',
    kms_key_ref TEXT,
    created_at BIGINT NOT NULL,
    last_login_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 3. Chats Table (Sessions, Iframe Context, and Guest TTL)
CREATE TABLE IF NOT EXISTS chats (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    guest_session_id VARCHAR(64),
    agent_id VARCHAR(64) REFERENCES agents(id) ON DELETE SET NULL,
    title VARCHAR(255) DEFAULT 'New Conversation',
    source_domain VARCHAR(255),
    session_type VARCHAR(32) NOT NULL DEFAULT 'guest',
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    expires_at BIGINT
);

CREATE INDEX IF NOT EXISTS idx_chats_user_id ON chats(user_id);
CREATE INDEX IF NOT EXISTS idx_chats_guest_session_id ON chats(guest_session_id);
CREATE INDEX IF NOT EXISTS idx_chats_agent_id ON chats(agent_id);
CREATE INDEX IF NOT EXISTS idx_chats_source_domain ON chats(source_domain);
CREATE INDEX IF NOT EXISTS idx_chats_expires_at ON chats(expires_at);

-- 4. Messages Table (Relational Turns with Cascade Deletion)
CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(36) PRIMARY KEY,
    chat_id VARCHAR(36) NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    sender_type VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    encrypted_dek BYTEA,
    meta JSON,
    created_at BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- 5. Tickets Table (User Feedback & Support)
CREATE TABLE IF NOT EXISTS tickets (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE SET NULL,
    name VARCHAR(128) NOT NULL,
    email VARCHAR(255) NOT NULL,
    issue_type VARCHAR(64) NOT NULL,
    description TEXT NOT NULL,
    info JSON,
    status VARCHAR(32) NOT NULL DEFAULT 'new',
    created_at BIGINT NOT NULL,
    resolved_at BIGINT
);

CREATE INDEX IF NOT EXISTS idx_tickets_user_id ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
