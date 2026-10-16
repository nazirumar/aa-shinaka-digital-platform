# Monitoring & Observability — AA Shinaka Digital Business Platform

**Phase:** 12. This describes **what to watch** and **how alerts are wired**,
using only what the platform emits (structured logs + a liveness endpoint). No
proprietary monitoring dependency is required.

---

## 1. Signals available

| Signal | Where | Notes |
|---|---|---|
| Structurally logged requests/errors | stdout (JSON via `config/observability.py`) | collected by the container/platform log driver |
| `/healthz/` | `config/urls.py` | unauthenticated liveness probe used by nginx and `healthcheck.sh` |
| Celery events | worker logs + `celery inspect ping` | queue health |
| DB/Redis | host tooling | connection counts, replication lag (managed), memory |
| Payment review queue | finance dashboard | `requires_review` payments awaiting a human |
| Audit log | `dashboard.AuditLog` | who changed what, when |

Log format (one JSON object per line):

```json
{"level":"ERROR","time":"2026-10-16T09:12:04Z","logger":"django.request","message":"...","logger_name":"django.request"}
```

Application logs deliberately avoid customer PII (see `docs/DATA_PROTECTION.md`).

---

## 2. What to alert on

| Alert | Condition | Severity |
|---|---|---|
| Site down | `/healthz/` fails 3 checks in a row (or 2 consecutive 5xx probes) | P1 |
| Elevated 5xx | HTTP 5xx rate > 1% over 5 min | P1 |
| Web server down | Gunicorn process/container not running | P1 |
| DB unreachable | connection errors in logs for > 1 min | P1 |
| Backup failed | `backup.sh` exits non-zero, or no backup in 26 h | P1 |
| Disk > 85% | host metric | High |
| Celery worker down | `celery inspect ping` fails for 5 min | High |
| Beat not running | no `expire_orders` line in 24 h | High |
| Payment review backlog | `requires_review` count > 0 for > 24 h | Medium |
| Elevated 4xx on login | spike beyond normal | Medium (possible brute force) |
| TLS expiry | < 21 days | Medium |

---

## 2b. Liveness probe

`/healthz/` returns `200` when the app can serve requests. It is exempted from
HTTPS redirect on the internal network but is still reachable through nginx over
TLS. Keep it cheap: it must not touch the database on every call.

---

## 3. Wiring alerts (provider-agnostic)

1. **Uptime probe:** an external service (or a 1-minute cron on another host)
   running `BASE_URL=https://DOMAIN ./deploy/scripts/healthcheck.sh`; alert on
   non-zero exit.
2. **Log-based alerts:** the log platform (Loki/CloudWatch/Papertrail/etc.)
   matches `"level": "ERROR"` and `django.request` records; alert on rate.
3. **Host metrics:** node exporter / provider metrics for CPU, memory, disk.
4. **Celery/beat:** a 5-minute cron running `celery -A config inspect ping` and a
   daily check that beat produced its scheduled entries.

Every alert must name the owning channel. Do not route production alerts to a
personal device without a backup.

---

## 4. Log retention & privacy

- Application logs intentionally exclude PII, card data and secrets.
- Provider (Paystack) payloads are only stored as the recorded webhook event body
  needed for idempotency; they are not written to application logs.
- Retain logs ≥ 30 days for incident response; longer if the provider requires.

---

## 5. Dashboards (minimum)

- **Availability:** `/healthz/` success rate, 5xx rate, request latency p50/p95.
- **Business:** orders placed, payments settled, refunds, exports generated.
- **Queue:** Celery task latency and failure count.
- **Finance:** `requires_review` payments, unmatched bank transfers.
- **Infrastructure:** DB connections, Redis memory, disk usage, TLS days-left.

> **NOT VERIFIED in this environment:** no monitoring stack was provisioned, so
> no alert has been fired or paged. This document plus `healthcheck.sh` is the
> deliverable; wiring it on staging is a launch gate.
