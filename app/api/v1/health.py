from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint returning application status."""
    return {"status": "ok"}
