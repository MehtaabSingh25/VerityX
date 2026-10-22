"""Entrypoint for the durable Celery outbox relay service."""
from app.core.observability import configure_logging
from app.outbox import run_dispatch_loop


if __name__ == "__main__":
    configure_logging()
    run_dispatch_loop()
