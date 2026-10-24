"""Runner for the MEDSHIELD AI FastAPI Server."""

import uvicorn
from medshield.config import settings

if __name__ == "__main__":
    print(f"Starting MEDSHIELD AI API Server on {settings.api_host}:{settings.api_port}...")
    uvicorn.run(
        "medshield.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=(settings.app_env == "development"),
        log_level=settings.log_level.lower(),
    )
