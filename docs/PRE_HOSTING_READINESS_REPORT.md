# Pre-Hosting Deployment Readiness Report

**Project:** AA Shinaka Digital Business Platform
**Repository:** <https://github.com/nazirumar/aa-shinaka-digital-platform>
**Target host (not yet purchased):** Hostinger KVM 2 — Ubuntu 24.04 LTS — Docker
**Report date:** 2026-10-16
**Base revision:** `27c7544` (Phase 15) plus the pre-hosting readiness changes
described below
**Author:** senior Django / DevOps review pass

> **Status: READY FOR A CONTROLLED STAGING DEPLOYMENT.**
> Not deployed. No VPS was purchased, no DNS was changed, no live Paystack
> credential exists, and no real customer transaction was created. Every claim
> below is backed by a command that was actually run; anything that needs a real
> host is explicitly marked **NOT VERIFIED**.

---

## 1. Scope and constraints

This pass audits the existing application and deployment configuration and closes
the gaps a pre-hosting review exposes. It honours the brief's prohibitions:

| Constraint | Honoured? |
|---|---|
| Do not deploy to a VPS | Yes — nothing was deployed. |
| Do not purchase hosting | Yes — no host exists. |
| Do not enable live payments | Yes — Paystack remains disabled / test-mode. |
| Do not create real customer transactions | Yes — only local dev data was read. |
| Do not claim success for unexecuted tests | Yes — see §5 for **NOT VERIFIED** items. |
| Preserve existing architecture and working features | Yes — additive changes only. |
| No oil & gas / multi-vendor / AgriTrade ERP features | Yes — none added. |
| No hardcoded categories, prices, inventory, achievements | Yes — none added. |

**Environmental limitation:** the local Docker **daemon is not available** (the
WSL backend is broken on this machine). Docker Compose can therefore be validated
**client-side** (`docker compose config`, which needs no daemon) but images cannot
be built and containers cannot be started here. This is the single biggest reason
for the items in §5.

---

## 2. Task-by-task result

| # | Task | Result |
|---|---|---|
| 1 | Audit existing app + deployment config | **PASSED** |
| 2 | Verify Phases 13 & 14 complete; report missing work | **PASSED** (no missing work found) |
| 3 | Production **and local-test** Compose configurations | **PASSED** (local stack added) |
| 4 | Configure Django, Gunicorn, PostgreSQL, Redis, Celery worker, Celery beat, Nginx | **PASSED** (config) / **NOT VERIFIED** (runtime) |
| 5 | Safe environment variable templates, no real credentials | **PASSED** |
| 6 | Persistent storage for PostgreSQL and uploads | **PASSED** (config) / **NOT VERIFIED** (survives a real `down`) |
| 7 | Private documents not accessible without authorisation | **PASSED** |
| 8 | Encrypted off-server backup + isolated restore test | **PASSED** (drill ran) / off-server copy **NOT VERIFIED** |
| 9 | Keep Paystack disabled / sandbox | **PASSED** |
| 10 | Verify email configuration and safe notification behaviour | **PASSED** |
| 11 | Review MFA, upload security, rate limiting, authorisation | **PASSED** |
| 12 | Verify CI security scans fail on vulnerabilities | **PASSED** (2 defects found & fixed) |
| 13 | Test database migrations and inventory concurrency | **PASSED** |
| 14 | Ruff, Django checks, automated tests, Compose validation | **PASSED** |
| 15 | Deployment runbook for Hostinger Ubuntu 24.04 | **PASSED** |
| 16 | Final pre-hosting readiness report | **PASSED** (this document) |

---

## 3. Defects found and fixed in this pass

The review was not a rubber stamp; it found and fixed real problems.

### 3.1 The CI dependency scan audited the wrong environment — **FIXED**

`uvx --from pip-audit==2.10.1 pip-audit --strict` (with **no target**) audits the
interpreter it runs under. Under `uvx` that is the *ephemeral tool environment*,
so the gate scanned **pip-audit's own 29 dependencies** and never the project's.

Evidence (real runs, 2026-10-16):

```
$ uvx --from pip-audit==2.10.1 pip-audit --strict -f json   # exactly as CI did
  uvx-audited deps = 29  (boolean-py, cachecontrol, cyclonedx-python-lib,
                          license-expression, markdown-it-py, …)

$ uv export --frozen --no-emit-project --format requirements-txt --no-hashes > r.txt
$ uvx --from pip-audit==2.10.1 pip-audit --strict -r r.txt -f json
  lock-audited deps = 38   ← the project's real dependency set
```

**Fix:** the workflow now exports the lock and audits it explicitly:

```yaml
- name: Export the locked requirements for auditing
  run: >-
    uv export --frozen --no-emit-project --format requirements-txt
    --no-hashes > requirements-audit.txt
- name: Dependency vulnerability scan (pip-audit, pinned)
  run: |
    set +e
    if [ ! -s requirements-audit.txt ]; then … exit 1; fi   # empty export = hard fail
    uvx --from pip-audit==2.10.1 pip-audit --strict --progress-spinner off \
      -r requirements-audit.txt > audit.log 2>&1
    …
```

### 3.2 The scan mis-classified a real finding as a tool failure — **FIXED**

pip-audit's real summary wording is **"Found 8 known vulnerabilities in 1
package"**. The old regex was `found [0-9]+ vulnerabilit`, which does **not**
match because the word "known" intervenes, so a genuine finding was labelled
"network/service problem". The step still exited non-zero (the gate held), but it
pointed the responder at the wrong fix.

**Fix:** the regex now accepts the real wording, and the clean phrase is excluded
so a `--strict` scan abort is not mislabelled as a finding:

```sh
if grep -qiE "found [0-9]+ (known )?vulnerabilit|vulnerabilit(y|ies) (were )?found" audit.log \
   && ! grep -qi "no known vulnerabilities found" audit.log; then
```

### 3.3 `deploy/.env.local.example` would have been git-ignored — **FIXED**

The repo's `.gitignore` uses a broad `.env.*` rule with explicit whitelists for
the production and staging templates. The new local template needed its own
whitelist or it would silently never be committed. Caught via `git status` and
fixed with `!deploy/.env.local.example`.

### 3.4 Missing deliverable: a **local-test** Compose stack — **ADDED**

Task 3 asked for production *and local-test* Compose configurations. Only
production and staging existed. A local stack was added (§4.3) so the production
shape can be exercised before any host exists.

---

## 4. What changed

### 4.1 CI hardening
`.github/workflows/ci.yml` — see §3.1/§3.2.

### 4.2 New regression tests
* `tests/test_ci_security_gate.py` — 9 tests pinning the scan target, the
  un-waivable failure modes, the finding-classification behaviour against
  pip-audit's real wording, full-SHA action pinning and the mandatory jobs.
* `tests/test_phase15_deploy.py` — +12 tests for the local stack (project
  isolation, ports, settings selection, capture inbox, env template safety,
  local nginx default-deny, and `render_nginx.sh --local`).

### 4.3 Local-test stack (new)
| File | Purpose |
|---|---|
| `deploy/docker-compose.local.yml` | Thin overlay: project `aa-shinaka-local`, `config.settings.local`, Mailpit inbox. |
| `deploy/.env.local.example` | Throwaway local values; HTTP on 8080, Mailpit SMTP, test-mode Paystack. |
| `config/settings/local.py` | Production settings with **only** the plain-HTTP controls relaxed. |
| `deploy/nginx/local.conf` | HTTP-only site, mirroring the production media default-deny. |
| `deploy/scripts/render_nginx.sh` | `--local` mode renders the above into the mounted conf.d. |

The local stack deliberately does **not** weaken production: `DEBUG` stays
`False`, Redis is the real cache, the upload-scan policy is the real one, and
Paystack stays test-mode. `test_production_and_staging_never_select_the_local_settings`
plus the fact that no other Compose file references `config.settings.local`
keeps the plain-HTTP allowances unreachable outside a laptop.

---

## 5. NOT VERIFIED (requires a real host or the Docker daemon)

These are **host-execution gates**. They are not failures; they simply could not
be executed here, and they are listed so nothing is mistaken for proven.

| Item | Why not verified |
|---|---|
| Image build (`docker build`) and `docker compose up` | No Docker daemon on this machine. |
| `nginx -t` against the rendered config in the container | Same. |
| PostgreSQL/Redis/volume persistence across `docker compose down` | Same. |
| TLS issuance and HTTPS redirect end-to-end | No domain, no host. |
| SSH/ufw/fail2ban hardening applied to a real host | No host. |
| Off-server backup upload (rclone to real remote) | No remote/credentials. |
| `pip-audit` **in GitHub Actions** (this machine's run is a faithful local replica) | CI not executed here. |
| Real Paystack *test* transaction, webhook signature, refund, reconciliation | No test keys / no network to Paystack. |
| Verified 37-state / 774-LGA import | No verified dataset bundled; dev DB is partial. |
| Staging performance and accessibility runs | No staging host. |
| Business-content sign-off | Owner input required. |

The Docker Compose **model** (networks, ports, volumes, env-file selection,
service wiring) *is* verified for all three environments via `docker compose config`.

---

## 6. Evidence — commands run and real results

### 6.1 Code quality and tests
```
uv run ruff check .                         → All checks passed!
uv run ruff format --check .                → 330 files already formatted
uv run python manage.py check               → System check identified no issues
uv run python manage.py makemigrations --check --dry-run → No changes detected
uv run pytest -q                            → 926 passed  (was 905 before this pass)
```

Full-suite baseline before this pass was 905; +12 (phase15 deploy) and +9 (CI gate)
gives 926.

### 6.2 Compose validation (client-side, no daemon)
```
docker compose --env-file deploy/.env.production.example -f deploy/docker-compose.yml config        → exit 0
… -f deploy/docker-compose.yml -f deploy/docker-compose.staging.yml config                          → exit 0
… -f deploy/docker-compose.yml -f deploy/docker-compose.local.yml  config                           → exit 0
```
Local render confirms: project `aa-shinaka-local`, ports `8080`/`8443`,
`DJANGO_SETTINGS_MODULE=config.settings.local` on all four app services, Mailpit
present and publishing only `8025`, and **zero** references to `config.settings.prod`.

### 6.3 Local settings module actually boots (task 3/4)
```
$ DJANGO_SETTINGS_MODULE=config.settings.local python manage.py check
ENVIRONMENT=local  DEBUG=False  SESSION_COOKIE_SECURE=False  CSRF_COOKIE_SECURE=False
SECURE_SSL_REDIRECT=False  SECURE_HSTS_SECONDS=0
CSRF_TRUSTED_ORIGINS=['http://localhost:8080','http://127.0.0.1:8080']
ALLOWED_HOSTS=['localhost','127.0.0.1']  PAYSTACK_LIVE_MODE=False
UPLOAD_SCAN_ENFORCEMENT=log  EMAIL_HOST=mailpit
System check identified no issues (0 silenced).  → CHECK OK
PROD COOKIES STILL SECURE: True   (prod.py still hard-sets SESSION/CSRF_COOKIE_SECURE=True)
```

### 6.4 Task 7 — private documents refused anonymously
Live dev server + `BASE_URL=http://127.0.0.1:8111 ./deploy/scripts/smoke_test.sh`:
```
23 checks, 0 failures
/invoices/ → 302   /invoices/AA-000001/pdf/ → 302   /receipts/AA-000001/pdf/ → 302
/payments/ → 302   /orders/ → 302   /account/export/ → 302   /account/support/ → 302
/media/quarantine/probe.txt → 404   /media/invoices/probe.pdf → 404
/media/export-documents/probe.pdf → 404   /media/payment-evidence/probe.jpg → 404
/healthz/ reports database ok
```
The nginx edge default-deny for `/media/` is independently asserted by
`test_nginx_defaults_to_deny_for_all_media` and the matching local-stack test.

### 6.5 Task 8 — encrypted off-server backup + isolated restore drill
Real isolated drill against the local PostgreSQL (source = dev DB, target =
`aa_shinaka_restore_drill`):
```
1/4 Dumping source database            dump size: 920K
2/4 Recreating isolated target database
3/4 Restoring into aa_shinaka_restore_drill   restore completed in 13s
4/4 Verifying restored schema
    django_migrations rows: 54
    accounts_user rows:     16
Drill OK. Total wall time: 19s (RTO input).    exit 0
```
The drill DB was dropped afterwards. `backup_docker.sh` encrypts with age (gpg
fallback) and **fails closed** if no recipient is set, and **fails closed** if no
rclone remote is configured — an unencrypted/on-host-only dump is refused.

### 6.6 Task 9 — Paystack stays test-mode
```
uv run pytest tests/test_paystack_test_mode.py tests/test_staging_settings.py \
               tests/test_production_security.py -q     → 42 passed
```
Production and staging templates pin `PAYSTACK_ENABLED=False`,
`PAYSTACK_LIVE_MODE=False`, and contain no `sk_live_`/`pk_live_` value. The
staging guard refuses a live key or live mode at import time.

### 6.7 Task 10 — email + notification behaviour
```
uv run pytest tests/test_notifications.py tests/test_email_verification.py \
               tests/test_upload_security.py tests/test_mfa.py \
               tests/test_permissions.py tests/test_security.py tests/test_support.py -q
  → 114 passed
```
`config/settings/prod.py` rejects `console`/`locmem`/`dummy` email backends and
requires `EMAIL_HOST` to be a real host (not `localhost`) — a misconfigured deploy
cannot boot. Notification delivery is fail-safe: `_deliver_many` logs and never
breaks the originating flow; `deliver_delivery` records `FAILED`; the Celery task
retries with exponential backoff.

### 6.8 Task 12 — CI security gate
The pip-audit decision logic was replicated and run against **real captured
pip-audit output** plus synthetic cases:
```
ok  real-vuln-log (Found 8 known vulnerabilities…)  exit=1  VULNERABILITY-FINDING
ok  real-clean-log (project lock, 38 pkgs)          exit=0  CLEAN
ok  tool-failure / empty-log-fail / strict-abort     exit=1  TOOL-FAILURE
All pip-audit failure-mode cases behave as intended.
```
A real audit of the project lock reports **No known vulnerabilities found**
(38 packages, exit 0).

### 6.9 Task 13 — migrations + concurrency
```
uv run python manage.py makemigrations --check --dry-run → No changes detected
uv run pytest tests/test_inventory_concurrency.py -q     → 18 passed
```

### 6.10 Task 14 — assets
```
npm run build:css   → Done   (static/css/app.css produced)
bash -n on all 18 deploy shell scripts → 0 syntax failures
```

---

## 7. Architecture preserved

* No new Python or JavaScript dependencies were added (`uv.lock` and
  `package.json` are untouched; DRF remains deferred).
* No models or migrations changed.
* No existing service, view, or template was modified.
* The service-layer convention (`services.py` writes, `selectors.py` reads) is
  untouched; the only new Python module is a settings profile.

---

## 8. Recommendation

**Proceed to a controlled staging deployment** on a Hostinger KVM 2 (Ubuntu
24.04), following `docs/HOSTINGER_VPS_DEPLOYMENT.md`, using
`config.settings.staging` with **test-mode** Paystack. Treat §5 as the checklist
to convert into real results on that host. **Do not** enable live Paystack, point
public DNS at the host, or load real customer data until the staging gates pass
and the owner approves (see `docs/PRODUCTION_LAUNCH_APPROVAL.md`).

No production launch is authorised by this report.
