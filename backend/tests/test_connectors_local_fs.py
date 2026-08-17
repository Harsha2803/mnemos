"""`LocalFsConnector` — browses and fetches only inside its configured root.

The traversal tests are the point of this file: `test_register_rejects_an_
empty_allowlist`'s discipline is "an empty allowlist means no schemas", and
this connector's analogue is "outside the root means refused", proved by
actually attempting an escape rather than asserting the check exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mnemos.core.errors import NotFoundError, ValidationError
from mnemos.features.connectors.adapters.local_fs import LocalFsConnector


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "policy.txt").write_text("hello policy")
    (tmp_path / "docs" / "nested").mkdir()
    (tmp_path / "docs" / "nested" / "deep.txt").write_text("hello deep")
    (tmp_path / "outside.txt").write_text("must never be reachable")
    return tmp_path / "docs"


async def test_list_items_finds_files_recursively_with_relative_uris(root: Path) -> None:
    connector = LocalFsConnector(root=str(root))

    items = await connector.list_items()

    uris = {item.uri for item in items}
    assert uris == {"policy.txt", "nested/deep.txt"}


async def test_fetch_reads_a_file_inside_the_root(root: Path) -> None:
    connector = LocalFsConnector(root=str(root))

    data = await connector.fetch("policy.txt")

    assert data == b"hello policy"


async def test_fetch_refuses_dot_dot_traversal_out_of_the_root(root: Path) -> None:
    connector = LocalFsConnector(root=str(root))

    with pytest.raises(ValidationError):
        await connector.fetch("../outside.txt")


async def test_fetch_refuses_an_absolute_path(root: Path) -> None:
    """`Path(root) / "/etc/passwd"` would otherwise silently become
    `Path("/etc/passwd")` — pathlib's `/` replaces the left side when the
    right side is absolute, so this has to be caught before any join."""
    connector = LocalFsConnector(root=str(root))

    with pytest.raises(ValidationError):
        await connector.fetch("/etc/passwd")


async def test_fetch_refuses_a_symlink_that_resolves_outside_the_root(root: Path) -> None:
    escape = root / "escape.txt"
    escape.symlink_to(root.parent / "outside.txt")

    connector = LocalFsConnector(root=str(root))

    with pytest.raises(ValidationError):
        await connector.fetch("escape.txt")


async def test_fetch_raises_not_found_for_a_missing_file(root: Path) -> None:
    connector = LocalFsConnector(root=str(root))

    with pytest.raises(NotFoundError):
        await connector.fetch("nope.txt")
