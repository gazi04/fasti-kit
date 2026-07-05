import argparse

from scripts.create_entity import create_entity
from scripts.create_model import create_model
from scripts.create_repository import create_repository
from scripts.create_route import create_route
from scripts.create_schema import create_schema
from scripts.create_service import create_service


def create_all(domain: str, name: str) -> None:
    create_entity(domain, name)
    create_model(domain, name)
    create_repository(domain, name)
    create_schema(domain, name)
    create_service(domain, name)
    create_route(domain, name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold entity/model/repository/schema/service/route in one go")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_all(args.domain, args.name)


if __name__ == "__main__":
    main()
