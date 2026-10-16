# Launch Content Checklist — AA Shinaka Digital Business Platform

**Phase:** 12. **No content is invented here.** Every item must be supplied or
approved by the business owner. Placeholders must be replaced before launch.

> Rule from `AGENTS.md`: never hardcode product categories, state-specific
> prices, inventory or company achievements. This checklist is where the owner
> provides the real values.

---

## 1. Company & brand

- [ ] Legal entity name, trading name, registration number(s).
- [ ] Registered address, phone number(s), public email addresses.
- [ ] Company logo (SVG/PNG) and favicon.
- [ ] Brand colours confirmed against the design tokens.
- [ ] Social links (only channels that actually exist).

## 2. Corporate pages (CMS)

- [ ] Home hero headline, sub-headline, imagery.
- [ ] About / our story, mission, values.
- [ ] Company achievements or milestones — **only real, verifiable ones**.
- [ ] Team/leadership bios and photos (with permission).
- [ ] Services overview copy for each division actually offered.
- [ ] Contact page: real address, phone, hours, map.
- [ ] Legal: terms of service, privacy notice, cookie notice, refund policy.

## 3. Catalogue

- [ ] Real categories (no placeholders), each with a description and image.
- [ ] Products with correct names, units of measure and descriptions.
- [ ] Listings with **owner-approved** prices and stock per state/LGA.
- [ ] Product images (owner-supplied; no stock photos implying false capability).
- [ ] Featured products selected deliberately.

## 4. Locations

- [ ] Nigeria locations imported: 37 states + 774 LGAs
      (`import_nigeria_locations --source FILE --strict`).
- [ ] Any city/coverage statements match the imported dataset.

## 5. Services & export

- [ ] Consultancy/farming/marketing/storage/service descriptions and pricing
      rules approved.
- [ ] Export destinations offered are approved; incoterms default confirmed.
- [ ] Export eligibility flags set on the correct products.
- [ ] Compliance document types configured for the destinations offered.

## 6. Training

- [ ] Real courses, modules, lessons and resources (owner-supplied).
- [ ] Sessions scheduled with real dates, venues and fees.
- [ ] Instructors assigned; certificate templates reviewed.

## 7. Payments & finance

- [ ] Currency/ies confirmed (per-currency, no mixing).
- [ ] Tax handling confirmed (`ORDER_TAX_RATE`; 0.00 until configured).
- [ ] Bank-transfer instructions accurate, or Paystack-only.
- [ ] Refund policy wording matches operations.
- [ ] Paystack remains in **test mode** until the owner explicitly approves live
      keys (a launch gate, not a checklist item to tick early).

## 8. Communications

- [ ] `DEFAULT_FROM_EMAIL` uses a real, monitored mailbox.
- [ ] Notification email templates reviewed; `SITE_URL` set so links are absolute.
- [ ] SMS/WhatsApp **left disabled** unless an approved provider is configured.

## 9. SEO, accessibility, legal

- [ ] `robots.txt` / sitemap reflect the launch domain.
- [ ] Meta titles/descriptions on key pages.
- [ ] Accessibility spot-check (see `docs/PERFORMANCE.md` §accessibility).
- [ ] Analytics/tracking (if any) respects the cookie notice.

## 10. Sign-off

| Role | Name | Date |
|---|---|---|
| Business owner | | |
| Operations | | |
| Finance | | |

Only after every row above is checked may `docs/FINAL_PRODUCTION_READINESS_REPORT.md`
be updated from `READY FOR STAGING` to `READY FOR CONTROLLED PRODUCTION LAUNCH`.
