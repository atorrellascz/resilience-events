import asyncio

import pytest

from app.domain.metric_sample import MetricSample
from app.service.sample_service import SampleService


# FakeRepo is an in-memory test double for the repository the service depends on.
# Its methods are async because SampleService awaits them (add / list / ping).
# Same idea as the Go fakeRepo and the .NET Moq mock — no real MySQL involved.
class FakeRepo:
    def __init__(self, ping_result: bool = True):
        self.added: MetricSample | None = None     # last sample passed to add()
        self.last_limit: int | None = None         # last limit passed to list()
        self.list_result: list[MetricSample] = []   # what list() returns
        self._ping_result = ping_result             # what ping() returns

    async def add(self, sample: MetricSample) -> MetricSample:
        self.added = sample
        return sample

    async def list(self, limit: int) -> list[MetricSample]:
        self.last_limit = limit
        return self.list_result

    async def ping(self) -> bool:
        return self._ping_result


def test_create_valid_persists_and_returns():
    repo = FakeRepo()
    svc = SampleService(repo)

    sample = asyncio.run(svc.create("payments-api", "latency", 0.42))

    assert repo.added is not None, "expected repo.add to be called"
    assert sample.service == "payments-api"
    assert sample.kind == "latency"
    assert sample.value == 0.42
    assert sample.id                      # the domain factory generates a uuid
    assert sample.recorded_at is not None  # and a timestamp


def test_create_empty_service_raises_and_does_not_persist():
    repo = FakeRepo()
    svc = SampleService(repo)

    with pytest.raises(ValueError):
        asyncio.run(svc.create("   ", "latency", 1.0))  # blank service is invalid

    assert repo.added is None, "repo.add must NOT be called when validation fails"


def test_create_unknown_kind_normalizes_to_custom():
    repo = FakeRepo()
    svc = SampleService(repo)

    sample = asyncio.run(svc.create("svc", "bogus", 1.0))

    assert sample.kind == "custom"  # unknown kind -> safe default


@pytest.mark.parametrize(
    "requested, want_used",
    [
        (0, 50),     # invalid (0)  -> 50
        (-5, 50),    # negative     -> 50
        (999, 50),   # too high     -> 50
        (25, 25),    # valid        -> respected
    ],
)
def test_list_clamps_limit_to_safe_range(requested, want_used):
    repo = FakeRepo()
    svc = SampleService(repo)

    asyncio.run(svc.list(requested))

    assert repo.last_limit == want_used


def test_ready_propagates_ping_result():
    # Healthy DB -> True.
    assert asyncio.run(SampleService(FakeRepo(ping_result=True)).ready()) is True
    # Unhealthy DB -> False.
    assert asyncio.run(SampleService(FakeRepo(ping_result=False)).ready()) is False