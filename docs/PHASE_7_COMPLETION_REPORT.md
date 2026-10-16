# Phase 7 Completion Report — Service Divisions (Consultancy, Farming, Marketing, Storage)

**Document ID:** AASDP-PH7-REP-001
**Status:** Complete (for owner/engineering approval before Phase 8)
**Date:** 2026-10-13

## Objective delivered

Phase 7 turns the four service divisions into first-class, auditable
workflows on top of the Phase 2–6 foundations. It adds **one shared request
engine**, per-division detail records, a reusable **quotation engine**, and a
**verified-payment** path that is the only way a priced service is activated —
served through a customer portal (`/account/services/`) and a capability-gated
staff dashboard (`/dashboard/services/`) with a Chart.js overview derived from
real records.

The hard rules hold throughout:

- **No paid service is ever activated from the browser.** Activation runs only
  from a server-side verification (Phase 6 callback/webhook) via
  `apps.services.payments.settle_quotation_payment` → `activate_paid_service`.
- Money is always `Decimal`; quotation totals are recomputed server-side and an
  accepted quotation is frozen.
- Over-allocation (storage) and overlap (consultants) are rejected in the
  service layer under `select_for_update`, backed by DB CheckConstraints.
- Every state change appends to an immutable history/activity log; every
  sensitive action writes an `AuditLog` row.
- Authorisation is enforced in services/views — templates only hide navigation.
- The hard exclusions still hold: no oil & gas, no marketplace, no AgriTrade
  ERP, no hardcoded categories/prices/stock/achievements.

## Files created/modified

### Apps — `apps/services` (new)
- `models.py` — the whole Phase 7 schema (see “Models”).
- `services.py` — the write layer: shared request engine
  (`create_service_request`, `review_service_request`, `assign_staff`,
  `add_comment`, `add_attachment`), consultancy (`book_consultation`,
  `confirm/reschedule/reject/complete_appointment`, `record_consultation_report`),
  farming (`submit_farm_service_request`, `create/approve/activate/complete_farm_project`,
  milestones, visits, progress), marketing (`submit_marketing_enquiry`,
  proposal lifecycle, `create_marketing_campaign`, activity),
  storage (`create_storage_facility/unit`, `submit_storage_request`,
  `create_storage_booking`, capacity accounting, `confirm_storage_booking`,
  `storage_check_in/out`, inspections), quotations
  (`create_quotation`, `submit_quotation_for_approval`, `approve/issue/accept/reject/revise`,
  `expire_due_quotations`) and `activate_paid_service`.
- `selectors.py` — read helpers + `service_overview_metrics` and
  `facility_utilization` (all from real records).
- `payments.py` — `initialize_quotation_payment` bridge +
  `settle_quotation_payment` (idempotent, marks paid, implicit acceptance,
  activates the paid service).
- `notifications.py` — idempotent, per-event email helper backed by
  `ServiceNotificationLog`.
- `forms.py` — customer booking/request forms and staff forms.
- `views.py` / `urls.py` — the customer portal (`app_name="services"`).
- `dashboard_views.py` / `dashboard_urls.py` — the gated staff dashboard
  (`app_name="services_dashboard"`, `services_required` decorator).

### Apps — `apps/orders` (modified)
- `payment_models.py` — `Payment.service_quotation` FK + `chk_payment_single_target`.
- `payments.py` — `initialize_quotation_payment`, `_service_callback_url`, and a
  branch in `_apply_verification` that settles a quotation.
- `notifications.py` — label/context handling for a payment with no order.

### Config, capabilities & navigation
- `apps/accounts/roles.py` — `SERVICES_MANAGE`, `QUOTATIONS_MANAGE` and their
  role mappings; `sync_roles` refreshed.
- `config/urls.py` — mounts `/account/services/` and `/dashboard/services/`.
- `templates/services/customer/` — 9 templates (portal home, request list/detail,
  the four forms, quotations, quotation detail).
- `templates/dashboard/services/` — 17 templates (overview + Chart.js, request
  queue/detail, farming, marketing, storage, quotations).
- `templates/dashboard/base.html`, `templates/accounts/account_base.html` —
  capability-gated navigation.

## Migrations

- `services/0001_initial.py` — all Phase 7 models/enums.
- `services/0002_servicenotificationlog_servicequotation_paid_at_and_more.py` —
  notification log, quotation payment tracking.
- `orders/0003_payment_service_quotation_alter_payment_order_and_more.py` —
  the quotation payment target + constraint.

All applied to the dev database.

## Models (Phase 7)

All PKs are UUIDs; money/quantities are `Decimal`.

- **Shared request**: `ServiceRequest` (customer, `service_type`, status
  pipeline, priority, structured location, `assigned_to`), with
  `ServiceRequestStatusHistory`, `ServiceAssignment` (unique
  `(request, staff, role)`), `ServiceComment` (customer/internal visibility),
  `ServiceAttachment` (size/type validated, explicit visibility),
  `ServiceActivityLog` and `ServiceNotificationLog` (unique `dedupe_key`).
- **Consultancy**: `ConsultancyService`, `Consultant`, `ConsultantAvailability`
  (weekly or one-off), `ConsultationAppointment`, `ConsultationReport`.
- **Farming**: `FarmingService`, `FarmServiceRequest`, `FarmProject`,
  `FarmProjectMilestone`, `FarmVisit`, `FarmProgressReport`
  (`CheckConstraint` progress ≤ 100).
- **Marketing**: `MarketingService`, `MarketingEnquiry`, `MarketingProposal`,
  `MarketingCampaign`, `MarketingActivity`. No third-party seller accounts.
- **Storage**: `ProduceType`, `StorageFacility`, `StorageUnit`,
  `StorageServiceRequest`, `StorageBooking`, `StorageCapacityAllocation`,
  `StorageCheckIn`, `StorageCheckOut`, `StorageInspection`.
- **Quotations**: `ServiceQuotation` (revision/`supersedes`, approval/issue/
  decision, `payment_status`/`paid_at`, frozen-on-accept) + `ServiceQuotationItem`.

### Request pipeline

```
submitted -> under_review -> quoted -> confirmed -> in_progress -> completed
     |            |            |          |             |
     +------------+------------+----------+-------------+--> rejected / cancelled
```

`REQUEST_TRANSITIONS` declares the legal moves. A request acted on straight from
`submitted` is **implicitly reviewed first**, so the recorded history always
reflects the pipeline instead of skipping a stage.

## Customer portal URLs (`/account/services/…`)

- `/account/services/` (`services:service_home`)
- `…/requests/`, `…/requests/<reference>/`
- `…/<division>/new/` — consultancy | farming | marketing | storage
- `…/quotations/`, `…/quotations/<uuid>/`, `…/quotations/<uuid>/pay/`
- `…/payments/callback/<reference>/` — server-side re-verify
- `…/proposals/<uuid>/decide/`

## Staff dashboard URLs (`/dashboard/services/…`, `SERVICES_MANAGE`)

- `/dashboard/services/` — overview + Chart.js.
- `…/requests/`, `…/requests/<reference>/`.
- `…/appointments/<uuid>/confirm|complete/`.
- `…/farm/projects/…`, `…/farm/requests/<uuid>/project/`.
- `…/marketing/`, `…/marketing/<uuid>/`.
- `…/storage/facilities/…`, `…/storage/bookings/…`, `…/storage/requests/<uuid>/booking/`.
- `…/quotations/…` (+ `…/quotations/new/<reference>/`), approval/issue gates on
  `QUOTATIONS_MANAGE`.

Every screen enforces its capability server-side; templates only hide
navigation. Customer records are scoped to their owner.

## Verified-payment settlement (Phase 6 integration)

```
customer pays quotation -> Paystack hosted page
        -> callback OR signed webhook
        -> server verifies (amount/currency, authoritative)
        -> settle_quotation_payment(payment)        [idempotent]
              -> quotation.payment_status = paid
              -> paying an ISSUED quotation = implicit acceptance
              -> activate_paid_service()  -> confirm storage booking /
                                             activate farm project
```

- `orders.Payment` targets exactly one of `order`/`service_quotation`
  (`chk_payment_single_target`).
- `settle_quotation_payment` is a no-op for a payment that targets no quotation.
- `confirm_storage_booking` refuses to confirm a priced booking until the
  quotation is paid; the browser callback alone never confirms/activates.

## Tests

34 new tests in `tests/test_services.py` (+ `tests/services_helpers.py`):

- **Request engine**: reference format, status history, transition guards,
  implicit-review-from-submitted, closing, assignment reactivation, comments,
  attachment type/size validation, notification dedupe, per-division isolation.
- **Consultancy**: booking, mode must be supported, confirm requires a
  consultant/availability, overlapping appointment rejected, report + completion.
- **Farming**: budget guard, agreement-gated activation, milestones, progress.
- **Marketing**: proposal lifecycle, campaign requires an accepted proposal,
  activity + completion.
- **Storage**: capacity reservation, overbooking rejected, unit ceiling,
  check-in/out guards, unaccepted produce.
- **Quotations**: server-recomputed totals, full workflow + request transitions,
  accepted frozen, capability gate on approval, revise/supersede, expiry.
- **Settlement**: idempotent, activates paid storage, ignores non-quotation
  payments.
- **Views**: portal login gate, page render smoke, cross-customer 404, dashboard
  capability gate (customer → 403), all URL names reverse.

Two real defects were found and fixed by the suite: `ServiceActivityLog` writes
used a non-existent `detail` field (now `summary`), and the shared pipeline
needed the implicit-review step so direct confirmations/activations from
`submitted` do not skip a stage.

## Quality gates (end of Phase 7)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest` — all green (existing suites + Phase 7).
- `uv run python manage.py check` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no changes.
- `npm run build:css` — Tailwind rebuilt after template/navigation changes.

## Open items / deviations (for owner decision)

- **Public division request forms** live in the authenticated customer portal
  (`/account/services/…`); the CMS public division pages keep their content and
  route enquiries through Contact. Moving the forms onto the public pages would
  be a UX decision, not a data-model change.
- **ASSUMPTION-04 (VAT/tax)**: quotations use the configured rate only; no tax
  table is invented.
- **Notification channel**: email only for now (ASSUMPTION-10 remains open for
  SMS/WhatsApp).
- **Consultant scheduling** is data-driven availability + explicit confirmation;
  calendar UI and reminders are not built.
- **DRF remains deferred.**
- Phase 8 (export & training/academy) is **not started**.
