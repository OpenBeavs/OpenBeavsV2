"""Keep Chris's SDK task and session state local to one HTTP request.

Chat supplies history on every turn. There is no supported task polling or
cross-request session continuation until caller isolation is implemented.
"""

from a2a.server.context import ServerCallContext
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, ListTasksRequest, ListTasksResponse
from a2a.utils.errors import UnsupportedOperationError
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.types import Receive, Scope, Send

from app.chris.agent import chris_agent


class MessageOnlyTaskStore(InMemoryTaskStore):
    """Support SDK execution within a request, without task enumeration."""

    async def list(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        """Reject listing even when the request-local store is empty."""
        raise UnsupportedOperationError(message="Chris does not support task retrieval.")


class RequestScopedA2A:
    """Give each RPC its own ADK app, executor, task store and session service.

    The SDK still handles the protocol. A later request cannot retrieve or resume
    earlier tasks or sessions, even if it supplies their IDs. Completed state has
    no application-wide owner and can be released when SDK execution finishes.
    """

    def __init__(self, card: AgentCard) -> None:
        self.card = card

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Initialize and dispatch through a fresh SDK application for this RPC."""
        app = to_a2a(
            chris_agent,
            agent_card=self.card,
            task_store=MessageOnlyTaskStore(),
        )
        async with app.router.lifespan_context(app):
            await app(scope, receive, send)
