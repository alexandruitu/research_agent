from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health():
    """Public liveness probe for the container health check. Touches nothing and reveals nothing."""
    return {"status": "ok"}
