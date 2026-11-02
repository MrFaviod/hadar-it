#!/usr/bin/env python3
"""Documentation consistency checks for the first public pre-alpha entry docs.

The checks are static and read-only: they read the Markdown and the Compose files
in this repository and ask read-only ``git ls-files`` / ``git check-ignore`` which
files are published. Nothing is built, pulled, started or written. Command evidence
for the rendered projects is produced separately with
``docker compose --env-file /dev/null … config``; this script only guarantees that
the documented commands keep naming the files, modes and variables that actually
exist, and that the translated documents keep the same command lines.

Exit codes: ``0`` all checks passed, ``1`` a check failed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

README = "README.md"
MODE_DOC = "docs/release-modes-deployment.md"
OPS_PAIR = ("docs/operations.md", "docs/operations.es.md")
USER_PAIR = ("docs/user-operations.en.md", "docs/user-operations.md")
COMPOSE_FILES = {
    "dev": "deploy/compose.dev.yaml",
    "prod": "deploy/compose.prod.yaml",
    "demo": "deploy/compose.demo.yaml",
}

# Same base tag and digest as frontend/Dockerfile; the final frontend image
# additionally contains application files.
NGINX_TLS_IMAGE = (
    "nginx:1.28.3-alpine@sha256:"
    "a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236"
)

COMMAND_START = re.compile(
    r"^(docker |export |RELEASE_MODE=|COMPOSE_FILE=|\.venv/bin/python|python |python3 |"
    r"curl |npm |ITSM_[A-Z_]+=|--|\.\s|cd )"
)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def fenced_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
            continue
        if current is not None:
            current.append(line)
    assert current is None, "unterminated fenced code block"
    return blocks


def command_lines(text: str) -> list[str]:
    """Shell lines inside fenced blocks, without comments and blank lines."""
    return [line for _, line in command_entries(text)]


def command_entries(text: str) -> list[tuple[str, str]]:
    """Pairs of (closest preceding comment, shell line) inside fenced blocks.

    The comment lets a document state the intent of a command that is expected to
    fail, such as the mandatory-mode refusal.
    """
    entries: list[tuple[str, str]] = []
    for block in fenced_blocks(text):
        comment = ""
        for line in block:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                comment = stripped
                continue
            if COMMAND_START.match(stripped):
                entries.append((comment, stripped))
    return entries


def compose_lines(text: str) -> list[str]:
    return [line for line in command_lines(text) if line.startswith("docker compose")]


def service_image(service: str, relative: str = "compose.yaml") -> str:
    """Image reference of one Compose service, from its top-level block."""
    lines = read(relative).splitlines()
    header = f"  {service}:"
    for index, line in enumerate(lines):
        if line.rstrip() != header:
            continue
        for following in lines[index + 1 :]:
            if following.strip() and not following.startswith("    "):
                break
            if following.startswith("    image:"):
                return following.split("image:", 1)[1].strip().strip("\"'")
        break
    return ""


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name}: {detail or 'failed'}")
    print(f"PASS {name}")


def check_entry_documents() -> None:
    for relative in (README, MODE_DOC, *OPS_PAIR, *USER_PAIR):
        check(f"exists {relative}", (ROOT / relative).is_file(), "missing document")

    for mode, overlay in COMPOSE_FILES.items():
        check(f"overlay exists {overlay}", (ROOT / overlay).is_file(), "missing overlay")

    compose = read("compose.yaml")
    compose_and_overlays = compose + "".join(read(path) for path in COMPOSE_FILES.values())
    check(
        "compose demands a release mode",
        "name: itsm-${RELEASE_MODE:?" in compose,
        "compose.yaml no longer carries the mandatory RELEASE_MODE project name",
    )
    check(
        "compose gates startup on preparation",
        "command: [python, -m, itsm.deployment, prepare]" in compose,
        "initialize no longer runs deployment prepare",
    )
    for variable in (
        "RELEASE_MODE",
        "ITSM_SELINUX_LEVEL",
        "ITSM_DATABASE_URL",
        "ITSM_AUTH_ORIGIN",
        "ITSM_DEV_ADMIN_PASSWORD",
    ):
        check(
            f"variable documented and used {variable}",
            variable in compose_and_overlays,
            "no Compose file references the documented variable",
        )


def check_readme_start_path() -> None:
    text = read(README)
    check(
        "README requires a release mode",
        "export RELEASE_MODE=dev" in text
        and all(f"-f {overlay}" in text for overlay in COMPOSE_FILES.values()),
        "the start path does not export RELEASE_MODE with every mode overlay",
    )
    check(
        "README keeps the environment explicit",
        "No `.env` file is created or read" in text
        and "docker compose --env-file /dev/null" in text,
        "the documented commands must keep --env-file /dev/null and no .env file",
    )
    check(
        "README does not use the obsolete bootstrap command",
        "bootstrap-admin" not in text,
        "bootstrap-admin was replaced by bootstrap-superadmin",
    )
    check(
        "README names the production first owner",
        "bootstrap-superadmin" in text and "initialize" in text,
        "the production path must document initialize plus bootstrap-superadmin",
    )
    check(
        "README does not install through the migrate service",
        not any("run --rm migrate" in line for line in command_lines(text)),
        "preparation applies migrations; migrate is a manual tools-profile fallback",
    )
    for comment, line in command_entries(text):
        if not line.startswith("docker compose"):
            continue
        if "must fail" in comment.lower():
            check(
                "README documents the mandatory-mode refusal",
                "config" in line and " -f " not in line,
                line,
            )
            continue
        check(
            "README compose command names its overlay",
            any(f"-f {overlay}" in line for overlay in COMPOSE_FILES.values()),
            line,
        )
        check(
            "README compose command sets the mode",
            "RELEASE_MODE=" in line or "export RELEASE_MODE=" in text,
            line,
        )
    check(
        "README links the mode document",
        "(docs/release-modes-deployment.md" in text,
        "the start path must link the release-mode document",
    )
    check(
        "README links SDK and engine prerequisites",
        "backend/docs/extensions-sdk.md" in text
        and "backend/docs/agent-integrations.md" in text,
        "the entry document must link the extension SDK and the agent engines",
    )
    for profile in ("dev", "prod", "demo"):
        check(
            f"README describes mode {profile}",
            f"deploy/compose.{profile}.yaml" in text,
            "each mode overlay must be named",
        )


def check_operations_documents() -> None:
    for relative in OPS_PAIR:
        text = read(relative)
        check(
            f"{relative} exports the mode",
            "export RELEASE_MODE=prod" in text,
            "every Compose command depends on a mode",
        )
        check(
            f"{relative} exports the overlay",
            "export COMPOSE_FILE=compose.yaml:deploy/compose.prod.yaml" in text,
            "the installation shell must name its overlay",
        )
        check(
            f"{relative} does not install through the migrate service",
            not any("run --rm migrate" in line for line in command_lines(text)),
            "preparation applies migrations; migrate stays a manual fallback",
        )
        check(
            f"{relative} names the production first owner",
            "bootstrap-superadmin" in text,
            "production creates no accounts during preparation",
        )
        lines = compose_lines(text)
        check(f"{relative} has compose commands", bool(lines), "no Compose command found")
        for line in lines:
            check(
                f"{relative} compose line stays explicit",
                "--env-file /dev/null" in line,
                line,
            )


def check_user_operations_documents() -> None:
    for relative in USER_PAIR:
        text = read(relative)
        check(
            f"{relative} starts with the release mode",
            "export RELEASE_MODE=prod" in text and "export COMPOSE_FILE=" in text,
            "the guide must select a mode and overlay first",
        )
        check(
            f"{relative} explains the preparation gate",
            "python -m itsm.deployment prepare" in text and "initialize" in text,
            "the guide must explain preparation instead of a manual migration step",
        )
        check(
            f"{relative} does not install through the migrate service",
            not any("run --rm migrate" in line for line in command_lines(text)),
            "migrate is a manual tools-profile fallback",
        )
        check(
            f"{relative} keeps the production owner explicit",
            "bootstrap-superadmin" in text and "adopt-superadmin" in text,
            "first owner and later claim must stay documented",
        )
        check(
            f"{relative} keeps secrets out of files",
            "`--env-file /dev/null`" in text and "`.env.example`" in text,
            "the guide must keep the explicit process environment rule",
        )
        check(
            f"{relative} links the demo contract",
            "backend/docs/demo-public.md" in text,
            "the publishable demo must link its public contract",
        )


def check_translated_command_parity() -> None:
    for pair in (OPS_PAIR, USER_PAIR):
        source, translation = pair
        source_lines = command_lines(read(source))
        translation_lines = command_lines(read(translation))
        check(
            f"command parity {source} / {translation}",
            source_lines == translation_lines,
            "the two language versions must carry identical command lines",
        )
        check(
            f"command lines found {source}",
            bool(source_lines),
            "no shell command detected; the extractor or the document changed shape",
        )


def check_demo_mount_documentation() -> None:
    overlay = read(COMPOSE_FILES["demo"])
    check(
        "demo overlay mounts the volume at /data",
        "demo-data:/data" in overlay and "demo-data:/data/demo" not in overlay,
        "the demo volume must be documented as mounted at /data",
    )
    text = read(MODE_DOC)
    check(
        "mode document matches the demo mount",
        "`itsm-demo_demo-data` → `/data`" in text,
        "the mode table must show /data, not /data/demo, as the mount target",
    )
    check(
        "mode document explains the demo data directory",
        "`/data/demo`" in text and "not at `/data/demo`" in text,
        "the data directory inside the volume must stay distinguished from the mount",
    )
    check(
        "operations documents do not claim the demo mount path",
        "`demo-data` → `/data/demo`" not in read(OPS_PAIR[0])
        and "`demo-data` → `/data/demo`" not in read(OPS_PAIR[1]),
        "the mount target is /data; /data/demo is the owned data directory",
    )


def check_optional_tls_image_pinned() -> None:
    """The optional TLS proxy must use one exact nginx tag and digest.

    A floating tag such as ``nginx:1.29-alpine`` resolves to different bytes on
    every pull, so the same release would not be reproducible.
    """
    image = service_image("proxy")
    check(
        "optional TLS proxy pins the exact nginx image",
        image == NGINX_TLS_IMAGE,
        f"proxy image is {image or 'missing'}, expected {NGINX_TLS_IMAGE}",
    )
    check(
        "optional TLS proxy image carries a digest",
        "@sha256:" in image and not image.endswith(":latest"),
        "the proxy image must be tag@sha256:… rather than a floating tag",
    )


def check_referenced_overlays_exist() -> None:
    pattern = re.compile(r"deploy/compose\.[a-z]+\.yaml")
    for relative in (README, MODE_DOC, *OPS_PAIR, *USER_PAIR):
        for overlay in set(pattern.findall(read(relative))):
            check(
                f"{relative} references an existing overlay {overlay}",
                (ROOT / overlay).is_file(),
                "documented overlay does not exist",
            )


def check_root_links_exist() -> None:
    """Root-owned relative links in the entry docs must resolve.

    Component links (``backend/…``, ``frontend/…``, with or without ``../``) are
    skipped: those are independent repositories that this worktree may not contain.
    """
    pattern = re.compile(r"\]\(([^)\s]+)\)")
    for relative in (README, MODE_DOC, *OPS_PAIR, *USER_PAIR):
        document = ROOT / relative
        for target in set(pattern.findall(document.read_text(encoding="utf-8"))):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path = target.split("#", 1)[0]
            if not path or path.startswith(("../backend/", "../frontend/")):
                continue
            if path.startswith(("backend/", "frontend/")):
                continue
            resolved = (document.parent / path).resolve()
            check(
                f"{relative} links to {target}",
                resolved.is_file(),
                "root-owned link target does not exist",
            )


# Local records that are never published; published docs must not point at them.
LOCAL_RECORD_REFERENCE = re.compile(r"(?<![\w.-])(?:odd/|AGENTS\.md\b|docs/reviews/)")
LOCAL_ONLY_PATHS = (
    "AGENTS.md",
    "SYSTEM.md",
    "odd/sample.md",
    "docs/reviews/sample.md",
    ".omp/sample",
    ".publish/sample",
    ".verification/sample",
)
# Same-named paths below the root, and new public docs, must stay addable.
PUBLISHABLE_PATHS = (
    "docs/new-public-doc.md",
    "docs/odd/sample.md",
    "scripts/odd/sample.py",
    "docs/SYSTEM.md",
    "docs/AGENTS.md",
)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    )


def is_ignored(relative: str) -> bool:
    return git("check-ignore", "-q", "--no-index", relative).returncode == 0


def check_no_local_record_references() -> None:
    """Tracked root docs must not link or point at unpublished local records."""
    tracked = git("ls-files", "--", README, "docs/*.md").stdout.split()
    found = [
        f"{relative}:{number}"
        for relative in tracked
        for number, line in enumerate(read(relative).splitlines(), start=1)
        if LOCAL_RECORD_REFERENCE.search(line)
    ]
    check(
        "published docs do not reference unpublished local records",
        not found,
        ", ".join(found),
    )


def check_local_only_ignore_rules() -> None:
    """Local-only rules stay anchored at the root without hiding public docs."""
    for relative in LOCAL_ONLY_PATHS:
        check(f".gitignore keeps {relative} local", is_ignored(relative), "not ignored")
    for relative in PUBLISHABLE_PATHS:
        check(f".gitignore lets {relative} be added", not is_ignored(relative), "ignored")


def main() -> int:
    try:
        check_entry_documents()
        check_readme_start_path()
        check_operations_documents()
        check_user_operations_documents()
        check_translated_command_parity()
        check_demo_mount_documentation()
        check_optional_tls_image_pinned()
        check_referenced_overlays_exist()
        check_root_links_exist()
        check_local_only_ignore_rules()
        check_no_local_record_references()
    except AssertionError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("all pre-alpha documentation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
