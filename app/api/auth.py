"""API-key protection for routes that spend the GitHub token or the LLM."""

import hmac

from fastapi import Header, HTTPException

from app.config import get_settings

API_KEY_HEADER = "X-API-Key"


def check_api_key(provided: str | None) -> None:
    """Raise 503 when no key is configured, 401 when the header does not match."""
    settings = get_settings()
    if not settings.api_key:
        raise HTTPException(
            status_code=503,
            detail="This endpoint is disabled until API_KEY is configured on the server.",
        )
    if not provided or not hmac.compare_digest(provided.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=401, detail=f"A valid {API_KEY_HEADER} header is required.")


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> None:
    check_api_key(x_api_key)
