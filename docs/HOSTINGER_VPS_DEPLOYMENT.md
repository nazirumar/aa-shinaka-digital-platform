# Hostinger VPS Deployment Guide — AA Shinaka Digital Business Platform

**Phase:** 15 (Hostinger KVM VPS, Ubuntu 24.04 LTS, Docker Compose)
**Status:** configuration and runbook — **not executed against a real server**
**Companion:** [`PHASE_15_HOSTINGER_REPORT.md`](PHASE_15_HOSTINGER_REPORT.md) (what
was actually verified), [`PRODUCTION_LAUNCH_APPROVAL.md`](PRODUCTION_LAUNCH_APPROVAL.md)
(go/no-go), [`PRODUCTION_RUNBOOK.md`](PRODUCTION_RUNBOOK.md),
[`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md), [`../../deploy/README.md`](../../deploy/README.md).

> **Read this first.** Nothing in this document has been run against a real
> Hostinger server. No VPS was provisioned, no DNS record was created or
> changed, no live Paystack credential was used and no production data was
> migrated by this phase. Every step below is the procedure an authorised
> operator must execute. Where a step cannot be proven from a development
> machine it is marked **NOT VERIFIED**.

---

## 0. What the owner must supply before anything else

| Item | Required for | Notes |
|---|---|---|
| Hostinger KVM VPS (Ubuntu 24.04, ≥ 4 GB RAM, ≥ 80 GB disk, 1 dedicated IPv4) | everything | 2 GB RAM will OOM during the image build (Tailwind + Gunicorn). |
| A public **SSH private key** whose public half is on the VPS | SSH access | Never paste the private key into a chat, ticket or this repository. |
| The **production domain** (and the person authorised to create DNS records) | domain/HTTPS | The domain placeholder in the templates must be replaced only here. |
| SMTP credentials (or a transactional email provider) | email | Registration, password reset and notifications all require real delivery. |
| **Paystack TEST** keys (optional at this stage) | payment verification | Live keys are refused by the platform until a separate owner approval. |
| A **verified** Nigeria locations dataset | reference data | 37 states + 774 LGAs. No dataset is bundled and none may be invented. |
| An off-server backup destination (Backblaze B2 / Hetzner Box / S3-compatible) | backups | Backups must leave this host. |

Nothing in this guide can proceed to production launch until the owner signs off
`docs/BUSINESS_CONTENT_APPROVAL_CHECKLIST.md`.

---

## 1. Hostinger VPS setup

1. In the Hostinger panel, create a **KVM VPS** with **Ubuntu 24.04 LTS**.
2. Set the **root password** from the panel, then immediately switch to key-based
   authentication (§2) and disable password login.
3. Note the server's **IPv4 address** — hereafter `<VPS_IP>`.
4. Optional but recommended: take a snapshot once the platform is running, so you
   have a last-resort rollback. **A snapshot is not a backup** — it is not
   off-server and not point-in-time consistent for PostgreSQL. See §14.
5. Attach the volume plan that matches your retention needs (80 GB minimum;
   PostgreSQL data, media uploads and Docker layers all grow).

Verify the instance from Hostinger's console (VNC) before touching SSH, so that a
network mistake cannot lock you out.

---

## 2. SSH access

```bash
# From your machine, as root:
ssh -i ~/.ssh/id_ed25519 root@<VPS_IP>
```

Then install your key properly and stop using the password:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# paste your PUBLIC key only
echo 'ssh-ed25519 AAAA... you@laptop' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Create the non-root administrative user and harden the host in one step
(**dry-run by default** — review the output, then re-run with `--apply`):

```bash
./deploy/scripts/host_hardening.sh --admin-user aashinaka --ssh-key ~/.ssh/authorized_keys
# happy with the plan:
sudo ./deploy/scripts/host_hardening.sh --admin-user aashinaka --ssh-key /path/to/id_ed25519.pub --apply
```

What it configures, and what it deliberately will **not** do:

| Setting | Value |
|---|---|
| Administrative user | non-root, in `sudo`, passwordless sudo for deployment |
| sshd | `PermitRootLogin no`, `PasswordAuthentication no`, `PermitEmptyPasswords no`, `MaxAuthTries 4` |
| ufw | default deny incoming; allow **OpenSSH, 80, 443 only** |
| fail2ban | `sshd` jail, 5 failures / 10 min → 1 h ban |
| unattended-upgrades | daily security patches, weekly autoclean |
| Docker | checked; installs/verifies the Engine + Compose plugin (§3) |

**Safety guard:** the script refuses to disable password authentication until a
key is proven to be installed, so you cannot lock yourself out. **PostgreSQL
(5432) and Redis (6379) are never opened in the firewall** — the Compose stack
keeps them on an internal Docker network with no published port.

Log out and log back in as the new user to confirm you still have access
*before* running anything else.

---

## 3. Docker and Docker Compose installation verification

Docker Engine with the Compose **plugin** (the `docker compose` subcommand, not
the legacy `docker-compose` binary) is required.

```bash
# Install (official Docker apt repository for Ubuntu 24.04 "noble")
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let the admin user drive Docker without sudo (log out/in afterwards)
sudo usermod -aG docker "$USER"
```

**Verification — all four must succeed:**

```bash
docker --version          # Docker version 27.x or newer
docker compose version    # Docker Compose version v2.2x or newer
docker run --rm hello-world
docker ps                 # empty list is fine; an error is not
```

If `docker compose` is missing but `docker-compose` exists, you have the legacy
tool — install `docker-compose-plugin` instead of relying on it.

---

## 4. Repository deployment

```bash
sudo apt-get install -y git jq postgresql-client
git clone https://github.com/nazirumar/aa-shinaka-digital-platform.git
cd aa-shinaka-digital-platform
git log -1 --oneline     # record the commit you deployed
```

Then create the environment file and render the site configuration
(**no fabricated hostname is ever used** — the template ships with an
`EXAMPLE_DOMAIN` placeholder that validation rejects):

```bash
cp deploy/.env.production.example deploy/.env.production
nano deploy/.env.production        # fill in every value (§5)
./deploy/scripts/validate_env.sh deploy/.env.production
deploy/scripts/render_nginx.sh yourdomain.com
```

`render_nginx.sh` substitutes the owner-approved domain into
`deploy/nginx/conf.d/default.conf` (gitignored) and refuses placeholders or
malformed hostnames. Nothing is written anywhere else.

**Verify the rendered config:**

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml config --quiet && echo OK
```

---

## 5. Environment variables

`deploy/.env.production` is the single source of truth and is **never
committed** (`.gitignore` and `.dockerignore` both exclude it). The full
annotated template is `deploy/.env.production.example`. The load-bearing groups:

| Group | Keys | Rule |
|---|---|---|
| Domain | `DOMAIN`, `HTTP_PORT`, `HTTPS_PORT` | owner-supplied; drives the rendered nginx config |
| Django | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | secret ≥ 50 chars; hosts must be explicit, never `*`; origins must be `https://` |
| Database | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, `DB_SSLMODE_REQUIRE=False` | the two passwords **must match** |
| Cache/Celery | `REDIS_PASSWORD`, `CACHE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `REDIS_PASSWORD` must be `[A-Za-z0-9_]` and is embedded in the URLs |
| Email | `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_HOST_USER/PASSWORD`, `DEFAULT_FROM_EMAIL` | console/locmem backends are **rejected** by production settings |
| Security | `SESSION_COOKIE_AGE`, `DJANGO_SECURE_SSL_REDIRECT=True`, `DJANGO_SECURE_HSTS_*`, rate limits, `MFA_*` | HSTS preload stays **False** until HTTPS is verified end-to-end |
| Uploads | `UPLOAD_SCAN_ENFORCEMENT=enforce`, `CLAMAV_*` | optional ClamAV via `--profile scanning` |
| Backups | `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_AGE_RECIPIENT`, `BACKUP_RCLONE_REMOTE` | encryption and an off-server copy are **mandatory** |
| Payments | `PAYSTACK_ENABLED`, `PAYSTACK_LIVE_MODE=False`, test keys | a live key is refused while live mode is off |

Generate secrets on the server:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # DJANGO_SECRET_KEY
tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48                   # REDIS_PASSWORD (URL-safe)
```

`validate_env.sh` fails the deploy if it finds a placeholder, a weak or short
secret, a wildcard host, a non-HTTPS origin, a console email backend, a
`DATABASE_URL` password that disagrees with `POSTGRES_PASSWORD`, a `REDIS_PASSWORD`
that is not embedded in the Redis URLs, or any live Paystack key.

---

## 6. Service startup

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
```

The stack, in dependency order:

| Service | Role | Restart | Notes |
|---|---|---|---|
| `db` | PostgreSQL 16 | `unless-stopped` | internal network only, persistent `pgdata` volume |
| `redis` | broker + cache | `unless-stopped` | `requirepass`, 128 MB `maxmemory`, internal only |
| `migrate` | **one-shot release step** | `no` | system check → `collectstatic` → `migrate`, then exits |
| `web` | Django + Gunicorn | `unless-stopped` | starts only after `migrate` **completes successfully** |
| `worker` | Celery worker | `unless-stopped` | shares the media volume |
| `beat` | Celery beat scheduler | `unless-stopped` | **exactly one instance** — never scale this |
| `nginx` | reverse proxy | `unless-stopped` | the **only** published ports (80/443) |
| `clamav` | optional scanner | `unless-stopped` | `--profile scanning` |
| `certbot` | optional ACME | `no` | `--profile tls` |

Useful commands:

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml logs -f web worker beat
```

> **Never run two Celery beats.** Running two schedulers double-fires every
> periodic task (duplicate notification emails, duplicate exports). Do not use
> `--scale beat=2`.

---

## 7. Database initialization and controlled migration

Migrations are **never** run by the long-running containers: every one of them
sets `RUN_MIGRATIONS=false`, and only the single one-shot `migrate` service ever
applies them. `web`/`worker`/`beat` wait on
`depends_on: service_completed_successfully`, so a failed migration aborts the
rollout instead of starting a half-migrated application.

```bash
./deploy/scripts/db_migrate.sh --with-backup
```

This takes a host-side lock (`flock`), optionally runs a backup first, shows the
pending migrations, then runs the release container and waits for it.

Check state:

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py showmigrations
```

---

## 8. Superuser creation

Django's `createsuperuser` expects an email address (the custom user model is
email-login, UUID-pk — there is no username field).

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py createsuperuser
```

Prefer the non-interactive form so the address is never echoed into shell
history:

```bash
read -p 'Superuser email: ' SU_EMAIL && \
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps -e DJANGO_SUPERUSER_EMAIL="$SU_EMAIL" \
  -e DJANGO_SUPERUSER_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  web python manage.py createsuperuser --noinput
```

Immediately enable **TOTM MFA** for that account (enforced for privileged staff)
at `/dashboard/`, and store the recovery codes offline.

---

## 9. Role synchronisation

The platform has ten canonical roles, each mapped to a Django group `role:<code>`
with capabilities in `apps/accounts/roles.py`. Groups must exist before staff
permissions resolve correctly:

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py sync_roles
```

Re-run this after every deploy that ships new roles; it is idempotent.

---

## 10. Nigeria location data import

Location data is **imported, never hand-entered**, and a real dataset is **not
bundled** with this repository. Importing fabricated states/LGAs would corrupt
pricing, coverage and delivery logic, so this step is blocked until a verified
dataset is supplied.

```bash
# 1. Obtain the verified source (owner-approved): 37 states + 774 LGAs.
# 2. Copy it into the container and dry-run the import first.
docker compose cp /path/to/nigeria_locations.json migrate:/tmp/locations.json
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py import_nigeria_locations \
  --source /tmp/locations.json --dry-run
# 3. Only then apply it for real:
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py import_nigeria_locations \
  --source /tmp/locations.json --strict
```

**Verify the counts** — anything short of 37 states and 774 LGAs means the
import was partial and must not be reported as complete:

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py shell -c \
  "from apps.locations.models import State,LGA; print(State.objects.count(), LGA.objects.count())"
```

The deployment verifier reports this as **WARN** while the data is partial
(`manage.py verify_deployment`).

---

## 11. Domain configuration

**Do not create or change DNS records without the owner's explicit approval.**
The scripts in this repository never touch DNS.

When the owner approves, create these records at the DNS provider (Hostinger's
DNS zone or wherever the domain is registered):

| Type | Name | Value |
|---|---|---|
| `A` | `@` | `<VPS_IP>` |
| `A` | `www` | `<VPS_IP>` |
| `CNAME` (optional) | any subdomain you intend to use | the apex domain |

Then confirm propagation **before** requesting a certificate:

```bash
dig +short A yourdomain.com        # must return <VPS_IP>
curl -s -o /dev/null -w '%{http_code}\n' http://yourdomain.com/.well-known/acme-challenge/probe
```

Pointing the wrong value at the wrong host is the single most common cause of a
failed certificate issuance.

---

## 12. SSL setup

Certificates are issued through Let's Encrypt in **webroot** mode. nginx serves
the ACME challenge over plain HTTP and redirects everything else to HTTPS.

```bash
# Rehearse against the Let's Encrypt STAGING CA first (untrusted certs, but no
# rate-limit risk) and confirm the flow end to end:
./deploy/scripts/ssl_bootstrap.sh yourdomain.com ops@yourdomain.com --staging

# Then issue the real certificate:
./deploy/scripts/ssl_bootstrap.sh yourdomain.com ops@yourdomain.com
```

The script renders the HTTP-only bootstrap config, starts nginx, runs the
one-shot `certbot` service, copies the issued certificate to
`deploy/nginx/certs/` and re-renders nginx with the TLS config.

**Schedule renewal** (certificates are valid 90 days; `renew` is a no-op until
~30 days remain):

```bash
crontab -e
# 03:00 daily
0 3 * * * cd /home/aashinaka/aa-shinaka-digital-platform && ENV_FILE=deploy/.env.production ./deploy/scripts/ssl_renew.sh yourdomain.com >> /var/log/aa-shinaka-ssl.log 2>&1
```

**Only after HTTPS is verified end-to-end** (§15) consider raising
`DJANGO_SECURE_HSTS_SECONDS` and enabling `DJANGO_SECURE_HSTS_PRELOAD`. Preload
is effectively irreversible for a domain — leave it off until all subdomains are
permanently on HTTPS.

---

## 13. Backups and recovery

**A snapshot is not a backup.** VPS snapshots are provider-side, not off-server,
and are not point-in-time consistent for PostgreSQL. The platform takes its own
encrypted, off-server, verified backups.

```bash
# One-off / manual
./deploy/scripts/backup_docker.sh --env-file deploy/.env.production

# Scheduled (daily at 02:00)
crontab -e
0 2 * * * cd /home/aashinaka/aa-shinaka-digital-platform && ENV_FILE=deploy/.env.production ./deploy/scripts/backup_docker.sh >> /var/log/aa-shinaka-backup.log 2>&1
```

`pg_dump` runs **inside** the `db` container; encryption (`age`, preferred) and
the off-server `rclone` copy run **on the host**, so a compromised image never
yields your backups. The script:

1. dumps in custom format (`-Fc`);
2. **verifies** the archive with `pg_restore --list` — an unverified backup is
   not a backup;
3. encrypts (`BACKUP_AGE_RECIPIENT`, falling back to `BACKUP_GPG_RECIPIENT`);
4. copies to `BACKUP_RCLONE_REMOTE` (Backblaze B2 / Hetzner / S3-compatible);
5. prunes local copies older than `BACKUP_RETENTION_DAYS` (default 30);
6. reports filesystem usage and warns past `DISK_USAGE_THRESHOLD`.

It **fails loudly** if encryption or the off-server copy is not configured.

**Restore** — see [`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md) §4 and
`deploy/scripts/restore.sh`. **Always rehearse in isolation first:**

```bash
DATABASE_URL=postgres://... \
TARGET_DATABASE_URL=postgres://.../aa_shinaka_restore_drill \
RESTORE_DRILL_CONFIRM=yes ./deploy/scripts/restore_drill.sh
```

The drill refuses to run against a target whose name does not contain
`drill`/`restore`/`staging`, and it never touches the source database.

**Media survival:** product images and uploaded documents live in the `media`
named volume, which outlives `docker compose down` and container recreation.
Never run `docker compose down -v` against production — the `-v` deletes the
database and all uploads.

**Migration rollback:** Django does not author down-migrations, so a
problematic migration is rolled back by restoring the pre-migration backup and
redeploying the previous release. See §16.

---

## 14. Monitoring

```bash
# Liveness probe (public, database status only)
curl -fsS https://yourdomain.com/healthz/

# Structured JSON logs for the application
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml logs -f web worker beat

# Disk and Docker growth — wire into cron and alert on a non-zero exit
*/15 * * * * cd /home/aashinaka/aa-shinaka-digital-platform && ./deploy/scripts/disk_check.sh >> /var/log/aa-shinaka-disk.log 2>&1
```

Signals worth alerting on:

| Signal | How |
|---|---|
| Application down | external uptime probe on `/healthz/` (returns 503 when the database is unreachable) |
| Disk full | non-zero exit from `disk_check.sh`; also alerts from `backup_docker.sh` |
| Backup failure | non-zero exit from `backup_docker.sh` (cron + mail or a log-based monitor) |
| TLS expiry | `openssl s_client -connect yourdomain.com:443` … expiry check, or an external monitor |
| Security events | `docker compose logs nginx | grep -E ' 4[0-9][0-9] '` and the application audit log |

**Verify a delivered alert** on staging before relying on it: force a failure
(stop `db`, watch `/healthz/` return 503 and the alert arrive) and restore.

---

## 15. Safe updates and rollback

```bash
./deploy/scripts/deploy.sh --ref <commit-or-tag>
```

The pipeline refuses a dirty working tree, runs the non-destructive preflight
gates, builds the image, runs the single release container, starts the stack and
smoke-tests it.

**Rollback** (code only — this deliberately never reverses migrations):

```bash
git checkout <previous-ref>
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml up -d --build
```

Or use `deploy/scripts/rollback.sh`. If a deploy ships a **bad migration**,
migrations are not reversible in place — restore the pre-migration backup
(§13) into a fresh database and redeploy the previous release. That is why
`db_migrate.sh --with-backup` exists.

**Before every launch or risky migration:** take and verify a fresh backup.

---

## 16. Post-deploy verification checklist

Run these against the deployed host and record the result. Anything that cannot
be run is **NOT VERIFIED**, never "passed".

```bash
./deploy/scripts/preflight.sh deploy/.env.production            # non-destructive gates
BASE_URL=https://yourdomain.com ./deploy/scripts/smoke_test.sh  # HTTP + private-document checks
./deploy/scripts/verify_host.sh https://yourdomain.com          # TLS, headers, media deny, ports
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml \
  run --rm --no-deps web python manage.py verify_deployment     # env / DB / security report
```

`smoke_test.sh` asserts, among other things, that `/invoices/…`, `/receipts/…`,
`/payments/`, `/orders/`, `/account/export/` and `/account/support/` are **not**
readable anonymously, and that `/media/` default-denies.

---

## 17. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `web` restarts, logs show `OperationalError: ... could not connect` | `DATABASE_URL` password ≠ `POSTGRES_PASSWORD`, or `DB_SSLMODE_REQUIRE=True` against the bundled PostgreSQL (no TLS listener) | run `validate_env.sh`; keep `DB_SSLMODE_REQUIRE=False` for Compose |
| `redis` exits immediately | `CACHE_URL`/`CELERY_BROKER_URL` do not embed `REDIS_PASSWORD`, or the password contains a reserved URL character | use a `[A-Za-z0-9_]` password and regenerate the URLs |
| `nginx` exits: `open() "/etc/nginx/certs/fullchain.pem" failed` | certificate not yet issued | run `ssl_bootstrap.sh` (it renders the HTTP-only bootstrap config first) |
| `nginx` exits: no `default.conf` | site config not rendered | `deploy/scripts/render_nginx.sh yourdomain.com` |
| `502 Bad Gateway` | `web` unhealthy or still starting | `docker compose ps`, `docker compose logs web`; the health check allows a 40 s start period |
| `migrate` container fails and nothing starts | a broken migration | `docker compose logs migrate`; restore the pre-migration backup — do **not** hand-edit migrations |
| `CSRF verification failed` | `CSRF_TRUSTED_ORIGINS` missing the domain or not `https://` | add `https://yourdomain.com` (and `https://www.…` if used) |
| `DisallowedHost` | `DJANGO_ALLOWED_HOSTS` missing the domain | list the exact hostnames; never use `*` |
| Emails not delivered | SMTP credentials or `EMAIL_HOST`; production settings reject console backends | verify with `manage.py sendtestemail`-style check and the provider's log |
| Upload rejected | `UPLOAD_SCAN_ENFORCEMENT=enforce` without a scanner, or a signature match | check `FileScanRecord`; enable ClamAV with `--profile scanning` |
| Duplicate notification emails | **two Celery beats running** | `docker compose ps` and remove any second beat |
| Disk filling up | media/Docker layer growth | `disk_check.sh`; `docker image prune -f`; extend the volume |

Collect diagnostics safely (never paste secrets):

```bash
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml logs --tail 200 web
df -h && docker system df
docker compose --env-file deploy/.env.production -f deploy/docker-compose.yml config | grep -c EXAMPLE_DOMAIN   # must be 0
```

---

## 18. Deployment gates — what still has to be executed

These require the real host and were **not** verified when this guide was
written. Each maps to a row in [`PHASE_15_HOSTINGER_REPORT.md`](PHASE_15_HOSTINGER_REPORT.md):

1. VPS provisioned; SSH key-only login; non-root admin; ufw/fail2ban/unattended-upgrades live.
2. Docker Engine + Compose plugin installed and verified.
3. Stack built and started; all containers healthy.
4. Migrations applied once; `sync_roles` run; superuser created with MFA.
5. Nigeria locations imported from a **verified** source (37 states / 774 LGAs).
6. Domain approved and DNS propagated.
7. TLS issued and renewal scheduled; HTTPS redirect and HSTS verified on the wire.
8. Encrypted off-server backups configured and a **restore drill** executed on the host.
9. Monitoring wired and a **delivered test alert** confirmed.
10. Paystack **test** end-to-end payment verified; live mode remains disabled.
11. Owner sign-off of business content.
