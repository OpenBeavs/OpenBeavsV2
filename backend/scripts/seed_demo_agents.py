"""Add LOCAL DEMO experts to the local SQLite database (scratch workspace only).

The seeded production experts are an OSU knowledge agent and a "hello world" agent, so
there is nothing for a maths question to match. This adds two clearly labelled demo
experts so the real registry model has something to choose between. Their endpoints are
placeholders (``example.test``) and are never called: this stage stops at the selection.

    .venv\\Scripts\\python.exe scripts\\seed_demo_agents.py          # add (idempotent)
    .venv\\Scripts\\python.exe scripts\\seed_demo_agents.py --remove # delete them again

It refuses to run against anything but a local SQLite database.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_database_url
from app.db import SessionLocal
from app.models import Agent

DEMO = [
    {
        "id": "demo-math-expert",
        "name": "Math Demo Expert",
        "description": (
            "DEMO. Solves arithmetic, percentages, fractions, unit conversions and "
            "basic algebra word problems."
        ),
        "skills": [
            {
                "id": "arithmetic",
                "name": "Arithmetic and percentages",
                "tags": ["math", "arithmetic", "percentages", "algebra"],
                "examples": ["What is 15% of 240?", "Convert 5 miles to kilometers"],
            }
        ],
    },
    {
        "id": "demo-weather-expert",
        "name": "Weather Demo Expert",
        "description": "DEMO. Weather forecasts and conditions for Oregon cities.",
        "skills": [
            {
                "id": "forecast",
                "name": "Oregon weather forecast",
                "tags": ["weather", "forecast", "rain", "temperature", "corvallis"],
                "examples": ["Will it rain in Corvallis tomorrow?"],
            }
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="delete the demo experts")
    args = parser.parse_args()
    if not get_database_url().startswith("sqlite"):
        print("Refusing: this script only touches a local SQLite database.")
        return 2
    now = int(time.time())
    with SessionLocal() as db:
        for spec in DEMO:
            existing = db.get(Agent, spec["id"])
            if args.remove:
                if existing is not None:
                    db.delete(existing)
                    print(f"removed {spec['id']}")
                continue
            if existing is not None:
                print(f"already present: {spec['id']}")
                continue
            db.add(
                Agent(
                    **spec,
                    endpoint_url=f"https://{spec['id']}.example.test/a2a/",
                    card_url=f"https://{spec['id']}.example.test/card.json",
                    trust_tier="public",
                    capabilities={"streaming": False},
                    is_active=True,
                    is_featured=False,
                    status="approved",
                    created_at=now,
                    updated_at=now,
                )
            )
            print(f"added {spec['id']}")
        db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
