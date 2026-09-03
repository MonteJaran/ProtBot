"""
sbom.py - A CycloneDX bill of materials for a ProtBot build.

    python packaging/sbom.py                 # writes dist/protbot-<version>.cdx.json
    python packaging/sbom.py --output x.json
    python packaging/sbom.py --check         # verify without writing anything

## Why this exists

Regulation (EU) 2024/2847 — the Cyber Resilience Act — applies to products
with digital elements made available in the EU. Annex I Part II requires the
manufacturer to "identify and document vulnerabilities and components
contained in products with digital elements, including by drawing up a
software bill of materials in a commonly used and machine-readable format
covering at the very least the top-level dependencies of the products."

The dates that matter: the vulnerability-reporting obligations begin on
**11 September 2026**, and the regulation applies in full from
**11 December 2027**.

Most of the surrounding obligation is already met — `SECURITY.md` is the
vulnerability disclosure policy, `pip-audit` runs in CI against the lockfile,
and dependencies are pinned by exact version and SHA-256 hash. The bill of
materials was the missing piece, and it is the one an authority asks for by
name.

## Why it is written here rather than shelling out to cyclonedx-py

Three reasons, in order of how much they mattered:

  * **The lockfile is the truth, and it already holds the hashes.** A build
    installs `requirements.lock` with `--require-hashes`, so those hashes are
    what actually ends up in the binary. Reading them straight out of the file
    the build uses means the SBOM cannot describe a different set of packages
    from the one that shipped. A tool that introspects an installed
    environment describes whatever happens to be installed on the build
    machine.

  * **A release build should not need the network or an extra toolchain.**
    `packaging/build.ps1` runs on a machine that has Python and PyInstaller.
    Adding a build-time dependency to produce a compliance document is a way
    for the document to stop being produced.

  * **It is small.** CycloneDX is a JSON schema; the part of it that describes
    a Python application with two dependencies is what you see below.

## What it deliberately does not do

It does not resolve transitive dependencies, because `requirements.lock` is
already fully resolved — pip-compile wrote every package that gets installed,
transitive ones included, which is exactly the set the CRA asks about. If the
lockfile is ever generated some other way, this stops being true and this
comment is the thing to come back to.

It does not invent licence metadata. A dependency's licence lives in
`THIRD_PARTY_NOTICES.md`, which is checked against the lockfile by a test, and
guessing here would produce a compliance document with a guess in it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from core.version import APP_NAME, __version__          # noqa: E402

LOCKFILE = os.path.join(REPO_ROOT, "requirements.lock")

# CycloneDX 1.5. Not the newest — 1.6 exists — but it is the version every
# consumer in the chain (GitHub dependency review, OWASP Dependency-Track,
# the common scanners) reads without a shim, and nothing here needs a field
# 1.6 added.
SPEC_VERSION = "1.5"
BOM_FORMAT = "CycloneDX"

# "name==version \" starting a requirement block in a pip-compile lockfile.
_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def parse_lockfile(text: str) -> list[dict]:
    """
    The packages a build installs, as {name, version, hashes}.

    Parsed rather than imported: this has to describe what the *build*
    installs, which is the lockfile, not what happens to be importable on the
    machine generating the document.

    Comment lines are dropped first. pip-compile writes `# via protbot
    (pyproject.toml)` under each entry, and a `# --hash=...` inside a comment
    would otherwise be read as a real hash.
    """
    packages: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        match = _REQUIREMENT_RE.match(line)
        if match:
            current = {
                "name": match.group(1),
                "version": match.group(2),
                "hashes": [],
            }
            packages.append(current)

        if current is not None:
            current["hashes"].extend(_HASH_RE.findall(line))

    for package in packages:
        # Deterministic output: a document that reorders between runs cannot
        # be diffed, and diffing two SBOMs is most of what they are for.
        package["hashes"] = sorted(set(package["hashes"]))

    packages.sort(key=lambda p: p["name"].lower())
    return packages


def _purl(name: str, version: str) -> str:
    """
    A package URL, which is how every SBOM consumer joins this to an advisory.

    Normalised per PEP 503 — the pypi purl type is defined in terms of the
    normalised name, and "Foo.Bar" and "foo-bar" are one package on PyPI.
    """
    normalised = re.sub(r"[-_.]+", "-", name).lower()
    return f"pkg:pypi/{normalised}@{version}"


def _component(package: dict) -> dict:
    component = {
        "type": "library",
        "name": package["name"],
        "version": package["version"],
        "purl": _purl(package["name"], package["version"]),
        "bom-ref": _purl(package["name"], package["version"]),
        # Every dependency here is installed from PyPI as a build input, not
        # vendored into the tree.
        "scope": "required",
    }
    if package["hashes"]:
        # The same hashes the build verifies with --require-hashes, so the
        # document and the binary cannot describe different artifacts.
        component["hashes"] = [
            {"alg": "SHA-256", "content": value} for value in package["hashes"]
        ]
    return component


def build_sbom(lockfile_text: str, now=None, serial_seed: str = "") -> dict:
    """
    The whole document, as a dict.

    `now` and `serial_seed` are injectable so the output is reproducible: two
    runs over the same lockfile at the same moment produce byte-identical
    JSON, which is what lets CI diff a regenerated SBOM against a committed
    one and mean something by the result.
    """
    packages = parse_lockfile(lockfile_text)
    moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)

    # A UUID urn derived from the content rather than random, for the same
    # reproducibility reason. Version 4 is what the schema expects to see, so
    # the variant and version nibbles are set to match.
    digest = hashlib.sha256(
        (serial_seed or f"{APP_NAME}-{__version__}-{lockfile_text}").encode("utf-8")
    ).hexdigest()
    serial = (f"urn:uuid:{digest[0:8]}-{digest[8:12]}-4{digest[13:16]}-"
              f"a{digest[17:20]}-{digest[20:32]}")

    return {
        "bomFormat": BOM_FORMAT,
        "specVersion": SPEC_VERSION,
        "serialNumber": serial,
        "version": 1,
        "metadata": {
            "timestamp": moment.astimezone(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
            "tools": [{
                "vendor": APP_NAME,
                "name": "packaging/sbom.py",
                "version": __version__,
            }],
            "component": {
                "type": "application",
                "name": APP_NAME,
                "version": __version__,
                "purl": _purl(APP_NAME, __version__),
                "bom-ref": _purl(APP_NAME, __version__),
                "description": "Windows application usage tracker and limiter",
                # Matches pyproject.toml. Proprietary, stated explicitly.
                "licenses": [{"license": {"name": "LicenseRef-Proprietary"}}],
            },
        },
        "components": [_component(package) for package in packages],
    }


def render(sbom: dict) -> str:
    """The document as text. Sorted keys and a trailing newline, so it diffs."""
    return json.dumps(sbom, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def default_output_path() -> str:
    return os.path.join(REPO_ROOT, "dist",
                        f"{APP_NAME.lower()}-{__version__}.cdx.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    parser.add_argument("--output", default="",
                        help="where to write it (default: dist/)")
    parser.add_argument("--lockfile", default=LOCKFILE)
    parser.add_argument("--check", action="store_true",
                        help="build the document and report on it, writing nothing")
    args = parser.parse_args(argv)

    try:
        with open(args.lockfile, encoding="utf-8") as handle:
            lockfile_text = handle.read()
    except OSError as e:
        print(f"Could not read {args.lockfile}: {e}", file=sys.stderr)
        return 1

    sbom = build_sbom(lockfile_text)
    components = sbom["components"]

    if not components:
        # An empty bill of materials is not a pass. It means the lockfile moved
        # to a format this does not parse, and a compliance document that
        # silently describes nothing is worse than one that is missing.
        print(f"No components found in {args.lockfile}. Refusing to write an "
              "empty bill of materials.", file=sys.stderr)
        return 1

    if args.check:
        print(f"{APP_NAME} {__version__}: {len(components)} component(s)")
        for component in components:
            print(f"  {component['purl']} "
                  f"({len(component.get('hashes', []))} hash(es))")
        return 0

    output = args.output or default_output_path()
    os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(render(sbom))
    print(f"Wrote {output} ({len(components)} component(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
