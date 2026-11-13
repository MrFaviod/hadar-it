#!/usr/bin/env python3
"""Build the deterministic runtime documentation pack from the tracked allowlist.

The manifest (``docs/runtime-context-manifest.json``) names every document that may
enter the pack and the two component files that carry the product version. The script
splits each Markdown document on ATX headings, hashes the raw bytes, and writes one
sorted JSON file. Nothing outside the manifest is read into the pack, and paths that
look like local records, environment files, secrets, backups or logs are refused.

Usage::

    python3 tools/build-project-context.py            # write the pack
    python3 tools/build-project-context.py --check    # exit 1 when the pack drifted

Exit codes: ``0`` success, ``1`` drift under ``--check``, ``2`` a refused manifest or
document. The output carries no timestamps, so two consecutive builds are identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = "docs/runtime-context-manifest.json"
PACK_PATH = "backend/itsm/project_context/pack.json"
PACK_SCHEMA = "project-context-pack"
PACK_SCHEMA_VERSION = 1
MANIFEST_SCHEMA = "runtime-context-manifest"
MAX_DOCUMENT_BYTES = 1_048_576

REQUIRED_MANIFEST_KEYS = frozenset({"schema", "schema_version", "output", "documents", "components"})
OPTIONAL_MANIFEST_KEYS = frozenset({"notes"})
REQUIRED_COMPONENT_KEYS = frozenset({"name", "source", "format"})
COMPONENT_FORMATS = frozenset({"pyproject-version", "package-json-version"})
COMPONENT_PREFIXES = ("backend/", "frontend/")

FORBIDDEN_PREFIXES = ("odd/", "docs/reviews/", ".git/", "backend/", "frontend/", ".worktrees/")
FORBIDDEN_NAMES = frozenset({"AGENTS.md", "SYSTEM.md", "IDEA.md", "AGENTS.local.md"})
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".log",
        ".bak",
        ".backup",
        ".dump",
        ".sql",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".whl",
        ".pyc",
    }
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abpsr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
TRAILING_HASHES = re.compile(r"[ \t]+#+$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")


class BuildError(Exception):
    """A manifest entry or a document the pack refuses to carry."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise BuildError(f"cannot read {path.relative_to(ROOT)}: {error}") from error


def _relative_path(value: Any, field: str) -> str:
    """Validate one allowlist entry as a relative POSIX path that never traverses."""
    if not isinstance(value, str):
        raise BuildError(f"{field} must be text")
    text = value.strip()
    if not text or text != value:
        raise BuildError(f"{field} must not be blank or padded")
    if "\\" in text or text.startswith("/"):
        raise BuildError(f"{field} must be a relative POSIX path: {text}")
    parts = text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BuildError(f"{field} must not traverse: {text}")
    if text != PurePosixPath(text).as_posix():
        raise BuildError(f"{field} is not normalized: {text}")
    return text


def _document_path(value: Any) -> str:
    text = _relative_path(value, "document")
    if text.startswith(FORBIDDEN_PREFIXES):
        raise BuildError(f"document is a local record or component path: {text}")
    name = PurePosixPath(text).name
    if name in FORBIDDEN_NAMES or name.startswith(".env"):
        raise BuildError(f"document is local-only: {text}")
    if PurePosixPath(text).suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BuildError(f"document looks like a backup or log: {text}")
    if text.lower().endswith(".local.md"):
        raise BuildError(f"document is a local override: {text}")
    if PurePosixPath(text).suffix.lower() != ".md":
        raise BuildError(f"document is not Markdown: {text}")
    candidate = ROOT / text
    if candidate.is_symlink():
        raise BuildError(f"document is a symlink: {text}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise BuildError(f"document escapes the repository: {text}")
    if not candidate.is_file():
        raise BuildError(f"document does not exist: {text}")
    if candidate.stat().st_size > MAX_DOCUMENT_BYTES:
        raise BuildError(f"document is larger than {MAX_DOCUMENT_BYTES} bytes: {text}")
    if (ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "--", text],
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            raise BuildError(f"document is not tracked by git: {text}")
    return text


def _component_source(value: Any) -> str:
    text = _relative_path(value, "component source")
    if not text.startswith(COMPONENT_PREFIXES):
        raise BuildError(f"component source must live under backend/ or frontend/: {text}")
    if not (ROOT / text).is_file():
        raise BuildError(f"component source does not exist: {text}")
    return text


def _secret_scan(text: str, path: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise BuildError(f"document matches a secret pattern: {path}")


def _slug(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title.casefold())
    kept = "".join(character for character in folded if character.isalnum() or character in {" ", "-", "_"})
    slug = re.sub(r"[\s_-]+", "-", kept).strip("-")
    return slug or "section"


def _heading_title(raw: str) -> str:
    return TRAILING_HASHES.sub("", raw).strip()


def split_sections(text: str) -> list[dict[str, Any]]:
    """Split Markdown on ATX headings, ignoring headings inside fenced code blocks."""
    sections: list[dict[str, Any]] = []
    preamble: list[str] = []
    body: list[str] = []
    heading_line: str | None = None
    level = 0
    title = ""
    in_fence = False

    def flush() -> None:
        nonlocal body
        if heading_line is None:
            content = "\n".join(preamble).strip()
            if content:
                sections.append({"title": "Overview", "level": 0, "text": content})
            return
        content = "\n".join(body).strip()
        chunk = heading_line if not content else f"{heading_line}\n\n{content}"
        sections.append({"title": title, "level": level, "text": chunk})
        body = []

    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            match = HEADING.match(line)
            if match:
                flush()
                level = len(match.group(1))
                title = _heading_title(match.group(2))
                heading_line = line.rstrip()
                continue
        if heading_line is None:
            preamble.append(line)
        else:
            body.append(line)
    flush()

    anchors: dict[str, int] = {}
    for section in sections:
        base = _slug(section["title"])
        seen = anchors.get(base, 0)
        anchors[base] = seen + 1
        section["anchor"] = base if seen == 0 else f"{base}-{seen}"
    return sections


def _document_entry(relative: str) -> dict[str, Any]:
    raw = (ROOT / relative).read_bytes()
    text = _read_text(ROOT / relative)
    _secret_scan(text, relative)
    sections = split_sections(text)
    if not sections:
        raise BuildError(f"document has no content: {relative}")
    title = relative
    for section in sections:
        if section["level"] == 1:
            title = section["title"]
            break
    else:
        title = sections[0]["title"]
    return {
        "path": relative,
        "title": title,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "sections": sections,
    }


def _component_entry(entry: Any) -> tuple[str, str]:
    if not isinstance(entry, dict) or set(entry) != REQUIRED_COMPONENT_KEYS:
        raise BuildError("each component needs exactly name, source and format")
    name = entry["name"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
        raise BuildError(f"component name is invalid: {name!r}")
    source = _component_source(entry["source"])
    kind = entry["format"]
    if kind not in COMPONENT_FORMATS:
        raise BuildError(f"unknown component format: {kind!r}")
    if kind == "pyproject-version":
        try:
            version = tomllib.loads(_read_text(ROOT / source))["project"]["version"]
        except (KeyError, tomllib.TOMLDecodeError) as error:
            raise BuildError(f"cannot read project.version from {source}") from error
    else:
        try:
            version = json.loads(_read_text(ROOT / source))["version"]
        except (KeyError, json.JSONDecodeError) as error:
            raise BuildError(f"cannot read version from {source}") from error
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise BuildError(f"component version is invalid in {source}: {version!r}")
    return name, version


def load_manifest() -> dict[str, Any]:
    """Read and validate the allowlist; every refusal names its manifest field."""
    path = ROOT / MANIFEST_PATH
    try:
        manifest = json.loads(_read_text(path))
    except json.JSONDecodeError as error:
        raise BuildError(f"{MANIFEST_PATH} is not valid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise BuildError(f"{MANIFEST_PATH} must be a JSON object")
    keys = set(manifest)
    missing = REQUIRED_MANIFEST_KEYS - keys
    unknown = keys - REQUIRED_MANIFEST_KEYS - OPTIONAL_MANIFEST_KEYS
    if missing:
        raise BuildError(f"manifest is missing: {', '.join(sorted(missing))}")
    if unknown:
        raise BuildError(f"manifest carries unknown keys: {', '.join(sorted(unknown))}")
    if manifest["schema"] != MANIFEST_SCHEMA or manifest["schema_version"] != 1:
        raise BuildError("manifest schema is not runtime-context-manifest version 1")
    if manifest["output"] != PACK_PATH:
        raise BuildError(f"manifest output must be {PACK_PATH}")
    documents = manifest["documents"]
    if not isinstance(documents, list) or not documents:
        raise BuildError("manifest documents must be a non-empty list")
    paths = [_document_path(item) for item in documents]
    if len(set(paths)) != len(paths):
        raise BuildError("manifest documents must not repeat")
    components = manifest["components"]
    if not isinstance(components, list) or not components:
        raise BuildError("manifest components must be a non-empty list")
    pairs = [_component_entry(item) for item in components]
    if len({name for name, _ in pairs}) != len(pairs):
        raise BuildError("manifest components must not repeat a name")
    return manifest


def build_pack() -> dict[str, Any]:
    """Build the pack exactly as it is written, with a digest over every input."""
    manifest = load_manifest()
    documents = sorted((_document_entry(path) for path in manifest["documents"]), key=lambda item: item["path"])
    components = dict(sorted((_component_entry(entry) for entry in manifest["components"])))
    digest_lines = [f"doc\t{document['path']}\t{document['sha256']}" for document in documents]
    digest_lines += [f"component\t{name}\t{version}" for name, version in components.items()]
    return {
        "schema": PACK_SCHEMA,
        "schema_version": PACK_SCHEMA_VERSION,
        "fixture": False,
        "generated_by": "tools/build-project-context.py",
        "source_digest": hashlib.sha256("\n".join(digest_lines).encode("utf-8")).hexdigest(),
        "components": components,
        "documents": documents,
    }


def serialize(pack: dict[str, Any]) -> str:
    return json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def describe_drift(existing: str, pack: dict[str, Any]) -> list[str]:
    """Name the documents whose content or membership changed since the last build."""
    try:
        previous = json.loads(existing)
    except json.JSONDecodeError:
        return ["the existing pack is missing or not valid JSON"]
    if not isinstance(previous, dict):
        return ["the existing pack is not a JSON object"]
    old_documents = {
        document["path"]: document
        for document in previous.get("documents", [])
        if isinstance(document, dict) and isinstance(document.get("path"), str)
    }
    new_documents = {document["path"]: document for document in pack["documents"]}
    details: list[str] = []
    for path in sorted(set(old_documents) | set(new_documents)):
        if path not in old_documents:
            details.append(f"{path} (added)")
        elif path not in new_documents:
            details.append(f"{path} (removed)")
        elif old_documents[path].get("sha256") != new_documents[path]["sha256"]:
            details.append(f"{path} (changed)")
    if previous.get("components") != pack["components"]:
        details.append("component versions changed")
    if previous.get("source_digest") != pack["source_digest"] and not details:
        details.append("source digest changed")
    return details or ["the serialized pack differs"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic runtime documentation pack.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed pack differs from a fresh build instead of writing it",
    )
    args = parser.parse_args(argv)
    try:
        pack = build_pack()
        payload = serialize(pack)
        output = ROOT / PACK_PATH
        sections = sum(len(document["sections"]) for document in pack["documents"])
        summary = f"{len(pack['documents'])} documents, {sections} sections"
        if args.check:
            if not output.is_file():
                print(f"project context pack is missing: {PACK_PATH}", file=sys.stderr)
                return 1
            existing = _read_text(output)
            if existing != payload:
                print(f"project context pack is stale: {PACK_PATH}", file=sys.stderr)
                for detail in describe_drift(existing, pack):
                    print(f"  - {detail}", file=sys.stderr)
                return 1
            print(f"project context pack is up to date ({summary})")
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8", newline="\n")
        print(f"wrote {PACK_PATH} ({summary}, source {pack['source_digest'][:12]})")
        return 0
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
