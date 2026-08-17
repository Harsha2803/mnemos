"""Deriving a session's own name from its first message.

Every session starts out titled `DEFAULT_SESSION_TITLE` ("New chat"). All three
answer flows — plain chat (`ChatService`), RAG (`flows/rag`) and NL2SQL
(`flows/nl2sql`) — persist a user's first message through the same
`ChatRepository`, and each should replace that placeholder the same way, the
moment it happens, the way every other chat product names a conversation for
what it is about rather than leaving a user to name forty identical "New
chat" rows themselves. Living here once, rather than duplicated three times,
is what keeps a fourth flow from forgetting to call it.
"""

from __future__ import annotations

from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.domain import ChatSessionSummary
from mnemos.features.identity.domain import OrgId

DEFAULT_SESSION_TITLE = "New chat"

#: Long enough to be recognisable in a 260px sidebar row, short enough that a
#: skimmed list stays a list rather than wrapping onto a second line.
MAX_TITLE_LENGTH = 60


def derive_title(content: str) -> str:
    """Collapse the message to one line and cut it at a word boundary — a
    title cut mid-word reads as broken, not as a title."""
    collapsed = " ".join(content.split())
    if len(collapsed) <= MAX_TITLE_LENGTH:
        return collapsed
    truncated = collapsed[:MAX_TITLE_LENGTH]
    boundary = truncated.rfind(" ")
    if boundary > 0:
        truncated = truncated[:boundary]
    return truncated.rstrip() + "…"


async def title_session_from_first_message(
    *,
    repository: ChatRepository,
    org_id: OrgId,
    session: ChatSessionSummary,
    content: str,
) -> None:
    """Renames a session the first time it receives a message, and only
    then. `session` is a snapshot taken *before* the message being answered
    was appended, so `last_message_at` is still `None` on exactly the first
    call for a given session — a later message, or a title the user already
    picked by hand, leaves the session alone."""
    if session.title != DEFAULT_SESSION_TITLE or session.last_message_at is not None:
        return
    title = derive_title(content)
    if title:
        await repository.rename_session(org_id=org_id, session_id=session.id, title=title)
