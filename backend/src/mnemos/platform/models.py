"""The single import surface for `Base.metadata`.

Alembic compares the live database against `Base.metadata`. A model module that
nothing imports contributes no tables to that comparison, and autogenerate will
cheerfully emit a migration that *drops* them. Importing every model here — and
having `migrations/env.py` import only this — makes that failure impossible.

`__all__` is what keeps the linter from removing the imports as unused.
"""

from __future__ import annotations

from mnemos.features.chat.adapters.models import (
    Bookmark,
    ChatMessage,
    ChatSession,
    Feedback,
    Folder,
    MessageCitation,
)
from mnemos.features.connectors.adapters.models import ContentSource
from mnemos.features.context.adapters.models import BundleItem, ContextBundle, ContextPlan
from mnemos.features.datasources.adapters.models import (
    GlossaryTerm,
    SqlDatasource,
    SqlRun,
    SqlSchemaObject,
)
from mnemos.features.identity.adapters.models import (
    ApiKey,
    AppUser,
    IdentityProvider,
    Org,
    Role,
    RoleBinding,
    Session,
    Tag,
    UserTag,
)
from mnemos.features.knowledge.adapters.models import (
    Chunk,
    ChunkEmbedding,
    Collection,
    Document,
    IngestJob,
    IngestJobEvent,
)
from mnemos.features.memory.adapters.models import (
    Memory,
    MemoryEdge,
    MemoryEmbedding,
    Subject,
)
from mnemos.features.observability.adapters.models import AuditLog, InferenceCall
from mnemos.features.prompts.adapters.models import Prompt, PromptVersion
from mnemos.features.tools.adapters.models import (
    McpCredential,
    McpGrant,
    McpInvocation,
    McpServer,
    McpTool,
)
from mnemos.platform.db import Base

# Every org-scoped table, in the order tenant isolation should be reasoned about.
# The RLS migration iterates this list, so adding a table to `Base.metadata`
# without adding it here is caught by `test_every_org_scoped_table_has_rls`.
ORG_SCOPED_TABLES: tuple[str, ...] = (
    "app_user",
    "identity_provider",
    "role",
    "role_binding",
    "tag",
    "user_tag",
    "api_key",
    "session",
    "subject",
    "memory",
    "memory_edge",
    "memory_embedding",
    "collection",
    "document",
    "chunk",
    "chunk_embedding",
    "ingest_job",
    "ingest_job_event",
    "content_source",
    "folder",
    "chat_session",
    "chat_message",
    "message_citation",
    "bookmark",
    "feedback",
    "context_plan",
    "context_bundle",
    "bundle_item",
    "sql_datasource",
    "sql_schema_object",
    "glossary_term",
    "sql_run",
    "mcp_server",
    "mcp_tool",
    "mcp_credential",
    "mcp_grant",
    "mcp_invocation",
    "prompt",
    "prompt_version",
    "inference_call",
    "audit_log",
)

__all__ = [
    "ORG_SCOPED_TABLES",
    "ApiKey",
    "AppUser",
    "AuditLog",
    "Base",
    "Bookmark",
    "BundleItem",
    "ChatMessage",
    "ChatSession",
    "Chunk",
    "ChunkEmbedding",
    "Collection",
    "ContentSource",
    "ContextBundle",
    "ContextPlan",
    "Document",
    "Feedback",
    "Folder",
    "GlossaryTerm",
    "IdentityProvider",
    "InferenceCall",
    "IngestJob",
    "IngestJobEvent",
    "McpCredential",
    "McpGrant",
    "McpInvocation",
    "McpServer",
    "McpTool",
    "Memory",
    "MemoryEdge",
    "MemoryEmbedding",
    "MessageCitation",
    "Org",
    "Prompt",
    "PromptVersion",
    "Role",
    "RoleBinding",
    "Session",
    "SqlDatasource",
    "SqlRun",
    "SqlSchemaObject",
    "Subject",
    "Tag",
    "UserTag",
]
