"""Agent registry: submit agents by URL, review them, and expose approved ones.

The registry owns the ``agents`` table and runs as its own service. Chris routes only
to agents that an admin has approved (see ``service.routable_agents``).
"""
