"""Read-only endpoints for model version history."""

from __future__ import annotations

from app.api.deps import DbDep, OwnerDep
from app.models.model import ForgeModel, ModelVersion
from app.schemas.models import VersionRead
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

router = APIRouter(prefix="/api/models/{model_id}/versions", tags=["versions"])


async def _owned_model(model_id: str, owner: str, db: DbDep) -> ForgeModel:
    model = await db.get(ForgeModel, model_id)
    if model is None or model.owner_sub != owner:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.get("", response_model=list[VersionRead])
async def list_versions(
    model_id: str, db: DbDep, owner: OwnerDep
) -> list[VersionRead]:
    await _owned_model(model_id, owner, db)
    stmt = (
        select(ModelVersion)
        .where(ModelVersion.model_id == model_id)
        .order_by(ModelVersion.version_number.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [VersionRead.model_validate(r) for r in rows]


@router.get("/{version_number}", response_model=VersionRead)
async def get_version(
    model_id: str, version_number: int, db: DbDep, owner: OwnerDep
) -> VersionRead:
    await _owned_model(model_id, owner, db)
    stmt = select(ModelVersion).where(
        ModelVersion.model_id == model_id,
        ModelVersion.version_number == version_number,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionRead.model_validate(row)
