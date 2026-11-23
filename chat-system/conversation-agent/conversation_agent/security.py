"""Safe-URL checks for the expert endpoint the agent is about to call.

The Agent Registry returns the endpoint of the expert it selects, and the agent then
sends the user's question there. A registered URL that pointed at an internal service
or the cloud metadata endpoint would turn that call into a request the agent's server
makes on the registrant's behalf (SSRF). ``validate_agent_url`` rejects those targets
at dispatch, whatever the registry checked when the expert registered.

These are the registry's own registration checks, kept here as the agent's copy so
that the agent needs no code from another system. Only public HTTPS is accepted.

Limitation: the host is resolved here and again when the request is made, so a
hostile DNS server could answer differently the second time (DNS rebinding).
Closing that needs connecting to the validated IP, or an egress proxy.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})


class UnsafeURLError(ValueError):
    """Raised when a URL must not be called."""


def default_resolver(host: str) -> list[str]:
    """Resolve ``host`` to every IP address it points at."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Host could not be resolved: {host}") from exc
    return sorted({str(info[4][0]) for info in infos})


def _check_ip(raw: str, host: str) -> None:
    """Reject loopback, private, link-local, multicast, reserved and non-global IPs."""
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError as exc:
        raise UnsafeURLError(f"Invalid address for host {host}: {raw}") from exc
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        raise UnsafeURLError(f"Host {host} resolves to a non-public address ({ip}).")


def validate_agent_url(url: str) -> str:
    """Return ``url`` unchanged if it is safe to call, otherwise raise.

    Rejects a non-https scheme, a missing host, embedded credentials, blocked
    hostnames, and any host that resolves to a non-public address. Names are
    resolved with ``default_resolver``, which tests replace to avoid real DNS.

    Raises:
        UnsafeURLError: If the URL must not be called.
    """
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError as exc:
        raise UnsafeURLError(f"Malformed URL: {exc}") from exc

    if parts.scheme != "https":
        raise UnsafeURLError("URL scheme must be https.")
    if not host:
        raise UnsafeURLError("URL has no host.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("URL must not contain credentials.")

    lowered = host.lower().rstrip(".")
    if lowered in BLOCKED_HOSTNAMES or lowered.endswith(".localhost"):
        raise UnsafeURLError(f"Host {host} is not allowed.")

    try:
        ipaddress.ip_address(lowered)
        addresses = [lowered]
    except ValueError:
        addresses = default_resolver(lowered)
    if not addresses:
        raise UnsafeURLError(f"Host {host} did not resolve.")
    for address in addresses:
        _check_ip(address, host)
    return url
