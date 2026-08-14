import re
from pathlib import Path
from typing import Any

# Boundary between the last capital of an acronym run and the Capitalized word that
# follows it, e.g. "HTTPServer" -> boundary lands before the "S" in "Server".
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
# Boundary between a lowercase letter/digit and the uppercase letter that follows it,
# e.g. "userProfile" -> boundary before "P".
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

TYPE_MAPPING = {
    "str": {"py": "str", "sqla": "String", "pydantic": "str"},
    "int": {"py": "int", "sqla": "Integer", "pydantic": "int"},
    "float": {"py": "float", "sqla": "Float", "pydantic": "float"},
    "bool": {"py": "bool", "sqla": "Boolean", "pydantic": "bool"},
    "uuid": {"py": "uuid.UUID", "sqla": "UUID(as_uuid=True)", "pydantic": "uuid.UUID"},
}


def parse_fields(fields_str: str) -> list[dict[str, Any]]:
    """Parses 'name:str,price:float,is_active:bool=True' into structured data for all generators."""
    parsed = []
    if not fields_str:
        return parsed

    for item in fields_str.split(","):
        item = item.strip()
        if not item:
            continue

        default_val = None
        if "=" in item:
            item, default_val = item.split("=", 1)

        name, field_type = item.split(":")
        name = name.strip()

        # Skip base fields to prevent duplicate initialization
        if name in ["id", "created_at", "updated_at", "is_active"]:
            continue

        parsed.append(
            {
                "name": name,
                "type": field_type.strip(),
                "default": default_val.strip() if default_val else None,
                "py_type": TYPE_MAPPING.get(field_type.strip(), TYPE_MAPPING["str"])[
                    "py"
                ],
                "sqla_type": TYPE_MAPPING.get(field_type.strip(), TYPE_MAPPING["str"])[
                    "sqla"
                ],
            }
        )
    return parsed


def to_snake_case(name: str) -> str:
    normalized = name.replace("-", "_").replace(" ", "_")
    normalized = _ACRONYM_BOUNDARY.sub("_", normalized)
    normalized = _CAMEL_BOUNDARY.sub("_", normalized)
    return normalized.lower().strip("_")


def to_pascal_case(name: str) -> str:
    return "".join(part.capitalize() for part in to_snake_case(name).split("_"))


def pluralize(word: str) -> str:
    return word if word.endswith("s") else f"{word}s"


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
    # If no symbols are provided, just create an empty __init__.py safely
    if not module and not symbols:
        init_path.parent.mkdir(parents=True, exist_ok=True)
        init_path.touch()
        return

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
                all_names = [
                    n.strip().strip("'\"")
                    for n in all_match.group(1).split(",")
                    if n.strip()
                ]

    existing = imports.get(module, [])
    for symbol in symbols:
        if symbol not in existing:
            existing.append(symbol)
        if symbol not in all_names:
            all_names.append(symbol)

    if existing:
        imports[module] = existing

    # Only generate lines if names exist, preventing trailing "from .module import "
    lines = []
    for mod, names in imports.items():
        if names:
            lines.append(f"from .{mod} import {', '.join(names)}")

    all_literal = ", ".join(f"'{n}'" for n in all_names)

    content = ""
    if lines:
        content += "\n".join(lines) + "\n"
    if all_names:
        content += f"\n__all__ = [{all_literal}]\n"

    init_path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure there is content, otherwise just touch the file
    if content.strip():
        init_path.write_text(content.strip() + "\n")
    else:
        init_path.touch()

    print(f"updated: {init_path}")
