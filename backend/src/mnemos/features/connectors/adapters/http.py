"""`SourceConnector` over an operator-curated list of HTTP(S) URLs.

**Never crawls, never fetches a URL it was not configured with.** `list_items`
enumerates exactly the configured URLs — it does not follow links out of any
of them — and `fetch` only ever accepts a `uri` that is one of those same
configured URLs. Every request goes through `ssrf_guard.resolve_and_pin`
first, and a redirect response is treated as a failure rather than followed:
a connector that transparently followed redirects would let an
operator-approved URL forward to an internal address the deny-list would
otherwise catch.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx

from mnemos.core.errors import UpstreamError, ValidationError
from mnemos.features.connectors.adapters.ssrf_guard import resolve_and_pin
from mnemos.features.connectors.domain import SourceItem

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class HttpConnector:
    def __init__(self, *, urls: Sequence[str], client: httpx.AsyncClient) -> None:
        self._urls = list(urls)
        self._client = client

    async def list_items(self) -> Sequence[SourceItem]:
        """No network I/O — just the operator-configured list. Fetching
        metadata for every configured URL on every listing would itself be a
        network round trip this connector has no business making unprompted;
        size and content-type are learned when an item is actually fetched."""
        items = []
        for url in self._urls:
            name = urlsplit(url).path.rsplit("/", 1)[-1] or url
            items.append(
                SourceItem(
                    uri=url,
                    name=name,
                    size_bytes=0,
                    content_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                    modified_at=None,
                )
            )
        return items

    async def fetch(self, uri: str) -> bytes:
        if uri not in self._urls:
            raise ValidationError("uri is not one of this connector's configured URLs", uri=uri)

        pinned_url, original_host = await resolve_and_pin(uri)
        try:
            response = await self._client.get(
                pinned_url,
                headers={"Host": original_host},
                extensions={"sni_hostname": original_host},
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"fetching {uri!r} failed", reason=str(exc)) from exc

        if response.status_code in _REDIRECT_STATUSES:
            raise UpstreamError(
                "the http connector does not follow redirects",
                uri=uri,
                status_code=response.status_code,
            )
        if response.is_error:
            raise UpstreamError(
                f"fetching {uri!r} returned {response.status_code}",
                uri=uri,
                status_code=response.status_code,
            )
        return response.content
