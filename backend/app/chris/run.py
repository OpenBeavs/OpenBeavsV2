"""Run Chris's A2A server independently of the main application."""

import uvicorn
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from app.chris.agent import chris_agent


def main() -> None:
    """Expose Chris's agent card and A2A message endpoint."""
    app = to_a2a(
        chris_agent,
        host="localhost",
        port=8000,
        rpc_path="chris/a2a",
    )
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
