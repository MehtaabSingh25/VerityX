"""Run API, Celery worker and outbox relay in one Render web service."""
import os
import signal
import subprocess
import sys
import time

commands = [
    [sys.executable, "-m", "celery", "-A", "app.celery_app:celery_app", "worker", "--loglevel=INFO", "--pool=prefork", "--concurrency=1"],
    [sys.executable, "-m", "app.outbox_dispatcher"],
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", os.getenv("PORT", "10000"), "--proxy-headers"],
]
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)

processes = []
def stop(_signum, _frame):
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.time() + 20
    for process in processes:
        try:
            process.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            process.kill()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
for command in commands:
    processes.append(subprocess.Popen(command))
while True:
    for process in processes:
        code = process.poll()
        if code is not None:
            stop(signal.SIGTERM, None)
            raise SystemExit(code)
    time.sleep(1)
