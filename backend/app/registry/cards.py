"""Fetch and validate an A2A agent's discovery card.

Every A2A agent publishes a small JSON "card" at ``/.well-known/agent.json``.
The registry stores what the card says, so this module is the only place that
turns untrusted remote JSON into registry fields. It never follows redirects,
caps the response size, and rejects values that would not fit the database.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.registry.security import Resolver, validate_agent_url

log = logging.getLogger(__name__)

CARD_TIMEOUT_SECONDS = 10
MAX_CARD_BYTES = 100_000
MAX_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 4000
MAX_URL_LENGTH = 512
MAX_SKILLS = 50
WELL_KNOWN = "/.well-known/"

# Phrases that try to steer Chris's routing from inside a card. A match flags the
# card for the reviewer; it does not block the submission.
_INJECTION_PATTERNS = [
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE
    ),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(
        r"\balways\s+(reply|respond|answer|route|choose|select)\b", re.IGNORECASE
    ),
    re.compile(r"\bfor\s+every\s+(user\s+)?(message|query|request)\b", re.IGNORECASE),
]


class CardError(ValueError):
    """Raised when a card cannot be fetched or is not acceptable."""


@dataclass(frozen=True)
class AgentCard:
    """The validated subset of an agent card that the registry stores."""

    name: str
    description: str
    card_url: str
    endpoint_url: str
    skills: list[Any] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


def looks_like_prompt_injection(text: str) -> bool:
    """Return True if ``text`` contains wording aimed at hijacking routing."""
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def derive_card_url(url: str) -> str:
    """Return the card address for a submitted URL.

    A URL that already contains ``/.well-known/`` is used as given. Otherwise the
    card is looked up at the host's ``/.well-known/agent.json`` (any path on the
    submitted URL is dropped, so paste the full card URL for path-hosted agents).
    """
    candidate = url.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = "https://" + candidate
    if WELL_KNOWN in candidate:
        return candidate
    parts = urlsplit(candidate)
    return f"{parts.scheme}://{parts.netloc}{WELL_KNOWN}agent.json"


def derive_endpoint_url(card_url: str) -> str:
    """Return the A2A JSON-RPC endpoint: the card's path without ``/.well-known/…``.

    Built from the address we fetched, never from a URL written inside the card,
    so a hostile card cannot redirect later calls to an internal host.
    """
    parts = urlsplit(card_url)
    prefix = (
        parts.path[: parts.path.index(WELL_KNOWN)] if WELL_KNOWN in parts.path else ""
    )
    return f"{parts.scheme}://{parts.netloc}{prefix}/"


def parse_card(raw: Any, card_url: str) -> AgentCard:
    """Validate decoded card JSON and return the fields the registry stores.

    Raises:
        CardError: If a required field is missing or a value is unusable.
    """
    if not isinstance(raw, dict):
        raise CardError("The agent card must be a JSON object.")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CardError("The agent card has no name.")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise CardError(f"The agent name is longer than {MAX_NAME_LENGTH} characters.")

    description = raw.get("description") or ""
    if not isinstance(description, str):
        raise CardError("The agent description must be text.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise CardError(
            f"The agent description is longer than {MAX_DESCRIPTION_LENGTH} characters."
        )

    skills = raw.get("skills", [])
    if not isinstance(skills, list) or len(skills) > MAX_SKILLS:
        raise CardError(f"Skills must be a list of at most {MAX_SKILLS} items.")
    capabilities = raw.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise CardError("Capabilities must be an object.")

    endpoint_url = derive_endpoint_url(card_url)
    if len(card_url) > MAX_URL_LENGTH or len(endpoint_url) > MAX_URL_LENGTH:
        raise CardError(f"URLs must be at most {MAX_URL_LENGTH} characters.")

    flags = []
    searchable = " ".join([name, description, str(skills)])
    if looks_like_prompt_injection(searchable):
        flags.append("Card text looks like an attempt to steer Chris's routing.")

    return AgentCard(
        name=name,
        description=description.strip(),
        card_url=card_url,
        endpoint_url=endpoint_url,
        skills=skills,
        capabilities=capabilities,
        flags=flags,
    )


def fetch_card(
    url: str,
    *,
    allow_http: bool = False,
    client: httpx.Client | None = None,
    resolver: Resolver | None = None,
) -> AgentCard:
    """Fetch, size-limit and validate the card for a submitted agent URL.

    Args:
        url: What the submitter typed (scheme optional).
        allow_http: Permit plain http (local development only).
        client: Optional preconfigured client, used by tests.
        resolver: Optional DNS resolver, used by tests to avoid real lookups.

    Raises:
        UnsafeURLError: The address is not safe to fetch.
        CardError: The card could not be fetched, was too large, or is invalid.
    """
    card_url = derive_card_url(url)
    validate_agent_url(card_url, allow_http=allow_http, resolver=resolver)

    owns_client = client is None
    http = client or httpx.Client(timeout=CARD_TIMEOUT_SECONDS, follow_redirects=False)
    try:
        with http.stream("GET", card_url) as response:
            if response.is_redirect:
                raise CardError("The agent card address redirected; use the final URL.")
            if response.status_code != 200:
                raise CardError(
                    f"The agent card request returned HTTP {response.status_code}."
                )
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_CARD_BYTES:
                    raise CardError("The agent card is too large.")
    except httpx.HTTPError as exc:
        log.info("Card fetch failed for %s: %s", card_url, type(exc).__name__)
        raise CardError(
            f"Could not reach the agent card ({type(exc).__name__})."
        ) from exc
    finally:
        if owns_client:
            http.close()

    try:
        raw = httpx.Response(200, content=bytes(body)).json()
    except ValueError as exc:
        raise CardError("The agent card is not valid JSON.") from exc
    return parse_card(raw, card_url)
