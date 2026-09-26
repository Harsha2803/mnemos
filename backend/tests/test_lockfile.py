"""Every dependency declared in pyproject.toml is pinned in the lockfiles.

The image, CI and `make install` install from `requirements.lock` /
`requirements-dev.lock` with `--require-hashes`, then install this package with
`--no-deps`. A dependency added to pyproject.toml without re-running `make lock`
would therefore be missing at runtime, and would surface as an ImportError far from
its cause. This test names the cause instead.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _name(requirement: str) -> str:
    """The PEP 503 normalized project name of a requirement string."""
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    assert match is not None, requirement
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _pinned(lockfile: str) -> set[str]:
    text = (BACKEND / lockfile).read_text(encoding="utf-8")
    return {_name(line) for line in re.findall(r"^([A-Za-z0-9][^=\s]*)==", text, re.M)}


def _declared() -> tuple[list[str], list[str]]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return project["dependencies"], project["optional-dependencies"]["dev"]


def test_every_runtime_dependency_is_locked() -> None:
    runtime, _ = _declared()
    missing = sorted({_name(r) for r in runtime} - _pinned("requirements.lock"))
    assert missing == [], f"declared but not locked: {missing}; run `make lock`"


def test_every_dev_dependency_is_locked() -> None:
    runtime, dev = _declared()
    missing = sorted({_name(r) for r in [*runtime, *dev]} - _pinned("requirements-dev.lock"))
    assert missing == [], f"declared but not locked: {missing}; run `make lock`"


def test_every_pin_carries_a_hash() -> None:
    for lockfile in ("requirements.lock", "requirements-dev.lock"):
        text = (BACKEND / lockfile).read_text(encoding="utf-8")
        entries = re.split(r"\n(?=[A-Za-z0-9])", text.split("\n", 2)[2])
        unhashed = [entry.split()[0] for entry in entries if "--hash=sha256:" not in entry]
        assert unhashed == [], f"{lockfile}: {unhashed}"
