"""Gunicorn configuration for production.

Run::

    gunicorn config.wsgi:application --config deploy/gunicorn.conf.py

Every value is environment-driven so the same image scales without a rebuild.
Gunicorn sits behind nginx (or a managed platform such as Render), which
terminates TLS and sets the forwarded headers. The bind address comes from
``GUNICORN_BIND`` when set, otherwise from the platform's ``PORT`` (Render
defaults it to 10000), falling back to 8000 for local/Compose use.
"""

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND") or (f"0.0.0.0:{os.environ.get('PORT', '8000')}")
workers = int(os.environ.get("GUNICORN_WORKERS", (2 * multiprocessing.cpu_count()) + 1))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# Log to stdout/stderr so the container/platform log driver collects them.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Only trust proxy headers from the reverse proxy.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
