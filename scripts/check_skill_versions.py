#!/usr/bin/env python3
"""Pre-commit guard: detect skill changes that forgot a version bump.

For each watched "unit" (a skill directory), if any staged file under it
changed, at least one of the unit's version declarations must have a *different
value* between HEAD and the staged index. Comparing the value (not just "the
file was touched") is what catches an edit that left the version number alone.

Each unit's version is independent; no cross-unit consistency is required.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field

# --- Configuration ---------------------------------------------------------

SKILL_VERSION_RE = re.compile(r"#\s*Version\s+(\S+)", re.IGNORECASE)
TOML_VERSION_RE = re.compile(r"""^\s*version\s*=\s*["'](.+?)["']""", re.MULTILINE)

# Noise that lives under a skill dir but shouldn't trigger a version bump.
IGNORE_SUBSTRINGS = ("__pycache__/", ".egg-info/")
IGNORE_SUFFIXES = (".pyc", ".env")


@dataclass
class VersionSource:
    path: str          # repo-relative, posix-style (matches `git` output)
    pattern: re.Pattern


@dataclass
class Unit:
    name: str
    dir: str           # repo-relative dir prefix, posix-style, trailing slash
    sources: list[VersionSource] = field(default_factory=list)


UNITS = [
    Unit(
        name="zenn",
        dir=".claude/skills/zenn/",
        sources=[
            VersionSource(".claude/skills/zenn/SKILL.md", SKILL_VERSION_RE),
        ],
    ),
    Unit(
        name="use-tavily",
        dir=".claude/skills/use-tavily/",
        sources=[
            VersionSource(".claude/skills/use-tavily/SKILL.md", SKILL_VERSION_RE),
            VersionSource(".claude/skills/use-tavily/pyproject.toml", TOML_VERSION_RE),
        ],
    ),
]


# --- Git helpers -----------------------------------------------------------

def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout


def staged_files() -> list[str]:
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [line.strip() for line in out.splitlines() if line.strip()]


def blob(rev: str, path: str) -> str | None:
    """Content of `path` at `rev` (e.g. 'HEAD' or '' for the index).

    Returns None if the path doesn't exist there (e.g. a newly added file).
    """
    spec = f"{rev}:{path}" if rev else f":{path}"
    res = subprocess.run(
        ["git", "show", spec],
        capture_output=True, text=True, encoding="utf-8",
    )
    return res.stdout if res.returncode == 0 else None


def version_in(content: str | None, pattern: re.Pattern) -> str | None:
    if content is None:
        return None
    m = pattern.search(content)
    return m.group(1) if m else None


# --- Core ------------------------------------------------------------------

def is_ignored(path: str) -> bool:
    return (
        any(s in path for s in IGNORE_SUBSTRINGS)
        or path.endswith(IGNORE_SUFFIXES)
    )


def version_bumped(src: VersionSource) -> bool:
    """True if the version value differs between HEAD and the staged index."""
    head_v = version_in(blob("HEAD", src.path), src.pattern)
    staged_v = version_in(blob("", src.path), src.pattern)
    # New file (no HEAD version) counts as a bump; otherwise require a change.
    if head_v is None:
        return staged_v is not None
    return staged_v != head_v


def main() -> int:
    staged = [f for f in staged_files() if not is_ignored(f)]
    failures: list[str] = []

    for unit in UNITS:
        changed = [f for f in staged if f.startswith(unit.dir)]
        if not changed:
            continue
        if any(version_bumped(src) for src in unit.sources):
            continue

        decls = " または ".join(f"`{s.path}`" for s in unit.sources)
        listing = "\n".join(f"      - {f}" for f in changed)
        failures.append(
            f"  [{unit.name}] 配下に変更がありますが、バージョンが更新されていません。\n"
            f"    更新が必要: {decls} のいずれかの version 値\n"
            f"    変更されたファイル:\n{listing}"
        )

    if failures:
        sys.stderr.write(
            "\n✗ スキルのバージョン更新漏れを検出しました:\n\n"
            + "\n\n".join(failures)
            + "\n\n  対処: 該当スキルの version を上げてから再コミットしてください。\n"
            "  緊急回避: git commit --no-verify\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
