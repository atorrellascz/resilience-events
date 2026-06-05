from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.metric_sample import MetricSample
from app.repository.models import MetricSampleModel


class SampleRepository:
    """Implements persistence on MySQL. Translates between domain and ORM model."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, sample: MetricSample) -> MetricSample:
        model = self._to_model(sample)
        self._session.add(model)
        await self._session.commit()
        return sample

    async def list(self, limit: int = 50) -> list[MetricSample]:
        stmt = (
            select(MetricSampleModel)
            .order_by(MetricSampleModel.recorded_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def ping(self) -> bool:
        """For /ready: does MySQL respond?"""
        try:
            await self._session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # ── Domain <-> ORM mapping (the price of keeping them separate, worth it) ──
    @staticmethod
    def _to_model(s: MetricSample) -> MetricSampleModel:
        return MetricSampleModel(
            id=s.id, service=s.service, kind=s.kind,
            value=s.value, recorded_at=s.recorded_at,
        )

    @staticmethod
    def _to_domain(m: MetricSampleModel) -> MetricSample:
        return MetricSample(
            id=m.id, service=m.service, kind=m.kind,
            value=m.value, recorded_at=m.recorded_at,
        )