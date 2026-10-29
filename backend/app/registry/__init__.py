"""Agent registry: submit agents by URL, review them, and expose approved ones.

The registry writes to the unified ``agents`` table. Chris routes only to agents
that an admin has approved (see ``service.routable_agents``).
"""
