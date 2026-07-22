#!/usr/bin/env python3
"""Repository checks that do not require private documents or credentials."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

ROOT = Path(__file__).resolve().parents[1]


class DuplicateJsonKeyError(ValueError):
    pass


@dataclass(frozen=True)
class CheckResult:
    name: str
    checked: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJsonKeyError(f"duplicate key: {key}")
        value[key] = item
    return value


def repository_json_files(root: Path = ROOT) -> list[Path]:
    return sorted((root / "miniprogram").rglob("*.json"))


def check_json_files(paths: Sequence[Path]) -> CheckResult:
    errors: list[str] = []
    for path in paths:
        try:
            json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
            errors.append(f"{path}: {exc}")
    if not paths:
        errors.append("no JSON files found")
    return CheckResult(name="json", checked=len(paths), errors=tuple(errors))


def repository_markdown_files(root: Path = ROOT) -> list[Path]:
    candidates = [root / "AGENT.md", root / "README.md", root / "server" / "README.md"]
    candidates.extend((root / "docs").rglob("*.md"))
    return sorted(path for path in candidates if path.is_file())


def _walk_tokens(tokens: Sequence[Token]) -> list[Token]:
    flattened: list[Token] = []
    for token in tokens:
        flattened.append(token)
        if token.children:
            flattened.extend(_walk_tokens(token.children))
    return flattened


def _local_destinations(path: Path, parser: MarkdownIt) -> list[str]:
    tokens = _walk_tokens(parser.parse(path.read_text(encoding="utf-8")))
    destinations: list[str] = []
    for token in tokens:
        if token.type == "link_open":
            destination = token.attrGet("href")
        elif token.type == "image":
            destination = token.attrGet("src")
        else:
            continue
        if isinstance(destination, str) and destination:
            destinations.append(destination)
    return destinations


def check_markdown_links(paths: Sequence[Path], *, root: Path = ROOT) -> CheckResult:
    parser = MarkdownIt("commonmark")
    errors: list[str] = []
    for path in paths:
        try:
            destinations = _local_destinations(path, parser)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        for destination in destinations:
            if destination.startswith(("#", "//")):
                continue
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            relative_path = Path(unquote(parsed.path))
            target = (
                root / relative_path.as_posix().lstrip("/")
                if relative_path.is_absolute()
                else path.parent / relative_path
            )
            if not target.exists():
                errors.append(f"{path}: missing local target {destination}")
    if not paths:
        errors.append("no Markdown files found")
    return CheckResult(name="docs", checked=len(paths), errors=tuple(errors))


def check_test_directories(directories: Sequence[Path]) -> CheckResult:
    errors: list[str] = []
    checked = 0
    for directory in directories:
        tests = sorted(directory.rglob("test_*.py")) if directory.is_dir() else []
        checked += len(tests)
        if not tests:
            errors.append(f"{directory}: no test_*.py files found")
    return CheckResult(name="tests", checked=checked, errors=tuple(errors))


def _expand_files(paths: Sequence[Path], suffix: str) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(path.rglob(f"*{suffix}"))
        else:
            expanded.append(path)
    return sorted(expanded)


def run_check(name: str, paths: Sequence[Path]) -> CheckResult:
    if name == "json":
        files = _expand_files(paths, ".json") if paths else repository_json_files()
        return check_json_files(files)
    if name == "docs":
        files = _expand_files(paths, ".md") if paths else repository_markdown_files()
        root = ROOT if not paths else Path.cwd()
        return check_markdown_links(files, root=root)
    directories = list(paths) if paths else [ROOT / "server" / "tests", ROOT / "tools" / "tests"]
    return check_test_directories(directories)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("json", "docs", "tests"))
    parser.add_argument("paths", nargs="*", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_check(args.check, args.paths)
    if not result.ok:
        print(f"{result.name}: FAILED ({result.checked} files)", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"{result.name}: ok ({result.checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
