"""Seed live production A2A agents into the database.

Can be run locally or against Google Cloud SQL depending on DATABASE_URL.
"""

import logging

from app.db.session import SessionLocal
from app.models.agent import Agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

INITIAL_AGENTS = [
    {
        "id": "8f695b47-27a7-4ce7-9932-975fc618ba1d",
        "name": "osu_rag_agent",
        "description": "An Oregon State University expert agent that answers questions using a RAG knowledge base of oregonstate.edu content.",
        "endpoint_url": "https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent/",
        "card_url": "https://osu-rag-agent-716080272371.us-west1.run.app/a2a/osu_rag_agent",
        "trust_tier": "public",
        "skills": [
            {
                "id": "osu-knowledge-search",
                "name": "OSU Knowledge Search",
                "description": "Search the Oregon State University knowledge base for information about admissions, academics, financial aid, housing, campus resources, and other OSU topics.",
                "tags": [
                    "osu",
                    "oregon-state",
                    "university",
                    "education",
                    "rag",
                    "search",
                ],
                "examples": [
                    "What are the admissions requirements for Oregon State University?",
                    "How do I apply for financial aid at OSU?",
                    "What majors does Oregon State offer in engineering?",
                    "Tell me about housing options at OSU",
                    "Who is the president of Oregon State University?",
                ],
            }
        ],
        "capabilities": {"pushNotifications": False, "streaming": False},
        "is_active": True,
        "status": "approved",
        "is_featured": True,
        "created_at": 1778370775,
        "updated_at": 1778370775,
    },
    {
        "id": "26b643fd-9a61-465d-b075-89ba84d503cb",
        "name": "Hello World Agent",
        "description": "Just a hello world agent",
        "endpoint_url": "https://hello-world-gxfr.onrender.com/",
        "card_url": "https://hello-world-gxfr.onrender.com/",
        "trust_tier": "public",
        "skills": [
            {
                "id": "hello_world",
                "name": "Returns hello world",
                "description": "just returns hello world",
                "tags": ["hello world"],
                "examples": ["hi", "hello world"],
            }
        ],
        "capabilities": {"streaming": True},
        "is_active": True,
        "status": "approved",
        "is_featured": False,
        "created_at": 1779224572,
        "updated_at": 1779224572,
    },
    {
        "id": "chris",
        "name": "Chris",
        "description": "OpenBeavs orchestrator. Routes your queries to installed agents and answers directly when no agent matches.",
        "endpoint_url": "/chris/message",
        "card_url": "/chris/.well-known/agent.json",
        "trust_tier": "public",
        "skills": [
            {
                "id": "route",
                "name": "Route Query",
                "description": "Classify a user query and delegate to the best installed agent.",
                "tags": ["orchestration", "routing"],
            }
        ],
        "capabilities": {"streaming": True},
        "is_active": True,
        "status": "approved",
        "is_featured": True,
        "created_at": 1778023031,
        "updated_at": 1778023031,
    },
]


def seed_agents() -> None:
    """Insert or update initial agents in the database."""
    db = SessionLocal()
    try:
        for data in INITIAL_AGENTS:
            agent = db.get(Agent, data["id"])
            if agent:
                log.info("Updating existing agent: %s", data["id"])
                for k, v in data.items():
                    if k == "status":
                        # Never overwrite an admin's review decision on re-seed.
                        continue
                    setattr(agent, k, v)
            else:
                log.info("Seeding new agent: %s (%s)", data["id"], data["name"])
                agent = Agent(**data)
                db.add(agent)
        db.commit()
        log.info("Seeding complete! %d agents registered.", len(INITIAL_AGENTS))
    finally:
        db.close()


if __name__ == "__main__":
    seed_agents()
