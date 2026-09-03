"""
The software bill of materials, for the EU Cyber Resilience Act.

Regulation (EU) 2024/2847 applies to products with digital elements sold in
the EU — vulnerability-reporting obligations begin 11 September 2026, full
application 11 December 2027. An SBOM is most of the paperwork half of that:
a machine-readable list of exactly what a build ships, so a newly disclosed
vulnerability in a dependency can be checked against what actually went out
rather than against memory of what requirements.lock said at some point.

`cyclonedx-py` is not imported by the app and does not ship in a build — a
CI job (.github/workflows/ci.yml, the sbom job) runs it over
requirements.lock on every push and publishes the result as a build
artifact. It is a development-only tool the same way pip-audit is, so the
same pattern as tests/test_qrcode.py applies here: install it via the `dev`
extra to get real coverage, skip without it rather than fail. What is
checked either way is not "cyclonedx-py works" — that is the tool's own
test suite's job — it is that pointing it at requirements.lock in exactly
the way CI does produces an SBOM that actually lists this project's pinned
dependencies, at the versions actually pinned. A generator that silently
produced an empty or stale SBOM would be worse than no SBOM: it would look
like compliance while not being any.
"""

import json
import os
import re
import subprocess
import sys

import pytest

from core.version import APP_NAME, __version__
from tests.conftest import REPO_ROOT

try:
    import cyclonedx_py as _cyclonedx_py
except ImportError:                     # pragma: no cover - depends on the box
    _cyclonedx_py = None

needs_cyclonedx = pytest.mark.skipif(
    _cyclonedx_py is None,
    reason="cyclonedx-bom is not installed; install the dev extras",
)

_LOCK_PATH = os.path.join(REPO_ROOT, "requirements.lock")
_PYPROJECT_PATH = os.path.join(REPO_ROOT, "pyproject.toml")

# "name==version" at the start of a pip-compile line, hashes and the trailing
# "# via ..." comment stripped off by not matching past the version.
_LOCK_LINE_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)")


def _pinned_dependencies() -> dict:
    """{name.lower(): version} for every package requirements.lock pins."""
    pinned = {}
    with open(_LOCK_PATH, encoding="utf-8") as fh:
        for line in fh:
            match = _LOCK_LINE_RE.match(line)
            if match:
                pinned[match.group(1).lower()] = match.group(2)
    return pinned


@pytest.fixture(scope="module")
def sbom(tmp_path_factory) -> dict:
    """
    The SBOM cyclonedx-py produces from requirements.lock right now, parsed.

    Module-scoped and generated once: this shells out to a real subprocess,
    and every test below asks a different question of the same output rather
    than needing its own copy of it.
    """
    out = tmp_path_factory.mktemp("sbom") / "sbom.cdx.json"
    result = subprocess.run(
        [sys.executable, "-m", "cyclonedx_py", "requirements", _LOCK_PATH,
         "--pyproject", _PYPROJECT_PATH, "-o", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"cyclonedx-py exited {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


class TestTheSBOMDescribesTheRealLockfile:

    @needs_cyclonedx
    def test_it_is_a_cyclonedx_document(self, sbom):
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"]

    @needs_cyclonedx
    def test_the_root_component_is_this_project(self, sbom):
        root = sbom["metadata"]["component"]
        assert root["name"] == APP_NAME.lower()
        assert root["version"] == __version__

    @needs_cyclonedx
    def test_every_pinned_dependency_is_listed_at_its_pinned_version(self, sbom):
        pinned = _pinned_dependencies()
        assert pinned, "requirements.lock did not parse to any pins — fix the test regex"

        listed = {c["name"].lower(): c["version"] for c in sbom["components"]}
        for name, version in pinned.items():
            assert name in listed, f"{name} is pinned in requirements.lock but missing from the SBOM"
            assert listed[name] == version, (
                f"{name} is pinned to {version} but the SBOM says {listed[name]}"
            )

    @needs_cyclonedx
    def test_the_sbom_lists_nothing_beyond_what_is_pinned(self, sbom):
        # The other direction from the test above: a component in the SBOM
        # that is not in requirements.lock means the generator pointed
        # somewhere other than the file CI actually pins.
        pinned = _pinned_dependencies()
        listed = {c["name"].lower() for c in sbom["components"]}
        assert listed == set(pinned), listed ^ set(pinned)

    @needs_cyclonedx
    def test_every_component_has_a_package_url(self, sbom):
        # The identifier a vulnerability database is actually looked up by.
        for component in sbom["components"]:
            assert component.get("purl", "").startswith("pkg:pypi/"), component

    def test_the_lockfile_parser_itself_is_not_fooled_by_comments(self):
        # Runs unconditionally — no cyclonedx-py needed to check the regex
        # this file's own fixture depends on against the real lockfile.
        pinned = _pinned_dependencies()
        assert pinned == {"plyer": "2.1.0", "psutil": "7.2.2"}, (
            "requirements.lock's pins changed shape — update this alongside "
            "whatever changed it, the same as THIRD_PARTY_NOTICES.md"
        )
