"""The safe-URL check: which addresses the hub refuses to fetch."""

import pytest

from app.registry.security import UnsafeURLError, validate_agent_url

PUBLIC = ["93.184.216.34"]


def resolve_to(*addresses: str):
    """Return a resolver that always answers with ``addresses``."""
    return lambda host: list(addresses)


def test_public_https_host_is_allowed() -> None:
    url = "https://agent.example.test/.well-known/agent.json"
    assert validate_agent_url(url, resolver=resolve_to(*PUBLIC)) == url


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.10",
        "169.254.169.254",  # cloud metadata endpoint
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "::ffff:127.0.0.1",  # IPv4 loopback written as IPv6
    ],
)
def test_non_public_ip_literals_are_rejected(address: str) -> None:
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(UnsafeURLError):
        validate_agent_url(f"https://{host}/")


@pytest.mark.parametrize(
    "host",
    ["localhost", "LOCALHOST.", "api.localhost", "metadata.google.internal"],
)
def test_blocked_hostnames_are_rejected(host: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_agent_url(f"https://{host}/", resolver=resolve_to(*PUBLIC))


def test_hostname_resolving_to_a_private_address_is_rejected() -> None:
    with pytest.raises(UnsafeURLError, match="non-public"):
        validate_agent_url(
            "https://evil.example.test/", resolver=resolve_to("10.1.2.3")
        )


def test_one_private_address_among_public_ones_rejects_the_host() -> None:
    with pytest.raises(UnsafeURLError):
        validate_agent_url(
            "https://mixed.example.test/", resolver=resolve_to(*PUBLIC, "192.168.0.9")
        )


def test_unresolvable_host_is_rejected() -> None:
    with pytest.raises(UnsafeURLError, match="did not resolve"):
        validate_agent_url("https://nothing.example.test/", resolver=resolve_to())


def test_plain_http_is_rejected_by_default() -> None:
    with pytest.raises(UnsafeURLError, match="https"):
        validate_agent_url("http://agent.example.test/", resolver=resolve_to(*PUBLIC))


def test_plain_http_is_allowed_only_when_enabled() -> None:
    url = "http://agent.example.test/"
    assert validate_agent_url(url, allow_http=True, resolver=resolve_to(*PUBLIC)) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@agent.example.test/",
        "ftp://agent.example.test/",
        "https:///no-host",
        "https://agent.example.test:notaport/",
    ],
)
def test_malformed_or_credentialed_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_agent_url(url, resolver=resolve_to(*PUBLIC))
