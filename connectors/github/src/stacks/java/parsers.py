"""Manifest parsers for Java repositories — pom.xml + Gradle.

Both parsers return ``[{name, version, group}]`` dicts. ``name`` is the
artifactId; ``group`` is the groupId; ``version`` is the literal string
in the manifest, including unresolved property placeholders like
``${spring.ai.version}``.

The Gradle parser is regex-based — full Gradle DSL parsing requires
running Groovy or Kotlin Script, which we won't ship in the connector.
This means we miss dependencies declared via dynamic logic, plugin DSLs,
or version catalogs (libs.versions.toml). Those gaps are documented and
covered by the LLM scanner pass in week 2.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# pom.xml
# ---------------------------------------------------------------------------

_POM_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def parse_pom(path: Path) -> list[dict[str, str]]:
    """Parse a Maven ``pom.xml`` into a list of dependency dicts.

    Walks ``<dependencies><dependency>`` under both the project root and
    ``<dependencyManagement>``. Test scope is included; users who care
    about scope can filter downstream.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        log.warning("Unparsable pom.xml at %s: %s", path, exc)
        return []
    root = tree.getroot()

    # Maven uses a namespace by default; some POMs omit it.
    ns = _POM_NS if root.tag.startswith("{") else {"m": ""}
    if not root.tag.startswith("{"):
        ns = {"m": ""}
        # ElementTree uses '' as no-namespace, but findall expects no prefix
        # — we'll just walk by local-name.
        return _parse_pom_no_ns(root)

    results: list[dict[str, str]] = []
    for dep in root.findall(".//m:dependency", ns):
        group = (dep.findtext("m:groupId", "", ns) or "").strip()
        name = (dep.findtext("m:artifactId", "", ns) or "").strip()
        version = (dep.findtext("m:version", "", ns) or "").strip()
        if name:
            results.append({"name": name, "group": group, "version": version})
    return results


def _parse_pom_no_ns(root: ET.Element) -> list[dict[str, str]]:
    """Fallback for POMs without an XML namespace."""
    results: list[dict[str, str]] = []
    for dep in root.iter("dependency"):
        group = (dep.findtext("groupId") or "").strip()
        name = (dep.findtext("artifactId") or "").strip()
        version = (dep.findtext("version") or "").strip()
        if name:
            results.append({"name": name, "group": group, "version": version})
    return results


# ---------------------------------------------------------------------------
# build.gradle / build.gradle.kts
# ---------------------------------------------------------------------------

# Matches the common shapes:
#   implementation 'group:artifact:version'
#   implementation "group:artifact:version"
#   implementation("group:artifact:version")
#   api(group: 'g', name: 'a', version: 'v')          (Groovy map form, partial)
#   testImplementation 'group:artifact'                (no version)
_GRADLE_GAV_RE = re.compile(
    r"""
    \b(?:implementation|api|compile|runtimeOnly|testImplementation|
        testRuntimeOnly|annotationProcessor|kapt|ksp)
    \s*[\(\s]?\s*
    ['"]
    (?P<group>[A-Za-z0-9._-]+)
    :
    (?P<name>[A-Za-z0-9._-]+)
    (?: : (?P<version>[A-Za-z0-9._${}-]+) )?
    ['"]
    """,
    re.VERBOSE,
)


def parse_gradle(path: Path) -> list[dict[str, str]]:
    """Parse a ``build.gradle`` or ``build.gradle.kts`` for declared deps.

    Regex-only — see module docstring for the precision/recall tradeoff.
    """
    try:
        text = path.read_text()
    except OSError as exc:
        log.warning("Unable to read %s: %s", path, exc)
        return []

    seen: set[tuple[str, str]] = set()
    results: list[dict[str, str]] = []
    for match in _GRADLE_GAV_RE.finditer(text):
        group = match.group("group")
        name = match.group("name")
        version = match.group("version") or ""
        key = (group, name)
        if key in seen:
            continue
        seen.add(key)
        results.append({"name": name, "group": group, "version": version})
    return results
