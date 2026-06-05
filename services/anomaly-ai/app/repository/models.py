from sqlalchemy import String, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class MetricSampleModel(Base):
    """ORM model = mapping to the MySQL table. SEPARATE from the domain entity.

    The MetricSample entity (domain) is pure; this model knows SQLAlchemy.
    Keeping them separate prevents the ORM from contaminating the domain.
    """
    __tablename__ = "metric_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    service: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped["DateTime"] = mapped_column(DateTime)