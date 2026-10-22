FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OpenCV's headless wheel avoids GUI dependencies; FFmpeg tools support common media codecs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-async.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt -r requirements-async.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
