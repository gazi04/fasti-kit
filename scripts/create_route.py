import argparse
from pathlib import Path

from scripts._boilerplate import to_pascal_case, to_snake_case, update_init, write_new_file

TEMPLATE = '''from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from {domain}.entities.{snake} import {class_name}
from {domain}.repositories.{snake}_repository import {class_name}Repository
from {domain}.schemas.{snake}_schema import Create{class_name}Request, Update{class_name}Request, {class_name}Response
from {domain}.services.{snake}_service import {class_name}Service

# Uncomment to require an authenticated caller (see auth/dependencies.py):
# from authx import TokenPayload
# from auth.dependencies import auth

{route_var} = APIRouter(prefix="/{prefix}", tags=["{tag}"])


@{route_var}.post("/create", response_model={class_name}Response)
async def create_{snake}(data: Create{class_name}Request, db: AsyncSession = Depends(get_db)) -> {class_name}:
    service = {class_name}Service({class_name}Repository(db))
    return await service.create(data)


@{route_var}.get("/get/{{id}}", response_model={class_name}Response)
async def get_{snake}(id: UUID, db: AsyncSession = Depends(get_db)) -> Optional[{class_name}]:
    service = {class_name}Service({class_name}Repository(db))
    record = await service.get(id)

    if record is None:
        raise HTTPException(404, "{class_name} not found")

    return record


@{route_var}.patch("/update/{{id}}", response_model={class_name}Response)
async def update_{snake}(
    id: UUID,
    data: Update{class_name}Request,
    db: AsyncSession = Depends(get_db),
    # payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers'])),
) -> Optional[{class_name}]:
    service = {class_name}Service({class_name}Repository(db))

    try:
        record = await service.update(id, data)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    if record is None:
        raise HTTPException(404, "{class_name} not found")

    return record


@{route_var}.delete("/delete/{{id}}")
async def delete_{snake}(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    # payload: TokenPayload = Depends(auth.token_required(type='access', locations=['headers'])),
):
    service = {class_name}Service({class_name}Repository(db))
    deleted = await service.delete(id)

    if deleted is None:
        raise HTTPException(404, "{class_name} not found")

    return {{"message": "{class_name} deleted"}}
'''


def create_route(domain: str, name: str) -> None:
    snake = to_snake_case(name)
    pascal = to_pascal_case(name)
    route_var = f"{snake}_router"

    layer_dir = Path(domain) / "routes"
    file_path = layer_dir / f"{route_var}.py"

    write_new_file(
        file_path,
        TEMPLATE.format(domain=domain, snake=snake, class_name=pascal, route_var=route_var, prefix=snake, tag=pascal),
    )
    update_init(layer_dir / "__init__.py", route_var, [route_var])

    print(
        f"reminder: mount the new router in main.py:\n"
        f"    from {domain}.routes import {route_var}\n"
        f"    app.include_router({route_var}, prefix='/api')"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new route")
    parser.add_argument("domain")
    parser.add_argument("name")
    args = parser.parse_args()

    create_route(args.domain, args.name)


if __name__ == "__main__":
    main()
