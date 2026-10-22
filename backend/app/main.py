from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.media_ingestion import router as media_router
from app.api.analysis_jobs import router as analysis_jobs_router
from app.api.similarity import router as similarity_router
from app.api.reports import router as reports_router
from app.api.operations import router as operations_router
from app.db.session import engine
from app.core.observability import (
    RequestObservabilityMiddleware, configure_logging, render_metrics,
)
from redis import Redis
from redis.exceptions import RedisError
from app.core.config import settings
from app.core.security import require_api_key

configure_logging()

app = FastAPI(
    title="VerityX API",
    description="Digital media forensics and provenance investigations",
    version="0.2.0",
)
# Investigation creation/token rotation and operations require the service key.
# Resource endpoints use a narrower per-investigation token instead.
app.include_router(media_router)
app.include_router(analysis_jobs_router)
app.include_router(similarity_router)
app.include_router(reports_router)
app.include_router(operations_router, dependencies=[Depends(require_api_key)])
app.add_middleware(RequestObservabilityMiddleware)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, headers={"Content-Type": content_type})


@app.get("/health")
def health_check():
    database_status = "connected"
    redis_status = "connected"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        database_status = "unavailable"
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "database": database_status},
        ) from exc

    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        client.ping()
    except RedisError as exc:
        redis_status = "unavailable"
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "database": database_status,
                "redis": redis_status,
            },
        ) from exc
    finally:
        client.close()

    return {
        "status": "healthy",
        "service": "verityx-api",
        "database": database_status,
        "redis": redis_status,
        "version": "0.2.0",
    }

from app.observability import install_metrics
install_metrics(app)
