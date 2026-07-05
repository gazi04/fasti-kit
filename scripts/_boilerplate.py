import re
from pathlib import Path

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def to_snake_case(name: str) -> str:
    normalized = name.replace("-", "_").replace(" ", "_")
    return _CAMEL_BOUNDARY.sub("_", normalized).lower().strip("_")


def to_pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in to_snake_case(name).split("_"))


def write_new_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"skip: {path} already exists")
        return
    path.write_text(content)
    print(f"created: {path}")


_IMPORT_RE = re.compile(r"^from \.(\w+) import (.+)$")
_ALL_RE = re.compile(r"^__all__\s*=\s*\[(.*)\]$")


def update_init(init_path: Path, module: str, symbols: list[str]) -> None:
    imports: dict[str, list[str]] = {}
    all_names: list[str] = []

    if init_path.exists():
        for line in init_path.read_text().splitlines():
            import_match = _IMPORT_RE.match(line)
            if import_match:
                mod, names = import_match.groups()
                imports[mod] = [n.strip() for n in names.split(",")]
                continue
            all_match = _ALL_RE.match(line)
            if all_match:
                all_names = [n.strip().strip("'\"") for n in all_match.group(1).split(",") if n.strip()]

    existing = imports.get(module, [])
    for symbol in symbols:
        if symbol not in existing:
            existing.append(symbol)
        if symbol not in all_names:
            all_names.append(symbol)
    imports[module] = existing

    lines = [f"from .{mod} import {', '.join(names)}" for mod, names in imports.items()]
    all_literal = ", ".join(f"'{n}'" for n in all_names)
    content = "\n".join(lines) + f"\n\n__all__ = [{all_literal}]\n"

    init_path.parent.mkdir(parents=True, exist_ok=True)
    init_path.write_text(content)
    print(f"updated: {init_path}")
