from datetime import datetime
from pydantic import BaseModel, Field


class CreateSampleRequest(BaseModel):
    """Input DTO — Pydantic validates automatically (equivalent to FluentValidation)."""
    service: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=50)
    value: float


class SampleResponse(BaseModel):
    """Output DTO — separate from the domain entity."""
    id: str
    service: str
    kind: str
    value: float
    recorded_at: datetime