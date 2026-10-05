import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import documents, shipments
from app.config import settings
from app.database import engine
from app.models.shipment import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-assisted import document reading and risk checker.",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    Base.metadata.create_all(bind=engine)

    @application.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "version": settings.app_version}

    @application.get("/health/db", tags=["health"])
    def health_db() -> dict:
        from sqlalchemy import text

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}

    application.include_router(shipments.router, prefix="/api/v1")
    application.include_router(documents.router, prefix="/api/v1")

    @application.get("/")
    def root() -> dict:
        return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}

    return application


app = create_app()
