# Performance & Accessibility — AA Shinaka Digital Business Platform

**Phase:** 12. This document defines **how** performance and accessibility are
measured. It deliberately contains **no invented numbers**: any figure quoted in
a release note must come from a run of the tools below against a specific commit
and recorded with the date and environment.

---

## 1. Known optimisations applied

| Area | Change |
|---|---|
| Catalogue images | `ProductListing.primary_image` memoised per instance, removing an N+1 on list/card pages (audit M-2). |
| Settings | Production static files use `CompressedManifestStaticFilesStorage` (hashed, compressed, long cache). |
| DB access | `select_related`/`prefetch_related` on list selectors; `select_for_update` only on ledger rows inside transactions. |
| Connections | `CONN_MAX_AGE` and `ATOMIC_REQUESTS` enabled in production settings. |
| Templates | Server-rendered with HTMX for partials; no SPA bundle to download. |

---

## 2. Load testing

A dependency-free loader ships with the project: `deploy/scripts/loadtest.py`
(uses only the Python standard library — no new dependency). It drives read-only
endpoints by default so it is safe to run against staging, and it refuses to run
against a non-test payment configuration.

```bash
# 30 seconds, 10 concurrent workers, against staging
BASE_URL=https://staging.example.com uv run python deploy/scripts/loadtest.py \
  --duration 30 --concurrency 10 --paths /,/shop/,/training/,/healthz/

# Save a JSON result for the record
... --json perf-$(date +%Y%m%dT%H%M%SZ).json
```

It reports requests, error rate, throughput and latency percentiles (p50/p95/p99)
computed from measured timings. **Record real numbers from a real run**; do not
paste illustrative values into a report.

### Scenarios worth measuring (when a staging host exists)

| Scenario | Paths | Watch |
|---|---|---|
| Anonymous browse | `/`, `/shop/`, `/shop/category/<slug>/`, `/training/` | latency, 5xx |
| Search | `/shop/search/?q=...` | DB time |
| Authenticated portal | `/account/`, `/orders/`, `/training/portal/` | session + query count |
| Staff dashboard | `/dashboard/`, `/dashboard/catalog/` | query count, auth redirects |
| Static assets | `/static/css/app.css` | cache headers |

> **NOT VERIFIED:** no staging host was provisioned in this environment, so no
> load test has been executed and **no performance figure is claimed**. The
> loader and method above are the deliverable.

---

## 3. Database

- Confirm the top queries use indexes; `pg_stat_statements` / `EXPLAIN ANALYZE`
  the catalogue and order selectors.
- Verify the production DB user is least-privilege and TLS is required
  (`DB_SSLMODE_REQUIRE=True`).
- Watch for N+1 regressions on list pages (the `primary_image` fix removed one).

---

## 4. Accessibility (WCAG 2.2 AA)

Target: **WCAG 2.2 level AA** for public pages, the customer portal and the staff
dashboard. Verify, don't assume:

- [ ] Keyboard-only pass over primary flows (browse → cart → checkout; login;
      forms; dialogs) — every control reachable and operable.
- [ ] Visible focus indicators on all interactive elements.
- [ ] Colour contrast ≥ 4.5:1 for text, ≥ 3:1 for large text and UI components.
- [ ] Form fields have programmatic labels; errors are announced and associated.
- [ ] Images have meaningful `alt` (or empty `alt` when decorative).
- [ ] Landmarks/headings in a sensible order; page has one `h1`.
- [ ] No content relies on colour alone.
- [ ] Target size (2.2 §2.5.8) ≥ 24×24 px for pointer targets.
- [ ] No unexpected context changes on focus; consistent help/placement (2.2
      additions).
- [ ] Automated smoke: an axe-core/Lighthouse run on key templates, then manual
      review for what automation cannot catch.

> **NOT VERIFIED:** no automated accessibility tool and no assistive technology
> pass was run in this environment. Treat the checklist as the gate to perform on
> staging.

---

## 5. Performance & accessibility sign-off

Record, per release: date, environment, tool versions, commands, raw results and
any accepted trade-offs. A green regression here is a launch gate.
