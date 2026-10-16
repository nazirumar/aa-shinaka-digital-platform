# Data Protection & Privacy — AA Shinaka Digital Business Platform

**Phase:** 12. This is an engineering control document, not legal advice. Confirm
obligations with the business owner / counsel before launch.

---

## 1. Personal data we process

| Category | Examples | Where |
|---|---|---|
| Identity/contact | name, email, phone, address | `accounts.User`, `accounts.Address` |
| Order/payment | order contents, amounts, provider references, bank-transfer proofs | `orders.*` |
| Service records | consultancy/farming/marketing/storage requests, reports | `services.*` |
| Export records | enquiries, incoterms, compliance documents | `export.*` |
| Training records | enrolments, attendance, certificates | `training.*` |
| Support records | tickets, messages, attachments | `support.*` |
| Audit | who did what, when | `dashboard.AuditLog` |

No card numbers or bank credentials are ever stored: card data stays with the
payment provider (Paystack); only provider references and verified amounts are
persisted.

---

## 2. Controls in force

- **Access control:** every sensitive record is gated by ownership or a
  capability (`apps/accounts/permissions.py`); templates only hide navigation.
  Object-level checks are verified by tests.
- **Least privilege:** ten canonical roles → Django groups `role:<code>`; the
  production database user needs only DML on its schema (no superuser).
- **Transport:** TLS in front of the app; `SECURE_SSL_REDIRECT`, HSTS, secure
  cookies, `X-Forwarded-Proto` trust only behind the proxy.
- **At rest:** uploaded documents live under `MEDIA_ROOT`; production nginx
  default-denies `/media/` and private files are streamed through authorised
  views. Backups can be encrypted (`age`/`gpg`).
- **Passwords:** Django hashers (PBKDF2 default, Argon2/bcrypt available);
  minimum-length and common-password validators.
- **Sessions:** secure/HttpOnly/SameSite cookies; age from env; invalidated on
  password change; login rate-limited.
- **Audit trail:** privileged actions write `AuditLog` rows.

---

## 3. Data minimisation & retention

- Collect only what a workflow needs; no free-form PII in logs.
- Retain financial/order records as long as the business/tax rules require;
  support attachments and exports are the likely first candidates for pruning.
- `ReportExport` files are generated artefacts; schedule their deletion when
  retention is defined (report exports are gated by capability meanwhile).
- Backups have a 30-day local / 90-day off-site target; deletion of a record is
  not immediate in old backups — document this in any privacy notice.

---

## 4. Subject requests (access / correction / deletion)

1. Verify the requester's identity (do not act on an unverified email).
2. **Access/portability:** export the subject's records from the staff dashboard
   or a management shell; money/order records are read-only snapshots.
3. **Correction:** update the `User`/`Address` record; never edit financial
   ledger rows — issue a corrective transaction instead.
4. **Deletion:** soft-delete where the schema supports it (`SoftDeleteModel`),
   and purge hard copies from media/backups per the retention policy. Financial
   records that must be retained are redacted where possible, not destroyed.
5. Log the request and its resolution.

---

## 5. Breach response (summary)

1. Contain: disable the exposed credential/path, rotate secrets.
2. Assess: what data, how many subjects, is it still accessible?
3. Notify: follow the applicable regulatory timelines and inform affected users
   where required.
4. Remediate and record the incident (`docs/DISASTER_RECOVERY.md` post-incident
   step).

---

## 6. Known gaps

| Gap | Impact | Plan |
|---|---|---|
| No malware scanning of uploads | a malicious file could be stored | add async AV scan (audit M-4) |
| Backups are not encrypted by default | sensitive if a backup leaks | set `BACKUP_AGE_RECIPIENT`/`BACKUP_GPG_RECIPIENT` in production |
| No automated retention/deletion job | data may be kept longer than needed | define retention with the owner, then schedule |
| MFA not implemented for privileged staff | account takeover risk | required before general-availability launch |
