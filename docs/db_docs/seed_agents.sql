-- =============================================================================
-- OpenBeavs v2: Seed Live Production Agents (Exported from Cloud SQL v1)
-- Database: openbeavs_v2
-- Agents: osu_rag_agent (GCP Cloud Run), Hello World Agent (Render), Chris (Orchestrator)
-- =============================================================================

INSERT INTO agents (
    id,
    name,
    description,
    endpoint_url,
    card_url,
    trust_tier,
    required_role,
    skills,
    capabilities,
    is_active,
    is_featured,
    status,
    created_at,
    updated_at
) VALUES 
(
    '8f695b47-27a7-4ce7-9932-975fc618ba1d',
    'osu_rag_agent',
    'An Oregon State University expert agent that answers questions using a RAG knowledge base of oregonstate.edu content.',
    'https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent/',
    'https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent',
    'public',
    NULL,
    '[{"description": "Search the Oregon State University knowledge base for information about admissions, academics, financial aid, housing, campus resources, and other OSU topics.", "examples": ["What are the admissions requirements for Oregon State University?", "How do I apply for financial aid at OSU?", "What majors does Oregon State offer in engineering?", "Tell me about housing options at OSU", "Who is the president of Oregon State University?"], "id": "osu-knowledge-search", "name": "OSU Knowledge Search", "tags": ["osu", "oregon-state", "university", "education", "rag", "search"]}]'::json,
    '{"pushNotifications": false, "streaming": false}'::json,
    TRUE,
    TRUE,
    'approved',
    1778370775,
    1778370775
),
(
    '26b643fd-9a61-465d-b075-89ba84d503cb',
    'Hello World Agent',
    'Just a hello world agent',
    'https://hello-world-gxfr.onrender.com/',
    'https://hello-world-gxfr.onrender.com/',
    'public',
    NULL,
    '[{"description": "just returns hello world", "examples": ["hi", "hello world"], "id": "hello_world", "name": "Returns hello world", "tags": ["hello world"]}]'::json,
    '{"streaming": true}'::json,
    TRUE,
    FALSE,
    'approved',
    1779224572,
    1779224572
),
(
    'chris',
    'Chris',
    'OpenBeavs orchestrator. Routes your queries to installed agents and answers directly when no agent matches.',
    '/chris/message',
    '/chris/.well-known/agent.json',
    'public',
    NULL,
    '[{"id": "route", "name": "Route Query", "description": "Classify a user query and delegate to the best installed agent.", "tags": ["orchestration", "routing"]}]'::json,
    '{"streaming": true}'::json,
    TRUE,
    TRUE,
    'approved',
    1778023031,
    1778023031
)
-- Preserve all existing settings and metadata; only add missing default agents.
ON CONFLICT (id) DO NOTHING;
