from core.setting import Settings


def test_staging_counts_as_deployed_but_local_does_not() -> None:
    assert Settings.model_construct(environment="staging").is_deployed
    assert Settings.model_construct(environment="production").is_deployed
    assert not Settings.model_construct(environment="local").is_deployed
