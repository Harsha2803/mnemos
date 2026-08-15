"""`DatasourceService`: register a warehouse and refresh what Mnemos knows
about its schema.

Registration and refresh are both explicit actions (`mnemosctl datasource
introspect`), never implicit work on the query path — TRACKER §5 deliverable 1
is explicit that refresh is "not a per-query cost". Execution and generation
(deliverables 3-4) read the cache this writes; they never introspect on demand.
"""

from __future__ import annotations

from mnemos.core.crypto import DsnCipher
from mnemos.core.logging import get_logger
from mnemos.features.datasources.application.ports import (
    DatasourceRecord,
    DatasourceRepository,
    GlossaryRepository,
    SchemaIntrospector,
    SchemaObjectRepository,
)
from mnemos.features.datasources.domain import (
    GlossaryTermRow,
    build_schema_objects,
    render_schema_context,
)
from mnemos.features.identity.domain import OrgId

log = get_logger(__name__)


class DatasourceService:
    def __init__(
        self,
        *,
        datasources: DatasourceRepository,
        schema_objects: SchemaObjectRepository,
        introspector: SchemaIntrospector,
        cipher: DsnCipher,
        glossary: GlossaryRepository,
    ) -> None:
        self._datasources = datasources
        self._schema_objects = schema_objects
        self._introspector = introspector
        self._cipher = cipher
        self._glossary = glossary

    async def register(
        self,
        *,
        org_id: OrgId,
        slug: str,
        name: str,
        description: str,
        dsn: str,
        read_only_role: str,
        allowed_schemas: list[str],
    ) -> DatasourceRecord:
        """Idempotent: a second call with the same slug changes nothing that
        exists, matching `mnemosctl bootstrap`'s own idempotence."""
        if not allowed_schemas:
            # The allowlist's default must be deny (adapters/models.py's own
            # docstring) — an empty list would mean "every schema" the moment
            # a query path forgets to check for emptiness, not "no schemas".
            raise ValueError("allowed_schemas must not be empty")
        return await self._datasources.ensure_datasource(
            org_id=org_id,
            slug=slug,
            name=name,
            description=description,
            dsn_encrypted=self._cipher.encrypt(dsn),
            read_only_role=read_only_role,
            allowed_schemas=allowed_schemas,
        )

    async def _require_datasource(self, *, org_id: OrgId, slug: str) -> DatasourceRecord:
        datasource = await self._datasources.get_by_slug(org_id=org_id, slug=slug)
        if datasource is None:
            raise LookupError(f"no datasource registered for org {org_id} with slug {slug!r}")
        return datasource

    async def refresh_schema(self, *, org_id: OrgId, slug: str) -> int:
        """Introspect the registered warehouse and replace its cached schema.

        Returns the number of `sql_schema_object` rows written, so the CLI has
        something concrete to print rather than a bare "done".
        """
        datasource = await self._require_datasource(org_id=org_id, slug=slug)

        dsn = self._cipher.decrypt(datasource.dsn_encrypted)
        tables, columns = await self._introspector.introspect(
            dsn=dsn, schemas=datasource.allowed_schemas
        )
        drafts = build_schema_objects(tables=tables, columns=columns)
        count = await self._schema_objects.replace_all(
            org_id=org_id, datasource_id=datasource.id, drafts=drafts
        )
        await self._datasources.mark_introspected(org_id=org_id, datasource_id=datasource.id)
        log.info(
            "datasources.schema_refreshed",
            org_id=str(org_id),
            datasource_slug=slug,
            tables=len(tables),
            columns=len(columns),
            rows_written=count,
        )
        return count

    async def seed_glossary(self, *, org_id: OrgId, slug: str, terms: list[GlossaryTermRow]) -> int:
        """Idempotent: a term already present (matched by its `term` text) is
        left untouched. Returns how many were newly written, mirroring
        `refresh_schema`'s "something concrete to print" reasoning."""
        datasource = await self._require_datasource(org_id=org_id, slug=slug)
        written = await self._glossary.ensure_terms(
            org_id=org_id, datasource_id=datasource.id, terms=terms
        )
        log.info(
            "datasources.glossary_seeded",
            org_id=str(org_id),
            datasource_slug=slug,
            terms_written=written,
        )
        return written

    async def render_context(self, *, org_id: OrgId, slug: str) -> str:
        """The schema-plus-glossary text block deliverable 3's prompt uses.
        Reads the caches deliverable 1 and `seed_glossary` write; introspects
        and seeds nothing itself."""
        datasource = await self._require_datasource(org_id=org_id, slug=slug)
        schema_objects = await self._schema_objects.list_all(
            org_id=org_id, datasource_id=datasource.id
        )
        glossary_terms = await self._glossary.list_terms(org_id=org_id, datasource_id=datasource.id)
        return render_schema_context(schema_objects=schema_objects, glossary_terms=glossary_terms)
