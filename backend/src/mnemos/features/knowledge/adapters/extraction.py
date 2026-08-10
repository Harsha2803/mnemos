"""Text extraction, off the event loop.

Ported from `_v1/ingest.py`'s `extract_pdf`. Extraction is CPU-bound — a large
PDF can take real wall-clock time to parse — so it runs on a thread
(CodingStandards §3), the same argument `PasswordHasher` makes for argon2id
and `OllamaChatModel` does not need to make because its cost is all network
I/O.

An unsupported media type is a `ValidationError` naming the type, never a
silently empty document (TRACKER §5 deliverable 2).
"""

from __future__ import annotations

import io

import anyio

from mnemos.core.errors import ValidationError

SUPPORTED_MEDIA_TYPES = frozenset({"text/plain", "text/markdown", "application/pdf"})


async def extract_pages(data: bytes, media_type: str) -> list[tuple[int | None, str]]:
    """`[(page_number, text)]` — `page_number` is `None` for non-paginated
    media, so a citation can tell "this came from page 3" from "this document
    has no pages" instead of guessing page 1 for both."""
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise ValidationError(f"unsupported media type {media_type!r}", field="media_type")
    if media_type == "application/pdf":
        return await anyio.to_thread.run_sync(_extract_pdf_sync, data)
    return [(None, data.decode("utf-8", errors="replace"))]


def _extract_pdf_sync(data: bytes) -> list[tuple[int | None, str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    out: list[tuple[int | None, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            out.append((i, text))
    return out
