"""Application Services does not host the Agent Registry.

Chat and Chris reach the registry over A2A as a separate service, so the registry's
Agent Card path, which the registry serves under its A2A mount, is not found here.
"""

from fastapi.testclient import TestClient

from application_services.main import app

# The registry's Agent Card, at the path its own service serves it.
CARD_PATH = "/a2a/registry/.well-known/agent-card.json"


class TestWiring:
    def test_the_integrated_backend_does_not_host_it(self) -> None:
        """Chat and Chris reach the registry over A2A as a separate service."""
        assert TestClient(app).get(CARD_PATH).status_code == 404
