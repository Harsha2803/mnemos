"""`ssrf_guard.resolve_and_pin` — ThreatModel.md §3⑥'s deny-list, proved by
actually refusing a loopback/link-local/metadata URL, not merely by asserting
the deny-list function exists.

No real internet access needed: every case here resolves locally (loopback,
literal IPs) or is rejected before any DNS lookup happens at all (bad scheme,
embedded credentials).
"""

from __future__ import annotations

import pytest

from mnemos.core.errors import SsrfRejectedError, ValidationError
from mnemos.features.connectors.adapters.ssrf_guard import resolve_and_pin


async def test_refuses_a_loopback_ip_literal() -> None:
    with pytest.raises(SsrfRejectedError):
        await resolve_and_pin("http://127.0.0.1/secrets")


async def test_refuses_localhost_by_name() -> None:
    with pytest.raises(SsrfRejectedError):
        await resolve_and_pin("http://localhost/secrets")


async def test_refuses_a_link_local_cloud_metadata_address() -> None:
    with pytest.raises(SsrfRejectedError):
        await resolve_and_pin("http://169.254.169.254/latest/meta-data/")


async def test_refuses_a_private_range_ip_literal() -> None:
    with pytest.raises(SsrfRejectedError):
        await resolve_and_pin("http://10.0.0.5/internal")


async def test_refuses_ipv6_loopback() -> None:
    with pytest.raises(SsrfRejectedError):
        await resolve_and_pin("http://[::1]/secrets")


async def test_refuses_a_non_http_scheme() -> None:
    with pytest.raises(ValidationError):
        await resolve_and_pin("file:///etc/passwd")


async def test_refuses_embedded_credentials() -> None:
    """`http://user:pass@host` is a classic way to smuggle a second,
    differently-parsed hostname past a naive check — refused outright rather
    than trusted to parse the same way everywhere it is read."""
    with pytest.raises(ValidationError):
        await resolve_and_pin("http://user:pass@example.com/x")


async def test_pins_to_the_checked_address_and_keeps_the_original_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public-looking host is allowed through, and the returned URL is
    pinned to the address that was actually validated, with the original
    hostname preserved for the `Host` header/SNI — the DNS re-resolution
    guard against rebinding, not just a one-time check."""
    from mnemos.features.connectors.adapters import ssrf_guard

    def fake_resolve_sync(host: str, port: int) -> set[str]:
        assert host == "docs.example.com"
        return {"93.184.216.34"}

    monkeypatch.setattr(ssrf_guard, "_resolve_sync", fake_resolve_sync)

    pinned_url, original_host = await resolve_and_pin("https://docs.example.com/report.pdf")

    assert original_host == "docs.example.com"
    assert pinned_url.host == "93.184.216.34"
    assert pinned_url.path == "/report.pdf"
