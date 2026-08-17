"""`HttpConnector` — fetches only a URL it was configured with, never
crawls, and never follows a redirect."""

from __future__ import annotations

import httpx
import pytest

from mnemos.core.errors import UpstreamError, ValidationError
from mnemos.features.connectors.adapters.http import HttpConnector

CONFIGURED_URLS = ["https://docs.example.com/report.pdf"]


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_list_items_never_makes_a_network_call() -> None:
    def blow_up(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("list_items must not touch the network")

    connector = HttpConnector(urls=CONFIGURED_URLS, client=_client(httpx.MockTransport(blow_up)))

    items = await connector.list_items()

    assert [item.uri for item in items] == CONFIGURED_URLS
    assert items[0].name == "report.pdf"


async def test_fetch_refuses_a_url_not_in_the_configured_list() -> None:
    connector = HttpConnector(
        urls=CONFIGURED_URLS, client=_client(httpx.MockTransport(lambda r: httpx.Response(200)))
    )

    with pytest.raises(ValidationError):
        await connector.fetch("https://not-configured.example.com/x.pdf")


async def test_fetch_refuses_to_follow_a_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect is a failure, not something followed — an operator-approved
    URL forwarding to an internal address must not silently work around the
    deny-list `resolve_and_pin` already applied to the approved URL."""
    from mnemos.features.connectors.adapters import http as http_module

    async def fake_pin(url: str) -> tuple[httpx.URL, str]:
        return httpx.URL(url), "docs.example.com"

    monkeypatch.setattr(http_module, "resolve_and_pin", fake_pin)

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    connector = HttpConnector(urls=CONFIGURED_URLS, client=_client(httpx.MockTransport(redirect)))

    with pytest.raises(UpstreamError):
        await connector.fetch(CONFIGURED_URLS[0])


async def test_fetch_returns_the_body_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from mnemos.features.connectors.adapters import http as http_module

    async def fake_pin(url: str) -> tuple[httpx.URL, str]:
        return httpx.URL(url), "docs.example.com"

    monkeypatch.setattr(http_module, "resolve_and_pin", fake_pin)

    def ok(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == "docs.example.com"
        return httpx.Response(200, content=b"%PDF-1.4 fake pdf bytes")

    connector = HttpConnector(urls=CONFIGURED_URLS, client=_client(httpx.MockTransport(ok)))

    data = await connector.fetch(CONFIGURED_URLS[0])

    assert data == b"%PDF-1.4 fake pdf bytes"
