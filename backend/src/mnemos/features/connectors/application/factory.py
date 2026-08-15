"""Turn a registered `content_source` row into a live `SourceConnector`.

Decryption and dispatch live here, one level above the repository, so nothing
that only needs to browse or fetch (the worker, deliverable 4) has to know
`ContentSource.config_encrypted` exists — it asks the factory for a connector
and gets one.
"""

from __future__ import annotations

import json

import httpx

from mnemos.core.config import Settings
from mnemos.core.errors import ConfigurationError
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.http import HttpConnector
from mnemos.features.connectors.adapters.local_fs import LocalFsConnector
from mnemos.features.connectors.adapters.s3 import S3Connector
from mnemos.features.connectors.application.ports import ContentSourceRecord
from mnemos.features.connectors.domain import SourceConnector
from mnemos.platform.objectstore.s3 import S3ObjectStore


class ConnectorFactory:
    def __init__(
        self,
        *,
        settings: Settings,
        cipher: SourceConfigCipher,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._settings = settings
        self._cipher = cipher
        self._http_client = http_client

    def build(self, record: ContentSourceRecord) -> SourceConnector:
        config = json.loads(self._cipher.decrypt(record.config_encrypted))

        if record.kind in ("s3", "minio"):
            store = S3ObjectStore(
                endpoint_url=self._settings.object_endpoint,
                access_key=self._settings.object_access_key,
                secret_key=self._settings.object_secret_key.get_secret_value(),
                bucket=config["bucket"],
                region=self._settings.object_region,
            )
            return S3Connector(store=store, prefix=config.get("prefix", ""))

        if record.kind == "local_fs":
            return LocalFsConnector(root=config["root"])

        if record.kind == "http":
            return HttpConnector(urls=config["urls"], client=self._http_client)

        raise ConfigurationError(f"unknown connector kind {record.kind!r}")
