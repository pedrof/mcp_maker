from fastapi import APIRouter

router = APIRouter()


@router.get("/livez")
async def livez() -> dict[str, str]:
    """Liveness probe — process alive, no external deps checked.

    Distinct from /health (which does SELECT 1) so a transient DB blip
    doesn't trigger a liveness-failure crashloop restart.
    """
    return {"status": "ok"}
