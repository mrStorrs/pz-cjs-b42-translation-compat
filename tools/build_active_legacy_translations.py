#!/usr/bin/env python3
"""Build B42 JSON translations from enabled legacy EN translation files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LIVE_MODS_ROOT = Path("/media/cjstorrs/windows/Users/cjsto/Zomboid/mods")
SAVE_MODS = Path(
    "/media/cjstorrs/windows/Users/cjsto/Zomboid/Saves/Sandbox/2026-06-30_23-36-46/mods.txt"
)
DEFAULT_MODS = Path("/media/cjstorrs/windows/Users/cjsto/Zomboid/mods/default.txt")

VALUE_RE = re.compile(r"^\s*(.+?)\s*=\s*([\"'])(.*)\2\s*[,，]?\s*$")


def parse_mod_list(path: Path) -> list[str]:
    mod_ids: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*mod\s*=\s*\\?(.+?)\s*,\s*$", line)
        if match:
            mod_ids.append(match.group(1).strip())
    return mod_ids


def parse_mod_info_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lower().startswith("id="):
            raw_ids = line.split("=", 1)[1].strip()
            ids.update(mod_id.strip() for mod_id in raw_ids.split(";") if mod_id.strip())
    return ids


def active_roots(active_ids: set[str]) -> list[Path]:
    roots: list[Path] = []
    for root in sorted(p for p in LIVE_MODS_ROOT.iterdir() if p.is_dir()):
        root_ids: set[str] = set()
        for mod_info in root.rglob("mod.info"):
            root_ids.update(parse_mod_info_ids(mod_info))
        if root_ids & active_ids:
            roots.append(root)
    return roots


def strip_lua_comment(line: str) -> str:
    quote = ""
    escaped = False
    output: list[str] = []
    index = 0
    while index < len(line):
        char = line[index]
        if escaped:
            output.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            output.append(char)
            escaped = True
            index += 1
            continue
        if quote:
            output.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in ("'", '"'):
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "-" and index + 1 < len(line) and line[index + 1] == "-":
            break
        if char == "/" and index + 1 < len(line) and line[index + 1] == "*":
            end = line.find("*/", index + 2)
            if end == -1:
                break
            index = end + 2
            continue
        output.append(char)
        index += 1
    return "".join(output)


def decode_lua_string(value: str) -> str:
    output: list[str] = []
    escaped = False
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "\\": "\\",
        '"': '"',
        "'": "'",
    }
    for char in value:
        if escaped:
            output.append(escapes.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            output.append(char)
    if escaped:
        output.append("\\")
    return "".join(output)


def version_tuple(name: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", name))


def file_sort_key(path: Path) -> tuple[int, tuple[int, ...], str]:
    first = path.parts[0] if path.parts else ""
    if first.lower() == "common":
        return (0, (), str(path).lower())
    if first.lower() == "media":
        return (1, (), str(path).lower())
    if re.match(r"^\d+(?:\.\d+)*$", first):
        return (2, version_tuple(first), str(path).lower())
    return (1, (), str(path).lower())


def iter_legacy_files(root: Path, category: str) -> list[Path]:
    suffix = f"media/lua/shared/Translate/EN/{category}_EN.txt".lower()
    files = []
    for path in root.rglob(f"{category}_EN.txt"):
        rel = path.relative_to(root)
        if str(rel).replace("\\", "/").lower().endswith(suffix):
            files.append(path)
    return sorted(files, key=lambda p: file_sort_key(p.relative_to(root)))


def parse_legacy_file(path: Path, root: Path) -> tuple[dict[str, str], list[str], list[str]]:
    entries: dict[str, str] = {}
    sources: list[str] = []
    skipped: list[str] = []
    rel_source = f"{root.name}:{path.relative_to(root).as_posix()}"

    for line_number, original_line in enumerate(
        path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1
    ):
        line = strip_lua_comment(original_line).strip()
        if (
            not line
            or line.endswith("{")
            or line == "}"
            or re.match(r"^[A-Za-z0-9_]+_EN\s*=\s*$", line)
        ):
            continue
        match = VALUE_RE.match(line)
        if not match:
            skipped.append(f"{rel_source}:{line_number}: {original_line.strip()}")
            continue
        key = match.group(1).strip()
        value = decode_lua_string(match.group(3))
        if not key:
            skipped.append(f"{rel_source}:{line_number}: {original_line.strip()}")
            continue
        entries[key] = value
        sources.append(f"{key}: {rel_source}:{line_number}")
    return entries, sources, skipped


def build_category(category: str, roots: list[Path], output_root: Path) -> None:
    entries: dict[str, str] = {}
    key_sources: dict[str, list[str]] = {}
    skipped: list[str] = []

    for root in roots:
        for path in iter_legacy_files(root, category):
            file_entries, file_sources, file_skipped = parse_legacy_file(path, root)
            entries.update(file_entries)
            for source in file_sources:
                key, location = source.split(": ", 1)
                key_sources.setdefault(key, []).append(location)
            skipped.extend(file_skipped)

    translate_dir = output_root / "42/media/lua/shared/Translate/EN"
    docs_dir = output_root / "docs"
    translate_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    json_path = translate_dir / f"{category}.json"
    source_path = docs_dir / f"{category}_sources.txt"
    skipped_path = docs_dir / f"{category}_skipped.txt"

    json_path.write_text(
        json.dumps(dict(sorted(entries.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source_lines = [
        f"{key}: {'; '.join(locations)}"
        for key, locations in sorted(key_sources.items())
    ]
    source_path.write_text("\n".join(source_lines) + ("\n" if source_lines else ""), encoding="utf-8")
    skipped_path.write_text("\n".join(skipped) + ("\n" if skipped else ""), encoding="utf-8")

    print(
        f"{category}: {len(entries)} keys, {sum(len(v) for v in key_sources.values())} sources, "
        f"{len(skipped)} skipped"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--categories",
        nargs="+",
        default=["Sandbox", "UI", "IG_UI"],
        help="Legacy translation categories to build.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="cjsB42TranslationCompat project root.",
    )
    args = parser.parse_args()

    save_ids = parse_mod_list(SAVE_MODS)
    default_ids = parse_mod_list(DEFAULT_MODS)
    if save_ids != default_ids:
        raise SystemExit("latest save mods.txt does not match mods/default.txt")

    roots = active_roots(set(save_ids))
    print(f"active roots: {len(roots)}")
    for category in args.categories:
        build_category(category, roots, args.output_root)


if __name__ == "__main__":
    main()
