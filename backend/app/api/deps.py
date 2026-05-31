"""FastAPI dependencies for the authoring API.

owner_sub is a stub returning a constant — replaced by OIDC in Phase 8.
"""

from __future__ import annotations

from typing import Annotated

from app.db import get_db
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Phase 8 will replace this with a real OIDC token dependency
ANONYMOUS_OWNER = "anonymous"


def get_current_owner() -> str:
    """Stub: returns a constant owner subject. Replaced by OIDC in Phase 8."""
    return ANONYMOUS_OWNER


DbDep = Annotated[AsyncSession, Depends(get_db)]
OwnerDep = Annotated[str, Depends(get_current_owner)]
