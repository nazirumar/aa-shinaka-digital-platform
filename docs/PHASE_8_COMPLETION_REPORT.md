# Phase 8 — Agricultural Export Management & International Trade

**Document ID:** AASDP-PH8-REP-001
**Status:** Complete (for owner/engineering approval before Phase 9)
**Date:** 2026-10-13

## Objective delivered

Phase 8 lets AA Shinaka take its **own** agricultural produce to international
buyers as a first-class, auditable workflow on top of the Phase 2–7 foundations:
configurable destinations, export-eligible product profiles, enquiries, priced
**Incoterms quotations**, export orders, compliance checklists, private export
documents, freight-forwarding shipments with staff-entered milestones, and
**verified-only** settlement — served through a customer portal
(`/account/export/`) and a capability-gated staff dashboard
(`/dashboard/export/`) with a Chart.js report derived strictly from real records.

It is implemented in the **dedicated `apps.export` app** (kept separate from
`catalog`/`orders`, matching the project's domain-oriented layout), and the
catalogue is extended — never duplicated — through `ExportProductProfile`
(`OneToOneField(catalog.Product)`).

The hard rules hold throughout:

- **Prices are never guessed.** Every quotation names an explicit **Incoterms
  2020** rule (`Incoterm`) **and a named place** (`named_place`), a currency and
  a validity window; totals are recomputed server-side and an accepted quotation
  is **frozen**.
- **Destinations are data, not hand-entered strings.** Each destination is a
  `locations.Country` row. A destination is created `pending`/inactive, approved
  by an `EXPORT_APPROVE` holder, then explicitly activated; it becomes selectable
  only when it is **both** approved and active.
- **No paid state from the browser.** An export payment becomes `paid` only
  after server-side verification through the Phase 6 pipeline
  (`orders.payments.verify_payment`); the browser callback is re-verified and is
  never the source of truth. The Phase 6 verification logic is **not
  duplicated** — `apps/export/payments.py` is a thin bridge.
- **Compliance gates movement.** An export order cannot reach
  `ready_for_shipment`/`shipped` (and a shipment cannot be `dispatched`) until
  its compliance checklist is approved.
- **Trade data is never fabricated.** Milestones are staff-entered
  (`is_staff_entered=True`); no live tracking is invented.
- Money and quantities are always `Decimal`; every state change appends an
  immutable history row and every sensitive action writes an `AuditLog` row.
- Authorisation is enforced in services/views — templates only hide navigation.
  Customers can only ever see and act on their own records.
- The hard exclusions still hold: no oil & gas, no marketplace, no AgriTrade ERP,
  no hardcoded categories/prices/stock/achievements.

> **Scope refinement.** The roadmap originally bundled *export* and the
> *training academy* into one phase. This engagement delivers **export only**;
> training/academy (courses, cohorts, enrollment, ASSUMPTION-09) is **deferred**
> to a later phase. `docs/` reflect this split.

## Files created/modified

### Apps — `apps/export` (new)
- `apps.py` — app config `ExportConfig`.
- `models.py` — the whole Phase 8 schema and status enumerations plus the
  transition maps `EXPORT_ENQUIRY_TRANSITIONS`, `EXPORT_ORDER_TRANSITIONS`,
  `SHIPMENT_TRANSITIONS` (see “Models”).
- `services.py` — the write layer: destinations (`upsert_destination`,
  `approve_destination`, `set_destination_active`, requirements, restrictions,
  document requirements), product profiles (`configure_export_profile`),
  enquiries (`create_enquiry`, `transition_enquiry` + review/requirements/
  reject/cancel helpers), quotations (`create_quotation`, `approve_quotation`,
  `accept_quotation`, `reject_quotation`, `revise_quotation`,
  `expire_due_quotations`), orders (`create_export_order_from_quotation`,
  `transition_export_order`, `assign_export_order`,
  `record_verified_payment`), compliance (`build_compliance_checklist`,
  `update_compliance_item`, `approve_compliance_checklist`), documents
  (`add_document`, `upload_customer_document`, `review_document`), shipments
  (`create_shipment`, `transition_shipment`, `record_milestone`), and providers.
  Two internal, non-gated helpers (`_advance_enquiry`, `_advance_export_order`)
  let system-driven steps (customer accepting a quotation; verified payment
  settlement) advance state without a staff capability, while the public
  transitions stay gated.
- `selectors.py` — reads and metrics: `overview_metrics`, `enquiries_by_destination`,
  `quotations_for`, `visible_documents`, `compliance_queues`, `shipments_queue`,
  `verified_revenue` / `verified_revenue_by_currency`, `product_quantities`,
  `active_destinations`, `active_restriction_for`.
- `payments.py` — `initialize_export_payment` bridge +
  `settle_export_payment` (called by Phase 6 verification).
- `notifications.py` — per-event email helpers.
- `validators.py` — export document file type/size validation.
- `forms.py` — customer enquiry form + item formset, document upload, and staff
  destination/quotation/order/shipment forms.
- `views.py` / `urls.py` — the customer portal (`app_name="export"`).
- `dashboard_views.py` / `dashboard_urls.py` — the gated staff dashboard
  (`app_name="export_dashboard"`).
- `admin.py` — **read-only** registrations (writes must go through services).

### Apps — `apps/orders` (modified)
- `payment_models.py` — `Payment.export_order` FK (`related_name="payments"`)
  and the updated `chk_payment_single_target` constraint.
- `payments.py` — `initialize_export_payment`, `_export_callback_url`, and a
  branch in `_apply_verification` that settles an export payment.
- `notifications.py` — label/context handling for an export payment.

### Config, capabilities & navigation
- `apps/accounts/roles.py` — `EXPORT_MANAGE` (Export Officer + admins/owners) and
  `EXPORT_APPROVE` (Administrators/Owners only via `ALL_CAPABILITIES`);
  `sync_roles` refreshed.
- `config/settings/base.py` — `apps.export` added to `INSTALLED_APPS`.
- `config/urls.py` — mounts `/account/export/` and `/dashboard/export/`.
- `templates/export/customer/` — 10 templates (portal home, enquiry list/form/
  detail, quotation list/detail, order list/detail, shipment list/detail).
- `templates/dashboard/export/` — staff templates (overview + Chart.js reports,
  destinations/requirements/restrictions/document rules, products, enquiries,
  quotations, orders, documents, compliance, shipments, providers, `_nav`).
- `templates/dashboard/base.html` — Export sidebar section.
- `templates/accounts/account_base.html` — Export portal link.

## Migrations

- `export/0001_initial.py` — all Phase 8 models/enums.
- `export/0002_seed_document_types.py` — seeds the configurable
  `ExportDocumentType` registry.
- `orders/0004_*` — `Payment.export_order` + updated single-target constraint.

All migrations are generated, reviewed and applied; `makemigrations --check`
reports no missing migrations. **No product category, price, stock figure or
company achievement is hardcoded**; document types are seeded *configuration*
(the owner can edit them), not business data.

## Models

Destination & product configuration:

- `ExportDestination` (unique per `locations.Country`; `approval_status` and
  `is_active` are independent), `ExportDestinationRequirement`,
  `ExportTradeRestriction`, `ExportDocumentRequirement`.
- `ExportProductProfile` — `OneToOneField(catalog.Product)` with
  `is_export_eligible`, grade/packaging, `min_export_quantity`, specifications,
  `export_availability`, inspection flags and an `allowed_destinations` allow-list.
  `allows_destination()` combines the allow-list with active trade restrictions.

Enquiries, quotations & orders:

- `ExportEnquiry` (ref `AS-EXQ-…`), `ExportEnquiryItem`,
  `ExportEnquiryStatusHistory` (append-only).
- `ExportQuotation` with Incoterms version + named place, currency, deposit,
  validity, server-computed totals; `ExportQuotationItem`;
  `ExportQuotationRevision` (revisions snapshot & supersede).
- `ExportOrder` (ref `AS-EXO-…`; `OneToOneField(ExportQuotation)` in the
  reverse direction via `quotation`), frozen commercial terms,
  `compliance_status`/`fulfillment_status`, money fields with non-negative
  CheckConstraints, lifecycle timestamps; `ExportOrderItem`;
  `ExportOrderStatusHistory` (append-only).

Compliance, documents & shipments:

- `ExportDocumentType` (configurable; `requires_expiry`), `ExportDocument`
  (private storage, `verification_status`, `is_customer_visible`),
  `ExportDocumentReview`.
- `ExportComplianceChecklist` + `ExportComplianceChecklistItem` (generated from
  destination document requirements).
- `LogisticsProvider`; `ExportShipment` + `ExportShipmentItem`;
  `ShipmentMilestone` (**staff-entered only**).

Transition maps (from `apps/export/models.py`):

```
EXPORT_ENQUIRY_TRANSITIONS : submitted → {under_review, requirements_requested, rejected, cancelled}
                             under_review → {requirements_requested, quoted, rejected, cancelled}
                             requirements_requested → {under_review, quoted, cancelled}
                             quoted → {converted, rejected, cancelled}
                             converted | rejected | cancelled → ∅ (terminal)
EXPORT_ORDER_TRANSITIONS   : pending_payment → payment_verified → in_production →
                             ready_for_shipment → shipped → delivered → completed
                             (plus cancellation paths); ready_for_shipment/shipped
                             require a cleared compliance checklist
SHIPMENT_TRANSITIONS       : planned → booked → dispatched → in_transit →
                             customs_processing → arrived → delivered
                             (plus cancelled); dispatch requires compliance cleared
```

## Customer portal URLs (`/account/export/…`)

- `/account/export/` (`export:home`)
- `…/enquiries/`, `…/enquiries/new/`, `…/enquiries/<reference>/`
- `…/quotations/`, `…/quotations/<uuid>/`, `…/quotations/<uuid>/accept/`
- `…/orders/`, `…/orders/<reference>/`, `…/orders/<reference>/pay/`,
  `…/orders/<reference>/documents/upload/`
- `…/documents/<uuid>/download/`
- `…/shipments/`, `…/shipments/<reference>/`
- `…/payments/callback/<reference>/` — server-side re-verify

## Staff dashboard URLs (`/dashboard/export/…`, `EXPORT_MANAGE`)

- `/dashboard/export/` — overview + compliance/shipment queues.
- `…/destinations/…` (+ `new/`, `approve/`, `activate/`,
  `requirements/new/`, `restrictions/new/`, `documents/new/`).
- `…/products/…`.
- `…/enquiries/…` (+ `/action/`, `…/quotation/new/`).
- `…/quotations/…` (approve/issue requires `EXPORT_APPROVE`; revise).
- `…/orders/<reference>/` (+ transitions, documents, checklist).
- `…/documents/…` (+ review).
- `…/compliance/…` (+ approve, item updates).
- `…/shipments/…` (+ transition, milestone).
- `…/providers/…`.
- `…/reports/` — Chart.js reports.

Every screen enforces its capability server-side; templates only hide
navigation. Customer records are scoped to their owner (cross-customer access is
rejected in the service/view layer).

## Verified-payment settlement (Phase 6 integration)

```
customer pays export order -> Paystack hosted page (USD or the configured currency)
        -> callback OR signed webhook
        -> server verifies (amount/currency, authoritative)
        -> _apply_verification(...) -> settle_export_payment(payment)   [idempotent]
              -> record_verified_payment(order, amount, payment)
                    -> order.amount_paid += amount
                    -> if pending_payment and amount_paid >= threshold:
                           _advance_export_order(order, PAYMENT_VERIFIED)   [system, ungated]
```

- `orders.Payment` targets exactly one of
  `order`/`service_quotation`/`export_order` (`chk_payment_single_target`).
- Only a **verified** payment is applied; a partial deposit below the threshold
  does not advance the order. `selectors.verified_revenue` counts only verified
  export payments (an unrelated paid shop payment is excluded).
- The currency must match the configured provider currency; Paystack is not
  assumed to support every export currency (a finance-recorded bank transfer
  can still settle through the same verification path).

## Tests

58 new tests in `tests/test_export.py` (+ `tests/export_helpers.py`):

- **Destinations**: created pending/inactive; activation blocked before
  approval; approval requires `EXPORT_APPROVE`; approved **and** active both
  required; activation is audited.
- **Product profiles & restrictions**: an enquiry needs an export profile;
  an active trade restriction blocks the destination; minimum export quantities
  enforced; allow-lists are positive; ineligible destination rejected.
- **Enquiries**: defaults + status history; a customer cannot raise an enquiry
  for another party; illegal/terminal transitions rejected; review recorded.
- **Quotations**: approval needs `EXPORT_APPROVE`; issue requires Incoterms
  version + named place; approval issues and marks the enquiry quoted;
  acceptance creates the order and converts the enquiry; draft/expired cannot be
  accepted; revisions snapshot & reset; accepted quotation is frozen.
- **Orders**: start `pending_payment`; can enter production; illegal transition
  rejected; checklist includes destination document requirements; checklist
  approval gated; incomplete checklist cannot be approved; `ready_for_shipment`
  blocked until compliance cleared.
- **Documents**: official types require expiry; file required; review mapping;
  customer upload recorded; cannot upload to someone else's order; customer
  visibility hides staff-only documents.
- **Shipments**: creation copies order items; dispatch requires compliance;
  delivered shipment advances the order; milestones are staff-entered; illegal
  transition rejected.
- **Payments**: a customer cannot pay another's order; a verified payment
  settles the order; verified revenue excludes unrelated payments.
- **Reporting**: `overview_metrics` keys; `product_quantities` from accepted
  orders.
- **Views**: portal login gate; cross-customer order blocked; portal renders;
  enquiry creation via the real formset; visibility-scoped document download;
  dashboard requires the capability (customer → 403); anonymous redirect;
  Export Officer can access; dashboard home / reports / order detail render;
  customer cannot reach the staff dashboard.

Real defects found and fixed by the suite:

1. **Customer quotation acceptance was capability-blocked.** `accept_quotation`
   internally called the staff-gated `transition_enquiry`, so a customer could
   not accept their own quotation (`PermissionDenied`). Extracted a non-gated
   internal `_advance_enquiry` (used for the `converted` step and for
   `_mark_enquiry_quoted`), and added an explicit ownership check so a customer
   can only accept their **own** quotation.
2. **Verified payment settlement was capability-blocked.** `record_verified_payment`
   called the staff-gated `transition_export_order` with `actor=None`, so a
   verified payment could never advance the order. Extracted a non-gated
   internal `_advance_export_order`; the trusted settlement path now uses it,
   while staff transitions remain gated.
3. **Staff dashboard 500.** `templates/dashboard/export/home.html` reversed
   `export_dashboard:order_detail` with two arguments (one undefined), raising
   `NoReverseMatch`. Corrected to a single `reference`.

## Quality gates (end of Phase 8)

Run in this order (all green at the end of Phase 8):

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run pytest` — **517 passed** (58 of them the new Phase 8 suite), 22:05 wall.
- `uv run python manage.py check` — 0 issues.
- `uv run python manage.py makemigrations --check --dry-run` — “No changes
  detected”.
- `npm run build:css` — run after template/class changes (`static/css/app.css`).

## Known limitations

- **Live carrier tracking is intentionally absent.** Shipment milestones are
  staff-entered; the platform never fabricates tracking or ETAs.
- **Incoterms places and countries are owner-supplied data.** The platform ships
  the Incoterms 2020 rule set as an enum; which countries/currencies to enable
  and how to price freight/insurance are operational decisions, not defaults.
- **Freight/insurance charges are quotation line items** (`charge_type`), priced
  by staff; no rate card is invented.
- **Paystack currency support is not assumed.** Only the configured provider
  currency can be paid online; other currencies must settle via the finance
  bank-transfer path. No other provider integration is added.
- **Compliance checklist templates** are generated from destination document
  requirements; richer per-destination templates remain a future refinement.
- **Email notifications only** (no SMS/push); delivery depends on configuration.

## Remaining work / not in scope

- **Training & academy** (courses, cohorts, capacity-limited enrollment,
  certificates, course fees) — **deferred**; ASSUMPTION-09 stays open.
- Live carrier tracking, CBM/container planning, and customs-broker workflows.
- DRF remains deferred — no machine client requires it yet.
- Phase 9 must **not** start without explicit owner approval.
