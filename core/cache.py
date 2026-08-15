import hashlib
import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from pydantic import TypeAdapter

from core.redis import redis
from core.setting import get_settings

T = TypeVar("T")


def _generate_cache_key(
    prefix: str, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> str:
    """Generates a deterministic cache key based on function arguments, ignoring class instances."""
    sig = inspect.signature(func)
    bound_args = sig.bind(*args, **kwargs)
    bound_args.apply_defaults()

    cache_kwargs = {}
    for key, value in bound_args.arguments.items():
        # Exclude instances like Service(self) or Repository(repo) from the cache key hash
        if key not in ("self", "cls", "repo", "db"):
            cache_kwargs[key] = str(value)

    arg_str = str(tuple(sorted(cache_kwargs.items())))
    arg_hash = hashlib.sha256(arg_str.encode()).hexdigest()

    return f"{prefix}:{func.__module__}:{func.__name__}:{arg_hash}"


def cache(
    ttl: int | None = None, tags: list[str] | None = None
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Cache-aside decorator. Intercepts method execution, checks Redis, and automatically
    serializes/deserializes response data into the function's return type hint.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)
        return_type = signature.return_annotation

        if return_type is inspect.Signature.empty:
            raise ValueError(
                f"Function '{func.__name__}' must have a return type annotation to be cached."
            )

        # TypeAdapter handles Pydantic Schemas, Dataclasses, and primitives out of the box
        adapter = TypeAdapter(return_type)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            settings = get_settings()
            actual_ttl = ttl if ttl is not None else settings.cache_default_ttl

            cache_key = _generate_cache_key(
                settings.cache_prefix, func, *args, **kwargs
            )
            cached_payload = await redis.get(cache_key)

            if cached_payload:
                return adapter.validate_json(cached_payload)

            # Cache Miss: Execute actual business logic
            result = await func(*args, **kwargs)

            # Serialize the Entity/Schema/Dict to JSON bytes
            json_data = adapter.dump_json(result)

            # Execute Redis writes atomically
            async with redis.pipeline() as pipe:
                pipe.setex(cache_key, actual_ttl, json_data)

                if tags:
                    for tag in tags:
                        tag_key = f"{settings.cache_prefix}:tags:{tag}"
                        pipe.sadd(tag_key, cache_key)
                        pipe.expire(tag_key, actual_ttl)

                await pipe.execute()

            return result

        return wrapper

    return decorator


async def invalidate_tags(*tags: str) -> None:
    """Wipes all cache keys associated with the provided tags."""
    if not tags:
        return

    settings = get_settings()
    keys_to_delete: set[bytes | str] = set()
    tag_keys = [f"{settings.cache_prefix}:tags:{tag}" for tag in tags]

    # 1. Fetch all cache keys belonging to these tags
    for tag_key in tag_keys:
        members = await redis.smembers(tag_key)
        keys_to_delete.update(members)

    # 2. Delete the individual cache entries and the tag sets themselves
    if keys_to_delete or tag_keys:
        async with redis.pipeline() as pipe:
            if keys_to_delete:
                pipe.delete(*keys_to_delete)
            if tag_keys:
                pipe.delete(*tag_keys)
            await pipe.execute()
