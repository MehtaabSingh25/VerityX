from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.media_ingestion import router as media_router
from app.api.analysis_jobs import router as analysis_jobs_router
from app.api.similarity import router as similarity_router
from app.db.session import engine

app = FastAPI(
    title="VerityX API",
    description="Digital media forensics and provenance investigations",
    version="0.2.0",
)
app.include_router(media_router)
app.include_router(analysis_jobs_router)
app.include_router(similarity_router)


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    return {
        "status": "healthy",
        "service": "verityx-api",
        "database": "connected",
        "version": "0.2.0",
    }
