import argparse
from pathlib import Path

DOMAIN_SUBFOLDERS = (
    "routes",
    "schemas",
    "entities",
    "models",
    "repositories",
    "services",
)


def create_domain(name: str) -> None:
    domain_dir = Path(name)
    for sub in DOMAIN_SUBFOLDERS:
        (domain_dir / sub).mkdir(parents=True, exist_ok=True)
        (domain_dir / sub / "__init__.py").touch()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new DDD domain folder")
    parser.add_argument("name", help="Domain name, e.g. 'book'")
    args = parser.parse_args()

    create_domain(args.name)


if __name__ == "__main__":
    main()
