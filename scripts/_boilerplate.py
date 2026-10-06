import ast
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.prompt import Prompt

console = Console()

# Boundary between the last capital of an acronym run and the Capitalized word that
# follows it, e.g. "HTTPServer" -> boundary lands before the "S" in "Server".
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
# Boundary between a lowercase letter/digit and the uppercase letter that follows it,
# e.g. "userProfile" -> boundary before "P".
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

RESERVED_DOMAINS = {"alembic", "core", "docs", "main", "scripts", "tests"}

TYPE_MAPPING = {
    "str": {"py": "str", "sqla": "String", "pydantic": "str"},
    "int": {"py": "int", "sqla": "Integer", "pydantic": "int"},
    "float": {"py": "float", "sqla": "Float", "pydantic": "float"},
    "bool": {"py": "bool", "sqla": "Boolean", "pydantic": "bool"},
    "uuid": {"py": "uuid.UUID", "sqla": "UUID(as_uuid=True)", "pydantic": "uuid.UUID"},
}

MODELS_MANIFEST = Path("core/models.py")
API_VERSIONS = Path("core/api_versions.py")
PYPROJECT = Path("pyproject.toml")


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


def validate_domain(domain: str) -> None:
    if not _IDENTIFIER.match(domain):
        raise ValueError(
            f"Domain '{domain}' must be lowercase snake_case "
            "(letters, digits, underscores), e.g. 'inventory'."
        )
    if domain in RESERVED_DOMAINS:
        raise ValueError(f"'{domain}' is a reserved top-level name, not a domain.")


def resolve_names(domain: str, name: str) -> tuple[str, str]:
    """Validate a domain/entity pair and return the entity's (snake, Pascal) names."""
    validate_domain(domain)
    snake = to_snake_case(name)
    if not _IDENTIFIER.match(snake):
        raise ValueError(
            f"Name '{name}' can't become a Python identifier, e.g. use 'order_item'."
        )
    return snake, to_pascal_case(name)


def require_domain(domain: str) -> None:
    if not Path(domain).is_dir():
        raise ValueError(
            f"Domain '{domain}' does not exist. "
            f"Run `uv run create-domain -d {domain}` first."
        )


@contextmanager
def cli_errors() -> Iterator[None]:
    try:
        yield
    except ValueError as err:
        console.print(f"[bold red]ERROR:[/bold red] {err}")
        raise typer.Exit(1) from err


def ask_domain(domain: str | None) -> str:
    return domain or Prompt.ask(
        "[bold blue]Enter domain name[/bold blue] (e.g., inventory)"
    )


def ask_name(name: str | None, kind: str) -> str:
    return name or Prompt.ask(
        f"[bold blue]Enter {kind} name[/bold blue] (e.g., product)"
    )


def ask_fields(fields: str | None) -> str:
    if fields is not None:
        return fields
    console.print("[dim]Supported types: str, int, float, bool, uuid[/dim]")
    return Prompt.ask(
        "[bold blue]Enter fields[/bold blue] (e.g., title:str,price:float) or leave blank",
        default="",
    )


def write_new_file(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"skip: {path} already exists")
        return False
    path.write_text(content)
    print(f"created: {path}")
    return True


def _module_names(tree: ast.Module) -> tuple[dict[str, list[str]], list[str]]:
    imports: dict[str, list[str]] = {}
    all_names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            imports.setdefault(node.module, []).extend(a.name for a in node.names)
        elif (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, ast.List | ast.Tuple)
        ):
            all_names = [
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return imports, all_names


def update_init(init_path: Path, module: str, symbols: list[str]) -> Path:
    """Merge `from .module import symbols` into a layer's `__init__.py`.

    Parsed with `ast` rather than line regexes so a file already reformatted by
    ruff (wrapped imports, multi-line `__all__`) is read back without losing names.
    """
    init_path.parent.mkdir(parents=True, exist_ok=True)

    imports: dict[str, list[str]] = {}
    all_names: list[str] = []
    if init_path.exists():
        imports, all_names = _module_names(ast.parse(init_path.read_text()))

    existing = imports.setdefault(module, [])
    for symbol in symbols:
        if symbol not in existing:
            existing.append(symbol)
        if symbol not in all_names:
            all_names.append(symbol)

    lines = [
        f"from .{mod} import {', '.join(names)}"
        for mod, names in imports.items()
        if names
    ]
    content = "\n".join(lines) + "\n"
    if all_names:
        content += f"\n__all__ = [{', '.join(repr(n) for n in all_names)}]\n"

    init_path.write_text(content)
    print(f"updated: {init_path}")
    return init_path


def _imported(tree: ast.Module) -> set[tuple[str | None, str]]:
    found: set[tuple[str | None, str]] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            found.update((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update((None, alias.name) for alias in node.names)
    return found


def merge_imports(content: str, imports: list[str]) -> str:
    """Insert any `imports` missing from `content` right after its top import block."""
    tree = ast.parse(content)
    present = _imported(tree)
    missing = [line for line in imports if not _imported(ast.parse(line)) <= present]
    if not missing:
        return content

    lines = content.splitlines()
    import_nodes = [
        node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)
    ]
    if import_nodes:
        insert_at = import_nodes[-1].end_lineno or 0
    elif (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
    ):
        insert_at = tree.body[0].end_lineno or 0
        missing = ["", *missing]
    else:
        insert_at = 0

    new_lines = lines[:insert_at] + missing + lines[insert_at:]
    return "\n".join(new_lines).strip("\n") + "\n"


def register_model(domain: str, model_class: str) -> list[Path]:
    if not MODELS_MANIFEST.exists():
        console.print(
            f"[yellow]{MODELS_MANIFEST} not found. Add this line to your models "
            f"manifest yourself:[/yellow] from {domain}.models import {model_class}"
        )
        return []

    content = MODELS_MANIFEST.read_text()
    tree = ast.parse(content)
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == f"{domain}.models"
            and any(alias.name == model_class for alias in node.names)
        ):
            return []

    line = f"from {domain}.models import {model_class}  # noqa: F401"
    MODELS_MANIFEST.write_text(content.rstrip("\n") + "\n" + line + "\n")
    console.print(f"[green]wired:[/green] {model_class} into {MODELS_MANIFEST}")
    return [MODELS_MANIFEST]


def register_router(domain: str, router_var: str) -> list[Path]:
    import_line = f"from {domain}.routes import {router_var}"
    include_line = f"v1_router.include_router({router_var})"
    manual = (
        f"[yellow]Couldn't wire {router_var} automatically. Add these to "
        f"{API_VERSIONS} yourself:[/yellow]\n    {import_line}\n    {include_line}"
    )

    if not API_VERSIONS.exists():
        console.print(manual)
        return []

    lines = API_VERSIONS.read_text().splitlines()
    if import_line in lines and include_line in lines:
        return []

    import_idx = [
        i for i, line in enumerate(lines) if line.startswith(("from ", "import "))
    ]
    include_idx = [
        i
        for i, line in enumerate(lines)
        if line.startswith("v1_router.include_router(")
    ]
    if not import_idx or not any(line.startswith("v1_router =") for line in lines):
        console.print(manual)
        return []

    if include_line not in lines:
        at = include_idx[-1] + 1 if include_idx else len(lines)
        lines.insert(at, include_line)
    if import_line not in lines:
        lines.insert(import_idx[-1] + 1, import_line)

    API_VERSIONS.write_text("\n".join(lines) + "\n")
    console.print(f"[green]wired:[/green] {router_var} into {API_VERSIONS}")
    return [API_VERSIONS]


def _list_values(literal: str) -> list[str]:
    return re.findall(r'"([^"]*)"', literal)


def _add_to_list(
    content: str, key: str, value: str, must_contain: str | None = None
) -> str:
    pattern = re.compile(rf"^({re.escape(key)} = )\[([^\]\n]*)\](.*)$", re.MULTILINE)
    for match in pattern.finditer(content):
        values = _list_values(match.group(2))
        if must_contain is not None and not any(must_contain in v for v in values):
            continue
        if value in values:
            return content
        rendered = ", ".join(f'"{v}"' for v in [*values, value])
        replacement = f"{match.group(1)}[{rendered}]{match.group(3)}"
        return content[: match.start()] + replacement + content[match.end() :]
    return content


def _pyproject_targets(domain: str) -> list[tuple[str, str, str | None]]:
    return [
        ("include", f"{domain}*", None),
        ("known-first-party", domain, None),
        ("source", domain, None),
        ("known_first_party", domain, None),
        ("root_packages", domain, None),
        ("containers", domain, None),
        ("source_modules", f"{domain}.entities", ".entities"),
    ]


def _dig(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        data = data.get(key, {})
    return data or []


def _pyproject_lists(data: dict[str, Any]) -> list[list[str]]:
    tool = data.get("tool", {})
    contracts = _dig(tool, "importlinter", "contracts")
    layers = next((c for c in contracts if c.get("type") == "layers"), {})
    entities = next(
        (
            c
            for c in contracts
            if any(m.endswith(".entities") for m in c.get("source_modules", []))
        ),
        {},
    )
    return [
        _dig(tool, "setuptools", "packages", "find", "include"),
        _dig(tool, "ruff", "lint", "isort", "known-first-party"),
        _dig(tool, "coverage", "run", "source"),
        _dig(tool, "deptry", "known_first_party"),
        _dig(tool, "importlinter", "root_packages"),
        layers.get("containers", []),
        entities.get("source_modules", []),
    ]


def register_pyproject(domain: str) -> list[Path]:
    """Add `domain` to every pyproject.toml list that enumerates the domains.

    Edited as text so comments and layout survive, then re-parsed: if the result
    doesn't parse or any list still lacks the domain, nothing is written.
    """
    targets = _pyproject_targets(domain)
    manual = (
        f"[yellow]Couldn't update {PYPROJECT} automatically. Add '{domain}' to: "
        "setuptools include, ruff known-first-party, coverage source, deptry "
        "known_first_party, importlinter root_packages, the layers contract's "
        f"containers, and '{domain}.entities' to the entities contract.[/yellow]"
    )

    if not PYPROJECT.exists():
        console.print(manual)
        return []

    original = PYPROJECT.read_text()
    content = original
    for key, value, must_contain in targets:
        content = _add_to_list(content, key, value, must_contain)

    try:
        lists = _pyproject_lists(tomllib.loads(content))
    except tomllib.TOMLDecodeError:
        console.print(manual)
        return []

    expected = [value for _, value, _ in targets]
    if any(value not in found for value, found in zip(expected, lists, strict=True)):
        console.print(manual)
        return []

    if content == original:
        return []

    PYPROJECT.write_text(content)
    console.print(f"[green]wired:[/green] '{domain}' into {PYPROJECT}")
    return [PYPROJECT]


def format_paths(paths: list[Path]) -> None:
    """Run ruff's autofix and formatter over generated files."""
    targets = sorted({str(p) for p in paths if p.suffix == ".py" and p.exists()})
    if not targets:
        return

    for args in (["check", "--fix", "--quiet"], ["format", "--quiet"]):
        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "ruff", *args, *targets],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            console.print(f"[yellow]Skipped ruff ({exc}).[/yellow]")
            return
        if "No module named ruff" in result.stderr:
            console.print("[yellow]ruff is not installed; skipped formatting.[/yellow]")
            return
        if result.returncode != 0:
            console.print(result.stdout + result.stderr)
