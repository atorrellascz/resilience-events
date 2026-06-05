from app.domain.metric_sample import MetricSample
from app.repository.sample_repository import SampleRepository


class SampleService:
    """Business logic. Depends on the repository (injected), not on MySQL directly."""

    def __init__(self, repo: SampleRepository):
        self._repo = repo

    async def create(self, service: str, kind: str, value: float) -> MetricSample:
        # The domain factory validates and creates a sample that is valid by construction.
        sample = MetricSample.create(service, kind, value)
        return await self._repo.add(sample)

    async def list(self, limit: int = 50) -> list[MetricSample]:
        # Defensive cap: never an unbounded query.
        if limit < 1 or limit > 200:
            limit = 50
        return await self._repo.list(limit)

    async def ready(self) -> bool:
        return await self._repo.ping()