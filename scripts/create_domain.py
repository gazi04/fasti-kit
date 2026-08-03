from pathlib import Path
from typing import Annotated

import typer

DOMAIN_SUBFOLDERS = (
    "routes",
    "schemas",
    "entities",
    "models",
    "repositories",
    "services",
)


def create_domain(
    name: Annotated[str, typer.Argument(help="Domain name, e.g. 'book'")],
) -> None:
    """Scaffold a new DDD domain folder."""
    domain_dir = Path(name)
    for sub in DOMAIN_SUBFOLDERS:
        (domain_dir / sub).mkdir(parents=True, exist_ok=True)
        (domain_dir / sub / "__init__.py").touch()


def main() -> None:
    typer.run(create_domain)


if __name__ == "__main__":
    main()
