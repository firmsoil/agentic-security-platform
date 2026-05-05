"""Entrypoint: `asp-api` runs uvicorn against the FastAPI app."""

from __future__ import annotations

import uvicorn

from asp_api.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "asp_api.main:app",
        host=settings.asp_api_host,
        port=settings.asp_api_port,
        log_level=settings.asp_api_log_level.lower(),
        reload=(settings.asp_api_environment == "development"),
    )


if __name__ == "__main__":
    main()
