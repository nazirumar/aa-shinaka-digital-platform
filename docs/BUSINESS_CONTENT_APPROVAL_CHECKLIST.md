# Business Content Approval Checklist — AA Shinaka Digital Business Platform

**Phase:** 14 (staging verification & controlled production launch)
**Owner:** AA Shinaka business owner (decision maker)
**Rule:** **No content is invented here.** Every item must be supplied or
approved by the business owner and entered through the application (never
hardcoded). This form is the owner's sign-off on the *business facts* before a
public launch. It complements `docs/LAUNCH_CONTENT_CHECKLIST.md` (which lists the
content to enter); this document records the owner's explicit approval.

> Status vocabulary for each row: **APPROVED** / **PENDING** / **NOT APPLICABLE**
> (with a reason). Leave PENDING until the owner confirms the exact value.

## 1. Company identity & legal

| # | Item | Exact approved value / source | Status | Approved by | Date |
|---|---|---|---|---|---|
| 1.1 | Legal entity name | | PENDING | | |
| 1.2 | Trading name / brand | | PENDING | | |
| 1.3 | Registration number(s) (CAC etc.) | | PENDING | | |
| 1.4 | Registered business address | | PENDING | | |
| 1.5 | Public phone number(s) | | PENDING | | |
| 1.6 | Public email address(es) | | PENDING | | |
| 1.7 | Official logo (final SVG/PNG) + favicon | | PENDING | | |
| 1.8 | Brand colours (design tokens confirmed) | | PENDING | | |
| 1.9 | Social channels that actually operate | | PENDING | | |

## 2. Legal pages

| # | Item | Status | Notes |
|---|---|---|---|
| 2.1 | Privacy notice (GDPR/NDPA-aware) | PENDING | |
| 2.2 | Terms of service | PENDING | |
| 2.3 | Cookie notice | PENDING | |
| 2.4 | Refund policy (wording matches operations) | PENDING | |

## 3. Catalogue & pricing

| # | Item | Status | Notes |
|---|---|---|---|
| 3.1 | Real product categories (no placeholders) | PENDING | |
| 3.2 | Products + units of measure + descriptions | PENDING | |
| 3.3 | Listings with **owner-approved** prices per state/LGA | PENDING | |
| 3.4 | Stock figures (real availability only) | PENDING | |
| 3.5 | Product images (owner-supplied, accurate) | PENDING | |
| 3.6 | Featured products chosen deliberately | PENDING | |

## 4. Warehousing, shipping & fulfilment

| # | Item | Status | Notes |
|---|---|---|---|
| 4.1 | Warehouse(s) and their real locations | PENDING | |
| 4.2 | Default fulfilment warehouse | PENDING | |
| 4.3 | Shipping methods, zones and rates | PENDING | |
| 4.4 | Delivery lead times / areas served (match reality) | PENDING | |
| 4.5 | Returns / refunds process wording | PENDING | |

## 5. Services divisions

| # | Item | Status | Notes |
|---|---|---|---|
| 5.1 | Consultancy services offered + fees | PENDING | |
| 5.2 | Farming services offered | PENDING | |
| 5.3 | Agricultural marketing services offered | PENDING | |
| 5.4 | Storage & warehousing services + capacities | PENDING | |

## 6. Export

| # | Item | Status | Notes |
|---|---|---|---|
| 6.1 | Destinations actually offered (each approved + activated) | PENDING | |
| 6.2 | Products flagged export-eligible | PENDING | |
| 6.3 | Default Incoterms 2020 rule + named place | PENDING | |
| 6.4 | Compliance document types per destination | PENDING | |
| 6.5 | Export claims in copy are accurate (no invented reach) | PENDING | |

## 7. Training academy

| # | Item | Status | Notes |
|---|---|---|---|
| 7.1 | Real courses / modules / lessons / resources | PENDING | |
| 7.2 | Sessions with real dates, venues and fees | PENDING | |
| 7.3 | Instructors assigned | PENDING | |
| 7.4 | Certificate template wording approved | PENDING | |

## 8. Payments & finance

| # | Item | Status | Notes |
|---|---|---|---|
| 8.1 | Currency/ies confirmed (no mixing) | PENDING | |
| 8.2 | Tax handling confirmed (`ORDER_TAX_RATE`) | PENDING | |
| 8.3 | Bank-transfer instructions accurate (or Paystack-only) | PENDING | |
| 8.4 | Paystack **test keys** verified on staging | PENDING | |
| 8.5 | **Live Paystack keys** — explicit separate approval required | PENDING | |

## 9. Communications

| # | Item | Status | Notes |
|---|---|---|---|
| 9.1 | `DEFAULT_FROM_EMAIL` is a real, monitored mailbox | PENDING | |
| 9.2 | `SITE_URL` = final domain (absolute links work) | PENDING | |
| 9.3 | SMS/WhatsApp remain **disabled** unless an approved provider exists | PENDING | |

## 10. Locations & coverage

| # | Item | Status | Notes |
|---|---|---|---|
| 10.1 | Nigeria locations imported (37 states / 774 LGAs) from a verified source | PENDING | |
| 10.2 | Coverage statements match the imported dataset | PENDING | |

## 11. Sign-off

By signing below the owner confirms that every item above marked APPROVED is
accurate, that no placeholder or invented business information remains, and that
the platform may be launched **with payments still in test mode** until a separate
live-payment approval is given.

| Role | Name | Signature | Date |
|---|---|---|---|
| Business owner | | | |
| Operations | | | |
| Finance | | | |

> Do not update `docs/FINAL_PRODUCTION_READINESS_REPORT.md` to
> **READY FOR CONTROLLED PRODUCTION LAUNCH** until every row is APPROVED or
> NOT APPLICABLE *and* the launch gates in
> `docs/PRODUCTION_LAUNCH_APPROVAL.md` have passed on the host.
