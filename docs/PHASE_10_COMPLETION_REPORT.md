# Phase 10 — Unified customer portal, notifications & support centre

**Status:** Complete (see owner approval before Phase 11)
**Date:** 2026-10-15

## Objective delivered

Phase 10 gives every customer **one authenticated place** to see everything about
their relationship with AA Shinaka, be told about genuine state changes, and get
help — and gives staff a scoped, capability-gated view of a customer and a support
queue. It is delivered in two new domain apps plus portal additions to
`apps.accounts`:

- **`apps.notifications`** — the unified **in-app notification centre**: a
  `Notification` feed, per-customer `NotificationPreference` opt-outs and a
  `NotificationDelivery` ledger, with pluggable channels (in-app + email live;
  SMS/WhatsApp present but inert) and event builders that domain services call at
  genuine state-change points.
- **`apps.support`** — the **support centre**: `SupportTicket` / `SupportMessage` /
  `SupportAttachment` / `SupportStatusHistory`, server-side ownership checks on any
  linked record, a status state machine, and customer + capability-gated staff
  surfaces.
- **`apps.accounts`** — the unified `/account/` hub gains a metrics overview, a
  cross-domain **activity timeline**, a **document centre** with one central,
  per-type ownership-checked download route, and a capability-gated **staff
  customer overview**.

The hard rules hold throughout:

- **No duplicate emails.** Events a domain app already emails simply mirror into
  the in-app feed; `manage_email=True` is reserved for genuinely new events (e.g.
  support replies). The existing per-domain dedupe logs remain the authority for
  transactional *email* idempotency.
- **The in-app row is created synchronously** inside the business transaction, so
  it rolls back with the business operation; only channel **delivery** is
  scheduled after commit (`transaction.on_commit`). A delivery failure never rolls
  back a business flow, and a broker/Celery outage never loses the in-app row.
- **`emit()` is idempotent** on a `dedupe_key`, so retried webhooks/events never
  duplicate. A category the customer has muted stores **nothing**.
- **No delivery is ever claimed that a provider did not confirm.** Email is only
  recorded `delivered` after the backend confirms it; an unconfigured channel is
  recorded `skipped`, and a failed delivery is retried and finally marked `failed`
  (never silently dropped).
- **SMS/WhatsApp stay inert** until an approved provider is configured **and** the
  customer opts in; no credentials are hardcoded (provider config is env-only),
  and no message is sent without consent/approved templates.
- **A linked record is never trusted from the browser.** Ticket links and document
  downloads are resolved and re-authorised server-side by ownership.
- **Nothing is hardcoded.** No fabricated documents, notifications, metrics,
  tickets or people; empty states stay empty.

## Files created/modified

### Apps — `apps.notifications` (new)
- `apps.py` — app config `NotificationsConfig`.
- `models.py` — `Notification`, `NotificationPreference`, `NotificationDelivery`,
  the category/channel/status enumerations and `max_delivery_attempts()`.
- `services.py` — the write layer: `emit` (idempotent create + schedule delivery),
  `get_preference`/`update_preference`/`category_enabled`, `safe_url`,
  `deliver_delivery`/`deliver_pending_for` (retry + never-claim-success), and
  read-state (`mark_read`, `mark_unread`, `mark_all_read`, `unread_count`).
- `channels.py` — `Channel` adapters: `InAppChannel`, `EmailChannel` (records
  delivery only when the backend confirms), and inert `SmsChannel`/`WhatsAppChannel`
  (raise `ChannelNotConfigured` until a provider is configured).
- `events.py` — event builders (`order_created`, `order_dispatched`,
  `payment_verified`, `export_quotation_issued`, `export_shipment_updated`,
  `consultancy_appointment_confirmed`, `farming_milestone_updated`,
  `storage_booking_confirmed`, `training_enrollment_confirmed`,
  `certificate_issued`, `support_ticket_reply`). Each is defensive — a missing
  recipient/link yields no notification rather than an error.
- `selectors.py` — feed reads (`feed_for`, unread counts, badge data).
- `forms.py` — `NotificationPreferenceForm` (channel toggles + category opt-outs).
- `views.py` / `urls.py` — the customer centre (`app_name="notifications"`):
  `center`, `preferences`, `badge`, `mark_read`, `mark_all_read`,
  `open` (mark-read + safe redirect).
- `tasks.py` — `deliver_delivery_task` (single, retryable) and
  `deliver_pending_task` (periodic sweep for missed schedules).
- `context_processors.py` — `unread_notifications` (badge count on every page).
- `admin.py` — **read-only** registrations (writes go through services).

### Apps — `apps.support` (new)
- `apps.py` — app config `SupportConfig` (verbose name “Support centre”).
- `models.py` — `SupportTicket`, `SupportMessage`, `SupportAttachment`,
  `SupportStatusHistory`, the category/priority/status/related-type enumerations,
  `SUPPORT_TRANSITIONS` and `REOPEN_WINDOW_DAYS`.
- `links.py` — `resolve_related`: resolves a linked order/payment/enquiry/request/
  enrolment **by ownership**, raising `ValidationError` for anything unknown or
  belonging to another customer (a raw reference/pk is never trusted).
- `services.py` — the write layer: `create_ticket`, `add_customer_message`,
  `add_staff_message` (public reply vs internal note), `assign_ticket`,
  `change_status`, `change_priority`, `reopen_ticket`, `close_ticket` — all
  transactional, state-machine-guarded and audited.
- `selectors.py` — customer-scoped (`tickets_for`, `customer_thread`) and staff
  queues + `support_metrics()` (list-of-dicts for template-safe rendering).
- `forms.py` — customer ticket/reply forms and staff reply/assign/status/priority
  forms.
- `validators.py` — attachment validation (allowed types + size cap).
- `views.py` / `urls.py` — customer surface (`app_name="support"`): home, list,
  create, detail, reply, reopen, close, attachment download.
- `dashboard_views.py` / `dashboard_urls.py` — capability-gated staff queue
  (`app_name="support_dashboard"`): home, list, detail, reply, assign, status,
  priority, attachment download.
- `admin.py` — **read-only** registrations.

### Portal, documents & activity — `apps.accounts` (modified/new)
- `documents.py` (new) — the **document centre**: per-type collectors that reuse
  the existing ownership checks and expose `(kind, pk, label, url)` rows, plus
  `resolve_document(customer, kind, pk)` used by the central download to
  re-authorise by type + ownership.
- `activity.py` (new) — `activity_feed(customer)`: merges the customer's recent
  orders, payments, service, export, training, support and notification events into
  one reverse-chronological `ActivityEntry` list (strictly scoped to the signed-in
  customer).
- `account_views.py` — `_account_metrics`, `documents`, `document_download`,
  `activity`.
- `account_urls.py` — `documents`, `documents/<kind>/<pk>/download/` (central),
  `activity`.
- `selectors.py` — `customer_directory(customer)` and `customer_overview(...)`
  (cross-domain aggregates; the finance section is gated separately).
- `customer_dashboard_views.py` / `customer_dashboard_urls.py` — the staff
  customer overview (`app_name="customers_dashboard"`: list, detail).

### Config, capabilities & navigation
- `apps/accounts/roles.py` — new capabilities `SUPPORT_MANAGE`, `SUPPORT_APPROVE`
  and `CUSTOMERS_VIEW`; `SALES_OFFICER`/`FINANCE_OFFICER` get `CUSTOMERS_VIEW`;
  `ADMINISTRATOR`/`OWNER` hold everything. `sync_roles` refreshed.
- `apps/core/models.py` — shared abstract `UUIDTimeStampedModel` (UUID PK +
  created/updated timestamps), used by `apps.support`.
- `config/settings/base.py` — `apps.notifications` + `apps.support` in
  `LOCAL_APPS`; the `unread_notifications` context processor; and the Phase 10
  settings block (`NOTIFICATION_EMAIL_ENABLED`, `NOTIFICATION_MAX_ATTEMPTS`,
  `SITE_URL`, and the inert `SMS_*`/`WHATSAPP_*` provider vars).
- `config/urls.py` — mounts `/account/notifications/`, `/account/support/`,
  `/dashboard/support/` and `/dashboard/customers/`.
- `templates/notifications/` — `center.html`, `_list.html`, `_badge.html`,
  `preferences.html` and `email/notification_body.html`.
- `templates/support/` — customer (`home`, `ticket_list`, `ticket_form`,
  `ticket_detail`, `_status_badge`) and dashboard (`home`, `ticket_list`,
  `ticket_detail`, `_ticket_table`) templates.
- `templates/accounts/` — `documents.html`, `activity.html`,
  `customer_dashboard_list.html`, `customer_dashboard_detail.html`; the portal
  base/dashboard gain the new nav.
- `templates/components/navbar.html`, `templates/dashboard/base.html` — portal
  badge + Support/Customers navigation sections.
- `apps/orders/payments.py`, `apps/orders/services.py`,
  `apps/services/services.py`, `apps/export/services.py`,
  `apps/training/services.py` — call the matching `notifications.events` builder at
  the genuine state-change point (in-app only; the existing domain email is
  unchanged).

### Documentation
- `docs/IMPLEMENTATION_ROADMAP.md` (Rev 1.0), `docs/SRS.md`,
  `docs/DATABASE_DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/UI_UX_SPEC.md`,
  `README.md`, `.env.example` — see “Documentation updates” below.

## Migrations

- `notifications/0001_initial.py` — `Notification`, `NotificationPreference`,
  `NotificationDelivery` + enumerations/indexes/constraints.
- `support/0001_initial.py` — `SupportTicket`, `SupportMessage`, `SupportAttachment`,
  `SupportStatusHistory` + enumerations/constraints.

All migrations are generated, reviewed and applied; `makemigrations --check`
reports no missing migrations. **`accounts.Notification` was not created** — the
roadmap’s sketch is superseded by `apps.notifications`.

## Models

### `notifications`
| Model | Purpose |
|---|---|
| `Notification` | One in-app notification for one recipient. `category`, `event`, `title`, `message`, same-site `url`, soft `reference_type`/`reference_id`, unique **`dedupe_key`**, `is_read`/`read_at`. Indexed by recipient/recency, recipient/unread, recipient/category. |
| `NotificationPreference` | OneToOne with `User`: `in_app_enabled`/`email_enabled` (default on), `sms_enabled`/`whatsapp_enabled` (default off), and a `categories` JSON map (all on by default). |
| `NotificationDelivery` | One row per `(notification, channel)` — `status` (`pending`/`delivered`/`skipped`/`failed`), `attempt_count`, `last_attempt_at`, `delivered_at`, `provider_reference`, `error_detail`. Constraint `uniq_notification_channel`. |

### `support`
| Model | Purpose |
|---|---|
| `SupportTicket` | `reference` (`AS-ST-…`, unique), `customer`, `subject`, `category`, `priority`, `status`, optional ownership-checked `related_type`/`related_id`, `assigned_to`, `resolved_at`/`closed_at`/`reopened_at`, `last_activity_at`. |
| `SupportMessage` | A conversation message: `ticket`, `sender`, `message`, `is_internal`. Internal notes never reach the customer. |
| `SupportAttachment` | A validated upload tied to a `ticket` (and optional `message`), with `original_filename` and `uploaded_by`. |
| `SupportStatusHistory` | Append-only status trail (`previous_status`, `new_status`, `changed_by`, `reason`). |

Enumerations: `NotificationCategory`, `NotificationChannel`,
`NotificationDeliveryStatus`; `SupportCategory`, `SupportPriority`
(`low`/`normal`/`high`/`urgent`), `SupportStatus` (`open`/`assigned`/`in_progress`/
`waiting_for_customer`/`resolved`/`closed`/`reopened`), `SupportRelatedType`.
`SUPPORT_TRANSITIONS` declares the legal status moves; `REOPEN_WINDOW_DAYS = 30`
bounds reopening.

## Customer portal URLs (`/account/…`)

```
/account/                               overview dashboard (real per-customer metrics)
/account/activity/                      aggregated cross-domain timeline
/account/documents/                     document centre (owned files only)
/account/documents/<kind>/<pk>/download/ central, per-type ownership check
```

## Notification centre URLs (`/account/notifications/…`)

```
/account/notifications/                 the feed (read/unread)
/account/notifications/preferences/     channel + category opt-outs
/account/notifications/badge/           HTMX unread badge partial
/account/notifications/read-all/        mark everything read
/account/notifications/<uuid>/read/     mark one read (ownership-scoped)
/account/notifications/<uuid>/open/     mark read then safe-redirect to the target
```

## Support centre URLs (`/account/support/…`)

```
/account/support/                       home (my tickets + status summary)
/account/support/tickets/               my tickets
/account/support/tickets/new/           raise a ticket (ownership-checked link)
/account/support/tickets/<ref>/         conversation + attachments
/account/support/tickets/<ref>/reply/   customer reply
/account/support/tickets/<ref>/reopen/  reopen (bounded by the reopen window)
/account/support/tickets/<ref>/close/   close
/account/support/attachments/<uuid>/download/  ownership-scoped download
```

## Staff support & customer-overview URLs

```
/dashboard/support/                     queue + metrics            (SUPPORT_MANAGE)
/dashboard/support/tickets/             filtered queue             (SUPPORT_MANAGE)
/dashboard/support/tickets/<ref>/       ticket + internal notes    (SUPPORT_MANAGE)
/dashboard/support/tickets/<ref>/reply/ public reply / internal note (SUPPORT_MANAGE)
/dashboard/support/tickets/<ref>/assign/ assignment                (SUPPORT_MANAGE)
/dashboard/support/tickets/<ref>/status/ status transition         (SUPPORT_MANAGE)
/dashboard/support/tickets/<ref>/priority/ priority change         (SUPPORT_APPROVE)
/dashboard/support/attachments/<uuid>/download/                    (SUPPORT_MANAGE)

/dashboard/customers/                   customer directory         (CUSTOMERS_VIEW)
/dashboard/customers/<uuid>/            cross-domain overview; finance rows need FINANCE_MANAGE
```

## Notification pipeline (no duplicate emails)

```
domain service (order placed, payment verified, ticket reply, …)
  └─> apps.notifications.events.<event>(obj)          # title/message/safe link + category
        └─> services.emit(recipient, category, event, dedupe_key, …, manage_email=…)
              • idempotent on dedupe_key (retried webhooks never duplicate)
              • a muted category stores nothing
              • creates Notification + a NotificationDelivery per channel IN the
                current transaction (so the feed always reflects the business fact)
              └─ transaction.on_commit -> deliver_delivery_task → channels.<Channel>.send()
                     · EmailChannel -> delivered only when the backend confirms
                     · unconfigured SMS/WhatsApp -> recorded `skipped`
```

Domain migrations that already emailed an event simply **mirror** it into the
in-app feed (no second email); `manage_email=True` is reserved for genuinely new
events such as support replies. This is a deliberate, documented boundary so the
existing transactional-email dedupe logs remain the single authority for email
idempotency.

## Support-ticket lifecycle

```
open ─assign→ assigned ─staff reply→ in_progress -> waiting_for_customer
   │                                                  │
   │                                        customer reply -> in_progress
   └────────────────> resolved ──(<= REOPEN_WINDOW_DAYS)──> reopened
                         │                                     │
                         └────────> closed                     └─> in_progress / …
```

- A ticket link is resolved by ownership server-side (`links.resolve_related`);
  an unknown or foreign record is rejected before anything is written.
- Only legal `SUPPORT_TRANSITIONS` moves are accepted; anything else raises
  `ValidationError`. Reopening a resolved/closed ticket is bounded by
  `REOPEN_WINDOW_DAYS`.
- **Internal staff notes are invisible to customers** (the customer selectors
  filter them out) and never notify. A **public** staff reply mirrors into the
  notification feed via `support_ticket_reply` (a genuinely new event, so it may
  also email).
- Every staff action writes an `AuditLog` entry in the same transaction.

## Tests

**44 new tests** across three files (`tests/test_notifications.py` 18,
`tests/test_support.py` 17, `tests/test_portal.py` 9):

- **Notifications**: `emit` creates a `Notification` + in-app `delivery`;
  idempotency on `dedupe_key`; a muted category stores nothing; unknown recipients
  return `None`; absolute/cross-site URLs are discarded; read-state is
  ownership-scoped; unread count + mark-all; email delivery is recorded only after
  the backend confirms; a disabled email channel is skipped; SMS/WhatsApp are
  inert until configured; a repeatedly-failing delivery ends `failed` (never
  silently dropped); channel singletons; the context processor exposes the unread
  count; preferences persist; the centre is login-gated and lists only the signed-in
  customer’s rows; another customer’s notification cannot be marked read; and
  placing a real order creates an in-app notification (no duplicate domain email).
- **Support**: ticket creation records the status history + opener; subject/message
  are required; a linked record must belong to the customer; a customer can link
  their own order; the state machine rejects illegal *and* unknown transitions
  server-side; a staff reply moves the ticket and notifies; an internal note is
  invisible to the customer and does **not** notify; a customer reply moves the
  ticket back into progress; reopen within/after the window; pages require login;
  a customer cannot view another customer’s ticket or download their attachment;
  non-support staff are denied the queue; a Sales officer can work the queue; and a
  priority change requires `SUPPORT_APPROVE`.
- **Portal**: document pages require login; the document centre lists only owned
  files; the central download is ownership-scoped; an unknown document kind 404s;
  the activity timeline is ownership-scoped; dashboard metrics render; the staff
  customer overview requires `CUSTOMERS_VIEW`; it lists customers; and its finance
  section is gated by `FINANCE_MANAGE`.

## Quality gates (end of Phase 10)

Run in this order:

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean (251 files already formatted).
- `uv run pytest` — **634 passed**, 14 warnings (34m23s). That is +44 tests
  versus Phase 9's 590. The 14 warnings are the pre-existing Django 6.0
  deprecation notices (`forms.URLField` scheme) and the pytest collection notice
  for the CMS model named `Testimonial`.
- `uv run python manage.py check` — clean (“no issues, 0 silenced”).
- `uv run python manage.py makemigrations --check --dry-run` — “No changes
  detected”.
- `npm run build:css` — rebuilt after template/class changes.

## Documentation updates

- `docs/IMPLEMENTATION_ROADMAP.md` — Revision 1.0: Phase 10 is the unified portal,
  notifications & support centre. The customer-portal & notification consolidation
  (drafted as Phase 12) plus the new support centre **is** Phase 10; the drafted
  “Staff dashboard, reporting & audit” and “Hardening” phases are renumbered to
  Phase 11 / Phase 12, and the old Phase 12 portal section is marked superseded.
  Dependency graph and requirement traceability updated.
- `docs/SRS.md` — FR-PORTAL gained a Phase 10 delivery note; `FR-NOTIF-1/2/3`
  delivery note (email unchanged, in-app delivered, SMS/WhatsApp inert);
  new **FR-SUPPORT** table; ASSUMPTION-10 resolved (channels), ASSUMPTION-11 moved
  to Phase 11; capability matrix row for `support.manage`/`support.approve`/
  `customers.view`.
- `docs/DATABASE_DESIGN.md` — `accounts.Notification` marked superseded; new §6c
  (`notifications`) and §6d (`support`) schemas; ER summary additions; `ReportExport`
  / `SavedReport` relabelled Phase 11.
- `docs/ARCHITECTURE.md` — new app rows; URL map for the portal/centre/support/
  customers routes; §7.2 capabilities, §7.3 notification pipeline, §7.4 support
  lifecycle; background-task note for delivery; testing-strategy rows; ADR-13/14/15.
- `docs/UI_UX_SPEC.md` — portal rows (activity, documents, notifications,
  preferences, support) and dashboard rows (support queue/ticket/priority, customer
  overview).
- `README.md` — Phase 10 feature summary + report link; “Phase 11+” note.
- `.env.example` — the Phase 10 notification/support env block.

## Remaining work / not in scope

- **Phase 11** (renumbered) — Staff dashboard, reporting & audit consolidation
  (including `ReportExport`/`SavedReport`); **Phase 12** (renumbered) —
  Hardening, performance & deployment.
- Live SMS/WhatsApp adapters remain deliberately unimplemented until an approved
  provider and, for WhatsApp, approved templates + explicit consent exist.
- Customer wishlist/saved items (`FR-PORTAL-5`) and the data-retention/
  account-deletion policy (ASSUMPTION-11) remain future work.
- DRF remains deferred — no machine client requires it.
- **Phase 11 must not start without explicit owner approval.**
