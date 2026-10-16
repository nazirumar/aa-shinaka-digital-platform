# Phase 6 Completion Report — Payments & Refunds (Paystack)

**Document ID:** AASDP-PH6-REP-001
**Status:** Complete (for owner/engineering approval before Phase 7)
**Date:** 2026-10-13

## Objective delivered

Phase 6 turns the Phase 5 `pending_payment` order into a settled sale. It adds
hosted **Paystack** checkout, authoritative server-side verification,
signature-verified idempotent **webhooks**, manual **bank-transfer** review,
finance-controlled **refunds**, immutable **invoices/receipts** (HTML +
dependency-free PDF), a customer payment portal and a capability-gated staff
**finance dashboard** with reconciliation.

The hard rules hold throughout:

- Paystack is contacted **only** from `apps.orders.paystack`, and **never** for
  real in tests (every provider call is monkeypatched).
- A payment is `paid` **only** after a server-side verification or a
  signature-verified webhook whose currency and amount match the stored order
  total. The browser redirect is never trusted.
- All money is `Decimal`; provider smallest units (kobo) exist **only** at the
  API boundary (`to_kobo`/`from_kobo`).
- Webhook/verification/receipt/stock/refund writes are transactional,
  row-locked and idempotent. Duplicate, delayed and out-of-order events are
  safe.
- Secrets come from `PAYSTACK_*` env vars, are never committed, rendered,
  logged or returned.

## Files created/modified

### Apps (new — `apps/orders`)
- `paystack.py` — the only provider boundary: config, `to_kobo`/`from_kobo`,
  signed HTTP (`initialize_transaction`, `verify_transaction`,
  `refund_transaction`), `verify_webhook_signature` (HMAC-SHA512 over the raw
  body), typed `PaystackError`.
- `payment_models.py` — `Payment`, `PaymentAttempt`, `PaymentWebhookEvent`,
  `CompanyBankAccount`, `BankTransferSubmission`, `Refund`, `Invoice`,
  `Receipt` + enums and state sets (imported at the end of `models.py`).
- `payments.py` — the Phase 6 service layer: `initialize_payment`,
  `verify_payment`/`_apply_verification`, `process_webhook`/`_handle_event`,
  bank-account CRUD, `record_bank_transfer`/`review_bank_transfer`,
  `request_refund`/`approve_refund`/`complete_refund`/`fail_refund`,
  `generate_invoice`, `issue_receipt`, `reconcile_payment(s)`.
- `documents.py` — HTML block builders + a dependency-free PDF writer
  (invoice and receipt).
- `notifications.py` — idempotent customer/customer-email notifications for the
  payment lifecycle (sent after commit via `notify_safe`).
- `payment_forms.py` — `BankTransferForm`, `BankTransferReviewForm`,
  `RefundRequestForm`, `CompanyBankAccountForm`.
- `payment_views.py` — customer payment portal, bank-transfer submit, invoice/
  receipt HTML + PDF, and the `@csrf_exempt` webhook endpoint.
- `finance_views.py` / `finance_urls.py` — the gated `/dashboard/finance/…`
  screens.
- `management/commands/reconcile_payments.py` — reconciliation fallback for
  beat.

### Apps (modified — `apps/orders`)
- `models.py` — imports the payment models; `Order` gains the settlement
  surface used by providers.
- `services.py` — new idempotent `settle_order` core (row-locked, commits
  reservations); `confirm_payment` delegates to it; `place_order` issues the
  invoice after commit.
- `selectors.py` — finance overview/metrics, payment, invoice and
  `staff_bank_accounts` selectors.
- `tasks.py` — `orders.expire_reservations`, `orders.reconcile_payments`.
- `urls.py` — customer payment/invoice/receipt/webhook routes.

### Config & templates
- `config/settings/base.py` — `PAYSTACK_*` settings (off by default),
  `ORDER_TAX_RATE`, reservation TTL and the reconciliation beat schedule.
- `.env.example` — documented `PAYSTACK_*` keys.
- `config/urls.py` — mounts the finance URLconf.
- `templates/orders/payments/` — payment list/detail, bank-transfer form.
- `templates/orders/invoices/` — invoice list/detail, receipt detail.
- `templates/orders/email/notification_body.{txt,html}`.
- `templates/dashboard/finance/` — home (Chart.js overview), payment list/
  detail, bank-transfer list/detail, refund list/detail, invoice list/detail,
  bank-account list/form.
- `templates/dashboard/base.html` — Finance nav block (capability-gated).
- `templates/accounts/account_base.html` — customer Payments/Invoices links.

## Migrations

- `orders/0002_companybankaccount_payment_banktransfersubmission_and_more.py`
  — `CompanyBankAccount`, `Payment`, `PaymentAttempt`, `PaymentWebhookEvent`,
  `BankTransferSubmission`, `Refund`, `Invoice`, `Receipt` and their
  constraints/indexes. Applied to the dev database.

## Models (Phase 6)

All money is `DecimalField(14,2)`; provider rows are UUID-pk.

- `Payment` — one attempt to settle one order through one provider. Unique
  `reference`; `expected_amount` (authoritative server total) vs
  `verified_amount` (set only after verification); `status`, `provider`,
  `method`, `currency`, `provider_reference`, `channel`,
  `requires_review`/`review_reason`, `verified_at`, `note`. Indexes for the
  order/status, provider-reference and review queues.
- `PaymentAttempt` — a hosted-checkout round-trip (`authorization_url`,
  `access_code`, `PaymentAttemptStatus`).
- `PaymentWebhookEvent` — durable webhook record with unique
  `(provider, event_id)` and a redacted `payload`, so deliveries are
  deduplicated and replayable.
- `CompanyBankAccount` — verified settlement accounts (finance-configured);
  unique `(bank_name, account_number, currency)`.
- `BankTransferSubmission` — a customer's **claim** (snapshotted account,
  transfer reference, claimed amount, optional proof, review fields). A
  partial unique constraint on `(transfer_reference, account_number_snapshot)`
  where the status is *approved* prevents one bank transfer settling two orders.
- `Refund` — finance-controlled reversal (`request → approve → complete`),
  `amount > 0`, never exceeding captured funds; Paystack refunds settle via
  `refund.processed` webhooks, offline refunds manually.
- `Invoice` — immutable once `issued_at` is set (`save()` rejects changes to
  the snapshotted number/parties/amounts); one per order.
- `Receipt` — one per verified payment; only issuable for captured payments.

## Customer URLs

- `/orders/<number>/pay/` (`orders:payment_start`) — start/resume hosted
  Paystack checkout.
- `/orders/<number>/payment/callback/` (`orders:payment_callback`) — Paystack
  redirect target; re-verifies server-side.
- `/orders/<number>/bank-transfer/` (`orders:bank_transfer_submit`) — claim a
  manual transfer.
- `/payments/` (`orders:payment_list`), `/payments/<uuid>/`
  (`orders:payment_detail`).
- `/invoices/` (`orders:invoice_list`), `/invoices/<number>/`
  (`orders:invoice_detail`), `/invoices/<number>/pdf/`.
- `/receipts/<number>/` (`orders:receipt_detail`),
  `/receipts/<number>/pdf/`.
- `/payments/paystack/webhook/` (`orders:paystack_webhook`) — `@csrf_exempt`,
  signature-verified; returns 401 (bad signature), 400 (malformed/unknown) or
  200 (accepted/duplicate).

## Staff finance URLs (`/dashboard/finance/…`, `FINANCE_MANAGE`)

- `/dashboard/finance/` (`finance_dashboard`) — overview with verified-only
  metrics and a Chart.js revenue chart.
- `…/payments/`, `…/payments/<uuid>/`, `…/payments/<uuid>/reconcile/`.
- `…/transfers/`, `…/transfers/<uuid>/`, `…/transfers/<uuid>/review/`.
- `…/refunds/`, `…/refunds/<uuid>/`, `…/refunds/<uuid>/approve/`,
  `…/refunds/<uuid>/complete/`.
- `…/invoices/`, `…/invoices/<number>/`.
- `…/bank-accounts/`, `…/bank-accounts/new/`, `…/bank-accounts/<uuid>/edit/`,
  `…/bank-accounts/<uuid>/toggle/`.

Every screen enforces `FINANCE_MANAGE` server-side; templates only hide
navigation. Customer records are scoped to their owner.

## Payment lifecycle & invariants

```
create order -> reserve stock -> Order(pending_payment)
      |                                             |
      |  staff manual approval    OR  verified Paystack capture
      |  (confirm_payment)            OR finance-approved bank transfer
      |                                             v
      +-------------------------> settle_order(atomic) -> Order.confirmed
                                                    |
                                      commit reservation (StockMovement: sale)
```

- `initialize_payment` reuses any open Paystack payment for the same
  order/amount, so re-clicking "Pay" never creates duplicate charges.
- `_apply_verification` takes a row lock, is a no-op once refundable, marks the
  payment `paid`, records `verified_amount`, issues a receipt and settles the
  order — all in one transaction. An underpay or currency mismatch is marked
  `failed` and flagged `requires_review`.
- `process_webhook` verifies the HMAC signature first, stores the delivery with
  a unique `(provider, event_id)`, and treats a repeat of a processed event as a
  no-op. `charge.success`, `charge.failed` and refund events are handled.
- A late capture on an expired/cancelled order records the payment, sets
  `requires_review` and never auto-completes the order.
- `review_bank_transfer(approve=True)` requires `settlement_confirmed`; the
  unique-approved-transfer constraint blocks one transfer settling two orders.
  Uploaded proof alone is never evidence of payment.
- Refunds are finance-only and `amount <= payment.settled_amount` is enforced
  inside a row-locked transaction.
- Invoices are immutable after issue; receipts exist only for verified payments.
- `reconcile_payment(s)` re-verifies open Paystack payments; run by the
  `orders.reconcile_payments` beat task and the `reconcile_payments` command.

## Notifications

Customer (and finance) notifications are sent **after commit** through
`notify_safe`, so a notification failure never rolls back a settlement. Because
settlement is idempotent, duplicate webhooks/verifications do not send duplicate
notifications.

## Tests

New Phase 6 suite (37 tests) in `tests/test_orders_payments.py`, with every
provider call monkeypatched and Paystack disabled by default:

- Initialize creates/reuses a processing payment, and enforces
  enabled/amount/currency/reservation guards.
- Verify settles a valid payment, is idempotent, rejects an underpay and a
  currency mismatch (both flagged for review), and never trusts the callback.
- Webhook accepts a valid signature, rejects a bad signature (401) and a
  malformed payload (400), is idempotent for duplicates, and flags a late
  payment.
- Bank-transfer approval requires confirmed settlement; one transfer cannot
  settle two orders.
- Refunds cannot exceed captured funds; a partial refund marks the payment
  `partially_refunded`, a full refund marks the order `refunded`.
- Invoices are marked paid after a verified payment and are immutable; receipts
  require a verified payment; PDF rendering produces valid output.
- Customers cannot open another customer's payment/invoice; finance screens
  reject users without `FINANCE_MANAGE`; the overview counts verified payments
  only; reconciliation verifies a pending payment.

## Quality gates (end of Phase 6)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — clean.
- `uv run pytest` — all green (existing suites + Phase 6).
- `uv run python manage.py check` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no changes.
- `npm run build:css` — Tailwind rebuilt after template changes.

## Open items / deviations (for owner decision)

- **Live Paystack wiring** is the one owner step: set `PAYSTACK_ENABLED=true`
  and the sandbox/live keys; the platform ships disabled so it runs fully
  offline.
- **ASSUMPTION-04 (VAT/tax):** invoices use the configured `ORDER_TAX_RATE`
  only; no tax table is invented.
- **ASSUMPTION-05 (refund policy/windows):** finance approval capability is
  enforced; any time-window policy is still owner-defined.
- **DRF remains deferred** — the webhook is a plain `csrf_exempt` JSON
  endpoint, not a DRF API.
- Phase 7 (service divisions) is **not started**.
