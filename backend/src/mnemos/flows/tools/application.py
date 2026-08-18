"""Connect routed chat to exactly one registered MCP tool."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence

from mnemos.core.errors import NotFoundError
from mnemos.core.types import JsonValue, TrustTier
from mnemos.features.chat.application.ports import ChatRepository
from mnemos.features.chat.application.titles import title_session_from_first_message
from mnemos.features.chat.domain import AssistantDone, ChatSessionId, ChatStreamEvent
from mnemos.features.identity.application.principals import AuthenticatedCaller
from mnemos.features.identity.domain import OrgId
from mnemos.features.tools.application import ToolCatalogService, ToolInvocationService
from mnemos.features.tools.application.invocations import narrate_invocation
from mnemos.features.tools.domain import McpInvocationRecord, McpToolRecord

FLOW_NAME = "tool"


class ToolFlow:
    """Select and propose one tool; there is no loop or second call."""

    def __init__(
        self,
        *,
        chat_repository: ChatRepository,
        catalog: ToolCatalogService,
        invocations: ToolInvocationService,
    ) -> None:
        self._chat = chat_repository
        self._catalog = catalog
        self._invocations = invocations

    async def stream_reply(
        self,
        *,
        caller: AuthenticatedCaller,
        session_id: ChatSessionId,
        content: str,
        router_rationale: str | None = None,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        org_id = caller.principal.org_id
        session = await self._chat.get_session(org_id=org_id, session_id=session_id)
        if session is None or session.user_id != caller.principal.principal_id:
            raise NotFoundError(f"chat session {session_id} not found")
        await self._chat.append_user_message(org_id=org_id, session_id=session_id, content=content)
        await title_session_from_first_message(
            repository=self._chat, org_id=org_id, session=session, content=content
        )

        tools = await self._catalog.list_tools(org_id=org_id)
        tool = _select_one(tools, content)
        if tool is None:
            yield await self._finish(
                caller=caller,
                org_id=org_id,
                session_id=session_id,
                content="No enabled tool matches this request. Discover a tool in Tools first.",
                router_rationale=router_rationale,
                invocation=None,
            )
            return

        invocation = await self._invocations.propose(
            caller=caller,
            tool_id=tool.id,
            arguments=_arguments_for(tool.input_schema, content),
            motivating_tier=TrustTier.USER,
        )
        yield await self._finish(
            caller=caller,
            org_id=org_id,
            session_id=session_id,
            content=narrate_invocation(tool=tool, invocation=invocation),
            router_rationale=router_rationale,
            invocation=invocation,
        )

    async def _finish(
        self,
        *,
        caller: AuthenticatedCaller,
        org_id: OrgId,
        session_id: ChatSessionId,
        content: str,
        router_rationale: str | None,
        invocation: McpInvocationRecord | None,
    ) -> AssistantDone:
        message = await self._chat.append_assistant_message(
            org_id=org_id,
            session_id=session_id,
            content=content,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            model="mcp",
            finish_reason="stop",
            flow=FLOW_NAME,
            router_rationale=router_rationale,
        )
        if invocation is not None:
            invocation = await self._invocations.attach_message(
                caller=caller,
                invocation_id=invocation.id,
                message_id=message.id,
            )
        return AssistantDone(
            message=message,
            extra={"tool": _invocation_payload(invocation)} if invocation is not None else None,
        )


def _select_one(tools: Sequence[McpToolRecord], content: str) -> McpToolRecord | None:
    enabled = [tool for tool in tools if tool.is_enabled]
    normalized = content.casefold()
    named = [tool for tool in enabled if tool.name.casefold() in normalized]
    if len(named) == 1:
        return named[0]
    if not named and len(enabled) == 1:
        return enabled[0]
    return None


def _arguments_for(schema: Mapping[str, JsonValue], content: str) -> dict[str, JsonValue]:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list) or len(required) != 1:
        return {}
    name = required[0]
    if not isinstance(name, str):
        return {}
    property_schema = properties.get(name)
    if isinstance(property_schema, dict) and property_schema.get("type") == "string":
        return {name: content}
    return {}


def _invocation_payload(invocation: McpInvocationRecord | None) -> dict[str, JsonValue]:
    if invocation is None:
        return {}
    return {
        "id": str(invocation.id),
        "tool_id": str(invocation.tool_id),
        "status": invocation.status.value,
        "denied_reason": invocation.denied_reason,
        "offending_source": invocation.offending_source,
        "result": invocation.result,
        "error_code": invocation.error_code,
    }
