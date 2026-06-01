"""FastAPI dependencies for the authoring API."""

from __future__ import annotations

from typing import Annotated

from app.auth.oidc import get_current_owner as _get_current_owner
from app.db import get_db
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export so callers can import from one place and tests can override here.
get_current_owner = _get_current_owner

DbDep = Annotated[AsyncSession, Depends(get_db)]
OwnerDep = Annotated[str, Depends(get_current_owner)]
