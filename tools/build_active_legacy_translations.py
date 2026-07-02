#!/usr/bin/env python3
"""Build B42 JSON translations from enabled legacy EN translation files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LIVE_MODS_ROOT = Path("/media/cjstorrs/windows/Users/cjsto/Zomboid/mods")
SAVE_MODS = Path(
    "/media/cjstorrs/windows/Users/cjsto/Zomboid/Saves/Sandbox/2026-06-27_21-27-42/mods.txt"
)
DEFAULT_MODS = Path("/media/cjstorrs/windows/Users/cjsto/Zomboid/mods/default.txt")

VALUE_RE = re.compile(r"^\s*(.+?)\s*=\s*([\"'])(.*)\2\s*[,，.]?\s*$")
BARE_TRAILING_QUOTE_RE = re.compile(r"^\s*(.+?)\s*=\s*([^\"'].+?)[\"']\s*[,，.]?\s*$")
CATEGORY_ALIASES = {
    "item_name": "ItemName",
    "itemname": "ItemName",
    "items": "ItemName",
    "sandbox": "Sandbox",
}
IGNORED_CATEGORY_PREFIXES = ("!",)


def canonical_category(category: str) -> str:
    return CATEGORY_ALIASES.get(category.lower(), category)


def ignored_category(category: str) -> bool:
    return category.startswith(IGNORED_CATEGORY_PREFIXES)


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


def active_roots(active_ids: list[str]) -> list[Path]:
    active_set = set(active_ids)
    active_order = {mod_id: index for index, mod_id in enumerate(active_ids)}
    roots: list[tuple[int, str, Path]] = []
    for root in sorted(p for p in LIVE_MODS_ROOT.iterdir() if p.is_dir()):
        root_ids: set[str] = set()
        for mod_info in root.rglob("mod.info"):
            root_ids.update(parse_mod_info_ids(mod_info))
        matched_ids = root_ids & active_set
        if matched_ids:
            load_index = min(active_order[mod_id] for mod_id in matched_ids)
            roots.append((load_index, root.name.lower(), root))
    return [root for _, _, root in sorted(roots)]


def default_ids_in_save_order(save_ids: list[str], default_ids: list[str]) -> list[str]:
    default_set = set(default_ids)
    save_set = set(save_ids)
    ordered_ids = [mod_id for mod_id in save_ids if mod_id in default_set]
    ordered_ids.extend(mod_id for mod_id in default_ids if mod_id not in save_set)
    return ordered_ids


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
        if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
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
    suffix = "media/lua/shared/translate/en/"
    files = []
    for path in root.rglob("*_EN.txt"):
        rel = path.relative_to(root)
        rel_posix = str(rel).replace("\\", "/").lower()
        if f"/{suffix}" not in f"/{rel_posix}":
            continue
        legacy_category = path.name[:-7]
        if canonical_category(legacy_category) == category:
            files.append(path)
    return sorted(files, key=lambda p: file_sort_key(p.relative_to(root)))


def iter_sandbox_option_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("sandbox-options.txt"):
        rel = path.relative_to(root)
        rel_posix = rel.as_posix().lower()
        if rel_posix.endswith("media/sandbox-options.txt"):
            files.append(path)
    return sorted(files, key=lambda p: file_sort_key(p.relative_to(root)))


def humanize_translation_key(key: str) -> str:
    text = re.sub(r"^[A-Za-z0-9]+_", "", key)
    text = text.replace("_", " ")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", text)
    return re.sub(r"\s+", " ", text).strip() or key


def add_sandbox_option_fallbacks(
    entries: dict[str, str],
    key_sources: dict[str, list[str]],
    roots: list[Path],
) -> None:
    option_re = re.compile(r"option\s+([^\s]+)\s*\{(.*?)\}", re.DOTALL)
    translation_re = re.compile(r"translation\s*=\s*([A-Za-z0-9_]+)\s*,")

    for root in roots:
        for path in iter_sandbox_option_files(root):
            rel_source = f"{root.name}:{path.relative_to(root).as_posix()}"
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for match in option_re.finditer(text):
                translation_match = translation_re.search(match.group(2))
                if not translation_match:
                    continue
                translation = translation_match.group(1)
                key = f"Sandbox_{translation}"
                if key in entries:
                    continue
                line_number = text.count("\n", 0, match.start()) + 1
                entries[key] = humanize_translation_key(translation)
                key_sources.setdefault(key, []).append(
                    f"{rel_source}:{line_number} (sandbox-options fallback)"
                )


def discover_categories(roots: list[Path]) -> list[str]:
    categories: set[str] = set()
    for root in roots:
        for path in root.rglob("*_EN.txt"):
            rel = path.relative_to(root).as_posix().lower()
            if "/media/lua/shared/translate/en/" not in f"/{rel}":
                continue
            category = canonical_category(path.name[:-7])
            if not ignored_category(category):
                categories.add(category)
    return sorted(categories)


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
            or re.match(r"^[A-Za-z0-9_]+\s*(?:\{=?|=)?\s*$", line)
            or re.match(r"^[A-Za-z0-9_]+_EN\s*=\s*$", line)
        ):
            continue
        match = VALUE_RE.match(line)
        if not match:
            match = BARE_TRAILING_QUOTE_RE.match(line)
        if not match:
            skipped.append(f"{rel_source}:{line_number}: {original_line.strip()}")
            continue
        key = match.group(1).strip()
        value = decode_lua_string(match.group(3) if len(match.groups()) == 3 else match.group(2).strip())
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

    if category == "Sandbox":
        add_sandbox_option_fallbacks(entries, key_sources, roots)

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
        default=None,
        help="Legacy translation categories to build. Defaults to all active categories except notes.",
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
        print(
            "latest save mods.txt does not match mods/default.txt; "
            "using default membership in latest-save order"
        )

    roots = active_roots(default_ids_in_save_order(save_ids, default_ids))
    print(f"active roots: {len(roots)}")
    categories = args.categories or discover_categories(roots)
    categories = sorted({canonical_category(category) for category in categories if not ignored_category(category)})
    print(f"categories: {', '.join(categories)}")
    for category in categories:
        build_category(category, roots, args.output_root)


if __name__ == "__main__":
    main()
