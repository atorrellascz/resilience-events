from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_session
from app.repository.sample_repository import SampleRepository
from app.service.sample_service import SampleService
from app.api.schemas import CreateSampleRequest, SampleResponse

router = APIRouter(prefix="/api/samples", tags=["samples"])


# Composition of the chain per request: session -> repo -> service (FastAPI DI).
def get_service(session: AsyncSession = Depends(get_session)) -> SampleService:
    return SampleService(SampleRepository(session))


@router.post("", response_model=SampleResponse, status_code=201)
async def create_sample(
    req: CreateSampleRequest,
    svc: SampleService = Depends(get_service),
):
    sample = await svc.create(req.service, req.kind, req.value)
    return sample


@router.get("", response_model=list[SampleResponse])
async def list_samples(
    limit: int = 50,
    svc: SampleService = Depends(get_service),
):
    return await svc.list(limit)