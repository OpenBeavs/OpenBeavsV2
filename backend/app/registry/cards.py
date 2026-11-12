"""Fetch and validate an A2A agent's discovery card.

Every A2A agent publishes a small JSON "card" at ``/.well-known/agent.json``.
The registry stores what the card says, so this module is the only place that
turns untrusted remote JSON into registry fields. It never follows redirects,
caps the response size, and rejects values that would not fit the database.
"""

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.registry.security import Resolver, validate_agent_url

log = logging.getLogger(__name__)

CARD_TIMEOUT_SECONDS = 10  # hard limit for the whole fetch
CARD_CONNECT_TIMEOUT_SECONDS = 3
# Per read/write; cold-starting Cloud Run agents can take several seconds to answer.
CARD_STEP_TIMEOUT_SECONDS = 8
_MAX_FETCH_WORKERS = 8
_fetch_slots = threading.BoundedSemaphore(_MAX_FETCH_WORKERS)
MAX_CARD_BYTES = 100_000
MAX_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 4000
MAX_URL_LENGTH = 512
MAX_SKILLS = 50
MAX_SKILL_TEXT_LENGTH = 64  # skill id and name, and each tag
MAX_TAGS_PER_SKILL = 10
_TIMEOUT_MESSAGE = "The agent card did not arrive in time."
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


def clean_text(text: str) -> str:
    """Make untrusted card text plain: no control or invisible characters.

    Chris puts card text into its prompts, so newlines (which could fake a new
    prompt section), zero-width and direction-override characters are removed and
    runs of whitespace collapse to one space.
    """
    text = "".join(
        " " if ch.isspace() else ch
        for ch in text
        if not unicodedata.category(ch) in ("Cc", "Cf") or ch.isspace()
    )
    return " ".join(text.split())


def _clean_skill(skill: Any) -> Any:
    """Return a skill with its text cleaned and bounded, or raise CardError."""
    if isinstance(skill, str):
        skill = {"name": skill}
    if not isinstance(skill, dict):
        raise CardError("Each skill must be an object or a string.")
    cleaned = dict(skill)
    for key in ("id", "name"):
        if key in cleaned:
            value = cleaned[key]
            if not isinstance(value, str):
                raise CardError(f"A skill {key} must be text.")
            cleaned[key] = clean_text(value)
            if len(cleaned[key]) > MAX_SKILL_TEXT_LENGTH:
                raise CardError(
                    f"A skill {key} is longer than {MAX_SKILL_TEXT_LENGTH} characters."
                )
    if isinstance(cleaned.get("description"), str):
        cleaned["description"] = clean_text(cleaned["description"])
    if "tags" in cleaned:
        tags = cleaned["tags"]
        if not isinstance(tags, list) or len(tags) > MAX_TAGS_PER_SKILL:
            raise CardError(
                f"Skill tags must be a list of at most {MAX_TAGS_PER_SKILL} items."
            )
        if not all(isinstance(tag, str) for tag in tags):
            raise CardError("Skill tags must be text.")
        cleaned["tags"] = [clean_text(tag) for tag in tags]
        if any(len(tag) > MAX_SKILL_TEXT_LENGTH for tag in cleaned["tags"]):
            raise CardError(
                f"A skill tag is longer than {MAX_SKILL_TEXT_LENGTH} characters."
            )
    return cleaned


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


# The only transport the hub speaks to experts: JSON-RPC over HTTP. A2A 1.0 names it
# in ``supportedInterfaces[].protocolBinding``; 0.3 cards name it in
# ``preferredTransport`` / ``additionalInterfaces[].transport``.
SUPPORTED_BINDING = "JSONRPC"
# A2A versions the hub can talk to, best first. A listed version matches on its
# major.minor (1.0, 1.1 ... count as "1"; 0.3.0 counts as "0.3").
_PROTOCOL_RANK = {"1": 2, "0.3": 1}


def _protocol_rank(version: Any) -> int:
    """Return how much the hub prefers ``version`` (0 means it cannot be used)."""
    if not isinstance(version, str):
        return 0
    parts = version.strip().split(".")
    return _PROTOCOL_RANK.get(parts[0], 0) or _PROTOCOL_RANK.get(".".join(parts[:2]), 0)


def _is_jsonrpc(binding: Any) -> bool:
    return isinstance(binding, str) and binding.strip().upper() == SUPPORTED_BINDING


def select_endpoint(raw: dict[str, Any]) -> str:
    """Choose which advertised address the registry stores as the agent's endpoint.

    Two card formats exist, and the choice is explicit rather than "the first url":

    - **A2A 1.0** lists ``supportedInterfaces``. Only entries with the JSON-RPC
      binding and a protocol version the hub supports (1.x, or 0.3) qualify; the
      newest version wins and the card's own order breaks ties. If the list is
      present but has no qualifying entry the card is rejected. It is never
      replaced by a different field.
    - **Older cards** (no ``supportedInterfaces``) use the top-level ``url``. It must
      be JSON-RPC (``preferredTransport`` absent or ``JSONRPC``), otherwise a
      JSON-RPC entry in ``additionalInterfaces`` is used.

    The result is only *chosen* here; the caller still applies every URL safety check.

    Raises:
        CardError: If no usable endpoint is advertised.
    """
    listed = raw.get("supportedInterfaces")
    if listed not in (None, []):
        if not isinstance(listed, list):
            raise CardError("supportedInterfaces must be a list.")
        best: tuple[int, str] | None = None
        for item in listed:
            if not isinstance(item, dict):
                continue
            if not _is_jsonrpc(item.get("protocolBinding")):
                continue
            rank = _protocol_rank(item.get("protocolVersion"))
            url = item.get("url")
            usable = rank and isinstance(url, str) and url.strip()
            if usable and (best is None or rank > best[0]):
                best = (rank, url.strip())
        if best is None:
            raise CardError(
                "The agent card lists no supported interface (it needs JSON-RPC "
                "with A2A 1.x or 0.3)."
            )
        return best[1]

    url = raw.get("url")
    transport = raw.get("preferredTransport")
    if transport is None or _is_jsonrpc(transport):
        if not isinstance(url, str) or not url.strip():
            raise CardError("The agent card must advertise a non-empty endpoint url.")
        return url.strip()
    for item in raw.get("additionalInterfaces") or []:
        if isinstance(item, dict) and _is_jsonrpc(item.get("transport")):
            extra = item.get("url")
            if isinstance(extra, str) and extra.strip():
                return extra.strip()
    raise CardError("The agent card offers no JSON-RPC endpoint url.")


def parse_card(
    raw: Any,
    card_url: str,
    *,
    allow_http: bool = False,
    resolver: Resolver | None = None,
) -> AgentCard:
    """Validate card fields and the advertised absolute service URL.

    The endpoint comes from ``select_endpoint`` (A2A 1.0 ``supportedInterfaces`` or
    the older top-level ``url``). Preserve its path and query; never guess from the
    discovery URL. Every check below applies to the chosen endpoint.
    The resolver and HTTP policy are shared with discovery-address validation.

    Raises:
        CardError: If a required field is missing or a value is unusable.
        UnsafeURLError: If the advertised endpoint is not a safe public URL.
    """
    if not isinstance(raw, dict):
        raise CardError("The agent card must be a JSON object.")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CardError("The agent card has no name.")
    name = clean_text(name)
    if not name:
        raise CardError("The agent card has no name.")
    if len(name) > MAX_NAME_LENGTH:
        raise CardError(f"The agent name is longer than {MAX_NAME_LENGTH} characters.")

    description = raw.get("description") or ""
    if not isinstance(description, str):
        raise CardError("The agent description must be text.")
    description = clean_text(description)
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise CardError(
            f"The agent description is longer than {MAX_DESCRIPTION_LENGTH} characters."
        )

    skills = raw.get("skills", [])
    if not isinstance(skills, list) or len(skills) > MAX_SKILLS:
        raise CardError(f"Skills must be a list of at most {MAX_SKILLS} items.")
    skills = [_clean_skill(skill) for skill in skills]
    capabilities = raw.get("capabilities", {})
    if not isinstance(capabilities, dict):
        raise CardError("Capabilities must be an object.")

    endpoint_url = select_endpoint(raw)
    # Reject ambiguous URL text before different URL parsers can reinterpret it.
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in endpoint_url):
        raise CardError("The endpoint url must not contain whitespace or controls.")
    if "\\" in endpoint_url or "#" in endpoint_url:
        raise CardError("The endpoint url must not contain backslashes or fragments.")
    if len(card_url) > MAX_URL_LENGTH or len(endpoint_url) > MAX_URL_LENGTH:
        raise CardError(f"URLs must be at most {MAX_URL_LENGTH} characters.")

    validate_agent_url(endpoint_url, allow_http=allow_http, resolver=resolver)

    flags = []
    searchable = " ".join([name, description, str(skills)])
    if looks_like_prompt_injection(searchable):
        flags.append("Card text looks like an attempt to steer Chris's routing.")

    return AgentCard(
        name=name,
        description=description,
        card_url=card_url,
        endpoint_url=endpoint_url,
        skills=skills,
        capabilities=capabilities,
        flags=flags,
    )


def _check_cancelled(deadline: float, stop: threading.Event) -> None:
    """Avoid starting another step after the caller has stopped waiting."""
    if stop.is_set() or time.monotonic() > deadline:
        raise CardError(_TIMEOUT_MESSAGE)


def _download(
    http: httpx.Client, card_url: str, deadline: float, stop: threading.Event
) -> bytes:
    """Stream the card body, enforcing size, encoding and the cooperative deadline."""
    # Ask for an uncompressed body and count the bytes on the wire, so a small
    # compressed response cannot expand into a large one in memory.
    _check_cancelled(deadline, stop)
    with http.stream(
        "GET", card_url, headers={"Accept-Encoding": "identity"}
    ) as response:
        _check_cancelled(deadline, stop)
        if response.is_redirect:
            raise CardError("The agent card address redirected; use the final URL.")
        if response.status_code != 200:
            raise CardError(
                f"The agent card request returned HTTP {response.status_code}."
            )
        encoding = response.headers.get("content-encoding", "identity")
        if encoding.strip().lower() not in ("", "identity"):
            raise CardError("The agent card must not be compressed.")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_CARD_BYTES:
            raise CardError("The agent card is too large.")
        body = bytearray()
        for chunk in response.iter_raw():
            body.extend(chunk)
            if len(body) > MAX_CARD_BYTES:
                raise CardError("The agent card is too large.")
            _check_cancelled(deadline, stop)
    return bytes(body)


def _fetch_blocking(
    http: httpx.Client,
    url: str,
    allow_http: bool,
    resolver: Resolver | None,
    deadline: float,
    stop: threading.Event,
) -> AgentCard:
    """Every step of a fetch, in order. Runs on a worker thread under a deadline."""
    _check_cancelled(deadline, stop)
    card_url = derive_card_url(url)
    validate_agent_url(card_url, allow_http=allow_http, resolver=resolver)
    try:
        body = _download(http, card_url, deadline, stop)
    except httpx.HTTPError as exc:
        log.info("Card fetch failed for %s: %s", card_url, type(exc).__name__)
        raise CardError(
            f"Could not reach the agent card ({type(exc).__name__})."
        ) from exc
    _check_cancelled(deadline, stop)
    try:
        raw = json.loads(body)
    except (ValueError, RecursionError) as exc:
        # ValueError covers bad JSON/encoding; RecursionError is deeply nested JSON.
        raise CardError("The agent card is not valid JSON.") from exc
    # Also validates the advertised endpoint, which does its own DNS lookup.
    _check_cancelled(deadline, stop)
    return parse_card(raw, card_url, allow_http=allow_http, resolver=resolver)


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
        client: Optional preconfigured client, used by tests. It belongs to the
            caller and is never closed here.
        resolver: Optional DNS resolver, used by tests to avoid real lookups.

    The whole job (DNS lookups, connecting, downloading, validation) runs on a
    worker thread and this function stops waiting after ``CARD_TIMEOUT_SECONDS``,
    so the caller's deadline holds even if a DNS lookup or socket operation is
    stuck. Python cannot kill a thread, so an abandoned worker ends on its own:
    when its next socket operation times out (``CARD_STEP_TIMEOUT_SECONDS``), when
    it next checks the deadline, or when the operating system's DNS lookup gives
    up. It holds no database session and cannot affect the response. At most eight
    workers run per process; timed-out workers retain capacity through cleanup.
    When all slots are occupied, new calls fail immediately without starting work.

    Raises:
        UnsafeURLError: The address is not safe to fetch.
        CardError: The card could not be fetched, was too large, or is invalid.
    """
    slots = _fetch_slots
    if not slots.acquire(blocking=False):
        raise CardError("Agent card fetch capacity is exhausted. Please try again later.")
    deadline = time.monotonic() + CARD_TIMEOUT_SECONDS
    stop = threading.Event()
    outcome: list[tuple[bool, Any]] = []
    finished = threading.Event()

    def work() -> None:
        http = client
        try:
            if http is None:
                http = httpx.Client(
                    timeout=httpx.Timeout(
                        CARD_STEP_TIMEOUT_SECONDS, connect=CARD_CONNECT_TIMEOUT_SECONDS
                    ),
                    follow_redirects=False,
                )
            outcome.append(
                (
                    True,
                    _fetch_blocking(http, url, allow_http, resolver, deadline, stop),
                )
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            outcome.append((False, exc))
        finally:
            try:
                if client is None and http is not None:
                    http.close()
            except BaseException as exc:  # noqa: BLE001 - re-raised on caller's thread
                outcome[:] = [(False, exc)]
            finally:
                slots.release()
                finished.set()

    try:
        threading.Thread(target=work, name="registry-card-fetch", daemon=True).start()
    except BaseException:
        slots.release()
        raise
    if not finished.wait(max(0, deadline - time.monotonic())):
        stop.set()
        raise CardError(_TIMEOUT_MESSAGE)
    succeeded, value = outcome[0]
    if not succeeded:
        raise value
    return value
