from core.setting import Settings

PRIMARY = "postgresql+asyncpg://u:p@db.internal:5433/app"
REPLICA = "postgresql+asyncpg://u:p@replica.internal:6000/app"


def test_unset_replica_url_falls_back_to_the_primary() -> None:
    settings = Settings.model_construct(database_url=PRIMARY, database_replica_url=None)

    assert settings.get_replica_url == PRIMARY


def test_explicit_replica_url_is_used_as_given() -> None:
    settings = Settings.model_construct(
        database_url=PRIMARY, database_replica_url=REPLICA
    )

    assert settings.get_replica_url == REPLICA


def test_staging_counts_as_deployed_but_local_does_not() -> None:
    assert Settings.model_construct(environment="staging").is_deployed
    assert Settings.model_construct(environment="production").is_deployed
    assert not Settings.model_construct(environment="local").is_deployed
