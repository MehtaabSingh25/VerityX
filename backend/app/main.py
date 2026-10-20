from fastapi import FastAPI

app = FastAPI(
    title="VerityX API",
    description="Digital media forensics and provenance investigations",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "verityx-api",
        "version": "0.1.0",
    }