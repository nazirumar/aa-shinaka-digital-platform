# Phase 9 — Training academy

**Status:** Complete (see owner approval before Phase 10)
**Date:** 2026-10-15

## Objective delivered

Phase 9 gives AA Shinaka its **own** training academy as a first-class, auditable
workflow on the Phase 2–8 foundations: a configurable catalogue (categories,
courses, modules, ordered lessons and private resources), instructors and
assignments, venues and **capacity-limited cohorts**, enrolment with
**waitlisting**, **verified-only** course payment, attendance registers, assessments
with automatic and manual grading, **derived** completion and staff-approved
certificates — served through the public site (`/training/`), a student portal
(`/account/training/`) and a capability-gated staff dashboard
(`/dashboard/training/`) whose Chart.js reports are derived strictly from real
records.

It is implemented in the **dedicated `apps.training` app** (kept separate from
`catalog`/`orders`, matching the domain-oriented layout). Course payment reuses
the Phase 6 verified-payment pipeline through `orders.Payment.training_enrollment`;
notifications reuse `orders.notifications.send_notification`; certificates render
with the dependency-free `orders.documents` PDF helper. Nothing is hardcoded —
categories, courses, cohorts, instructors, venues, fees and capacities are records.

The hard rules hold throughout:

- **Nothing is invented.** Categories, courses, cohorts, instructors, venues,
  fees, capacities, schedules and certificates are records. Empty states never
  fabricate courses, dates or people.
- **No paid state from the browser.** A paid seat confirms only after
  server-side verification through the Phase 6 pipeline; the browser callback is
  re-verified and is never the source of truth. The Phase 6 logic is **not
  duplicated** — `apps/training/payments.py` is a thin, idempotent bridge.
- **Capacity is enforced transactionally.** A full cohort yields `waitlisted`;
  duplicate active enrolments, closed sessions and passed deadlines are rejected.
- **Completion is derived, never assumed.** A course completes only when every
  lesson is complete **and** every published, completion-required assessment is
  passed; empty content never completes.
- **Certificates are governed.** Issuing/revoking requires `TRAINING_APPROVE` and
  a completed, certificate-eligible course; public verification exposes only the
  minimum approved information.
- Money is always `Decimal`; every sensitive change writes an `AuditLog` row
  (and enrolment history rows where applicable).
- Authorisation is enforced in services/views — templates only hide navigation.
  Students can only ever see and act on their own records.
- Hard exclusions still hold: no oil & gas, no marketplace, no AgriTrade ERP, no
  hardcoded categories/prices/inventory/achievements.

> **Scope note.** The roadmap originally pencilled Phase 9 as the customer-portal
> & notification consolidation and deferred the academy (split out of Phase 8).
> This engagement **repurposes Phase 9 as the Training academy**; the portal
> consolidation moves to Phase 12 in the roadmap. `docs/` reflect this.

## Files created/modified

### Apps — `apps/training` (new)
- `apps.py` — app config `TrainingConfig`.
- `models.py` — the whole Phase 9 schema, status enumerations and the transition
  maps `COURSE_TRANSITIONS`, `SESSION_TRANSITIONS`, `ENROLLMENT_TRANSITIONS`
  (see “Models”).
- `services.py` — the write layer: categories (`upsert_category`,
  `set_category_active`), courses (`create_course`, `update_course`,
  `transition_course`, `publish_course`, `archive_course`), content
  (`add_module`/`update_module`, `add_lesson`/`update_lesson`, `add_resource`),
  access (`can_access_lesson`, `can_access_resource`), instructors
  (`create_instructor_profile`, `assign_instructor`, …), venues, cohorts
  (`create_session`, `update_session`, `transition_session`), enrolment
  (`submit_enrollment`, `transition_enrollment`, `cancel_enrollment`,
  `settle_enrollment_payment`), attendance (`create_attendance_session`,
  `record_attendance`), assessments (`create_assessment`, question/option
  helpers, `publish_assessment`, `submit_assessment`, `grade_submission`),
  progress (`mark_lesson_complete`, `record_lesson_view`, `recompute_progress`)
  and certificates (`issue_certificate`, `revoke_certificate`,
  `verify_certificate`).
- `selectors.py` — reads/metrics: `active_categories`, `published_courses`,
  `course_modules`/`course_lessons`/`course_resources`, `upcoming_sessions`,
  `enrollments_for`, `attendance_summary`, `published_assessments`,
  `lesson_progress_map`, `course_progress`, staff queues (`staff_courses`,
  `staff_sessions`, `staff_enrollments`, `staff_certificates`), `overview_metrics`,
  `verified_revenue`, `completion_rate`, `course_popularity`.
- `payments.py` — `initialize_training_payment` bridge + idempotent
  `settle_training_payment` (called by Phase 6 verification).
- `notifications.py` — per-event email helpers and `TrainingNotificationLog`
  (date/event-keyed dedupe).
- `documents.py` — certificate PDF rendering.
- `validators.py` — resource/upload validation.
- `forms.py` — student enrolment and staff catalogue/cohort/assessment forms.
- `views.py` / `urls.py` — public academy (`app_name="training"`).
- `account_views.py` / `account_urls.py` — student portal
  (`app_name="training_account"`).
- `dashboard_views.py` / `dashboard_urls.py` — gated staff dashboard
  (`app_name="training_dashboard"`).
- `tasks.py` — `send_session_reminders` (date-keyed, idempotent).
- `notifications.py`/`documents.py`/`validators.py` as above.
- `admin.py` — **read-only** registrations (writes must go through services).

### Apps — `apps/orders` (modified)
- `payment_models.py` — `Payment.training_enrollment` FK (`related_name="payments"`)
  and the updated `chk_payment_single_target` constraint (four targets).
- `payments.py` — `initialize_training_payment`, `_training_callback_url`, and a
  branch in `_apply_verification` that settles a training payment.
- `notifications.py` — label/context handling for a training payment.

### Config, capabilities & navigation
- `apps/accounts/roles.py` — `TRAINING_MANAGE` + `TRAINING_INSTRUCT` (Training
  Manager) and `TRAINING_APPROVE` (Administrators/Owners via `ALL_CAPABILITIES`);
  `sync_roles` refreshed.
- `config/settings/base.py` — `apps.training` added to `INSTALLED_APPS`.
- `config/urls.py` — mounts `/training/`, `/account/training/` and
  `/dashboard/training/`.
- `templates/training/` — public academy templates (home, course list/detail,
  category, session list/detail, verify).
- `templates/training/account/` — student-portal templates.
- `templates/dashboard/training/` — staff templates (overview + Chart.js reports,
  categories, courses/modules/lessons/resources, instructors/assignments, venues,
  sessions/schedules, enrolments, attendance, assessments/grading, certificates/
  templates, `_nav`).
- `templates/dashboard/base.html` — Training sidebar section.
- `templates/accounts/account_base.html` — training portal link.
- `templates/components/navbar.html` — academy link.

## Migrations

- `training/0001_initial.py` — all Phase 9 models/enums/constraints.
- `orders/0006_payment_training_enrollment_and_more.py` — `Payment.training_enrollment`
  + updated single-target constraint.

All migrations are generated, reviewed and applied; `makemigrations --check`
reports no missing migrations. **No training category, course, instructor, venue,
fee, capacity or achievement is hardcoded.**

## Models

Catalogue:

- `TrainingCategory` (SluggedMixin, self-nesting via `parent`, `is_active`).
- `Course` (category, title/slug, summary/description/objectives, `delivery_mode`,
  duration, fee, cover image, `status` `CourseStatus`, `certificate_eligible`,
  published timestamp). Enrolment is via a cohort.
- `CourseModule` → `CourseLesson` (`sort_order`, unique per module via
  `uniq_lesson_module_order`; `lesson_type`, `is_preview`, content/media).
- `CourseResource` (private document/link attached to a course or lesson).

People & logistics:

- `InstructorProfile` (one per user) and `InstructorAssignment` (course and/or
  session, role, active window).
- `TrainingVenue`; `TrainingSession` (cohort with `status` `SessionStatus`,
  capacity, fee, start/end, enrolment deadline, venue, instructor);
  `TrainingSessionSchedule` (dated topic lines).

Enrolment & attendance:

- `Enrollment` (ref `AS-ENR-…`, student, session, `status` `EnrollmentStatus`,
  payment fields `amount_paid`/`payment_status`/`settled_payment_references`,
  confirmed/completed timestamps, derived `balance_due`); `EnrollmentRequirement`;
  `EnrollmentStatusHistory` (append-only).
- `AttendanceSession` (one per cohort per date) and `AttendanceRecord`
  (`AttendanceStatus`).

Assessments, progress & certificates:

- `Assessment` (type, max attempts, pass mark, `completion_required`, published) →
  `AssessmentQuestion` → `AssessmentOption`; `AssessmentSubmission` (answers JSON)
  and `AssessmentResult` (score, pass, grader).
- `LessonProgress`, `CourseProgress` (derived).
- `CertificateTemplate`, `Certificate`, `CertificateVerificationLog`.

`orders.Payment.training_enrollment` is a fourth payment target alongside shop
`order`, `service_quotation` and `export_order`; `chk_payment_single_target`
enforces exactly one target.

Status enumerations (`apps/training/models.py`):

```
CourseStatus           : draft | published | archived
DeliveryMode           : in_person | online | hybrid | self_paced
SessionStatus          : draft | scheduled | enrollment_open | enrollment_closed |
                         in_progress | completed | cancelled
EnrollmentStatus       : pending | payment_pending | confirmed | waitlisted |
                         cancelled | completed
EnrollmentPaymentStatus: not_required | pending | paid | partially_paid |
                         refunded | failed
AttendanceStatus       : present | absent | late | excused
AssessmentType         : quiz | assignment | practical | exam
QuestionType           : multiple_choice | true_false | short_answer
SubmissionStatus       : draft | submitted | graded | returned
CertificateStatus      : issued | revoked
```

`COURSE_TRANSITIONS`, `SESSION_TRANSITIONS` and `ENROLLMENT_TRANSITIONS` declare
the legal moves.

## Public URLs (`/training/…`)

- `/training/` (`training:training_home`)
- `…/courses/`, `…/courses/<slug>/`, `…/categories/<slug>/`
- `…/sessions/`, `…/sessions/<uuid>/`, `…/sessions/<uuid>/enrol/`
- `…/verify/`, `…/verify/<code>/` — public certificate verification
- `…/payments/callback/<reference>/` — server-side re-verify

## Student portal URLs (`/account/training/…`)

- `/account/training/` (`training_account:home`), `…/courses/`, `…/sessions/`
- `…/enrolments/`, `…/enrolments/<reference>/`,
  `…/enrolments/<reference>/pay/`, `…/enrolments/<reference>/cancel/`,
  `…/enrolments/<reference>/lessons/<lesson_id>/complete/`,
  `…/enrolments/<reference>/assessments/<assessment_id>/`
- `…/resources/<uuid>/download/`
- `…/certificates/`, `…/certificates/<uuid>/`, `…/certificates/<uuid>/download/`
- `…/payments/`

## Staff dashboard URLs (`/dashboard/training/…`, `TRAINING_MANAGE`)

- `/dashboard/training/` — overview + Chart.js reports.
- `…/categories/…`, `…/courses/…` (modules/lessons/resources; publish/archive
  requires `TRAINING_APPROVE`).
- `…/instructors/…`, `…/assignments/…`, `…/venues/…`.
- `…/sessions/…` (+ schedules, transitions).
- `…/enrollments/…` (+ actions).
- `…/attendance/…` (+ marking).
- `…/assessments/…` (+ questions/options, publish, grade).
- `…/certificates/…`, `…/templates/…` (issue/revoke requires `TRAINING_APPROVE`).
- `…/reports/` — Chart.js reports.

Every screen enforces its capability server-side; templates only hide navigation.
Student records are scoped to their owner (cross-student access is rejected in the
service/view layer).

## Verified-payment settlement (Phase 6 integration)

```
customer enrols on a paid cohort -> Payment(training_enrollment=…)
        -> Paystack hosted page
        -> callback OR signed webhook
        -> server verifies amount/currency (authoritative)
        -> _apply_verification(...) -> settle_training_payment(payment)   [idempotent]
              -> settle_enrollment_payment(enrollment, payment)
                    -> enrollment.amount_paid += verified amount
                    -> if fee met: status = confirmed (payment_status = paid)
```

- `orders.Payment` targets exactly one of
  `order`/`service_quotation`/`export_order`/`training_enrollment`.
- Idempotency is keyed on `Enrollment.settled_payment_references`, so a repeated
  callback/webhook cannot double-credit.
- Only a **verified** payment is applied; a partial payment leaves the enrolment
  pending (and, under the Phase 6 rules, is not silently settled). The browser
  callback alone never confirms an enrolment.
- `selectors.verified_revenue` counts only verified training payments.

## Tests

69 new tests in `tests/test_training.py` (+ `tests/training_helpers.py`):

- **Catalogue**: category capability toggle and active listing; course publication
  gate; illegal transition rejected; lesson preview visibility and private access;
  resource access control.
- **Instructors**: profiles + assignments; a non-assigned instructor cannot teach
  an unrelated course.
- **Cohorts**: schedule validation and transitions.
- **Enrolment**: free confirms immediately; paid requires payment; capacity and
  waitlisting; duplicate active enrolment; closed sessions and deadlines rejected;
  ownership enforced; cancellation scoping.
- **Payments**: Paystack-disabled guard; ownership/target checks; verified payment
  confirms an enrolment **idempotently**; partial payment stays pending; settlement
  ignores non-training payments; a browser callback cannot confirm.
- **Attendance**: trainer gate; register creation + duplicate rejection; record
  update (no duplicates); unknown status rejected.
- **Assessments**: publish requires a question; objective auto-grading (pass/fail);
  attempt limits and gates; short answers require manual grading;
  published-only listings.
- **Progress**: confirmed-student gate; recompute + completion; empty content never
  completes; un-completing a lesson reverts progress.
- **Certificates**: `TRAINING_APPROVE` + completion required; non-eligible course
  blocked; duplicate blocked; revoke + public verify; verification attempts
  recorded; PDF renders.
- **Public site**: draft filtering; draft detail 404; category/session pages;
  unpublished-course session hidden; certificate verification.
- **Portal & views**: enrol view (login + creation); strict per-student scoping;
  assessment take requires own confirmed enrolment; resource-download gate;
  notification dedupe; reporting metrics; dashboard capability gate; publish/
  certificate-approve gates; staff smoke pages.
- **Tasks**: session-reminder idempotency.
- **URLs**: full reversal coverage across all three URLconfs.

Real defects found and fixed by the suite:

1. **`mark_lesson_complete` referenced a non-existent column.** The service
   compared `lesson.course_id`, but a `CourseLesson` reaches its course only
   through `lesson.module.course`; every lesson-completion call raised
   `AttributeError`, which broke progress and derived completion. Fixed to
   compare `lesson.module.course_id` with `enrollment.session.course_id`.
2. **Two lessons in one module shared an order.** The preview/private-lesson
   test created both lessons with the helper's default `sort_order`, violating
   `uniq_lesson_module_order`; the test now assigns explicit distinct orders (the
   unique constraint is the application behaviour under test). This was a
   test-harness defect, not an application defect.

## Quality gates (end of Phase 9)

Run in this order:

- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — 217 files already formatted.
- `uv run pytest` — **590 passed**, 14 warnings (42m15s). The 14 warnings are
  pre-existing Django 6.0 deprecation notices (`forms.URLField` scheme) and a
  pytest collection notice for a CMS model named `Testimonial`.
- `uv run python manage.py check` — clean ("no issues, 0 silenced").
- `uv run python manage.py makemigrations --check --dry-run` — "No changes
  detected".
- `npm run build:css` — built after template/class changes.

> One pre-existing, non-Phase-9 flaky test was hardened while running the gate.
> `tests/test_catalog_pricing.py` selected the most recent `PriceHistory` row via
> `order_by("-created_at")`, but `created_at` is `auto_now_add` and the fixture
> creates several rows within the same clock tick, so the ordering tied
> non-deterministically under full-suite load. The two affected assertions now
> select the historical row by its uniquely-known `new_price` instead of relying
> on recency. No application behaviour changed (the append-only log itself was
> always correct).

## Remaining work / not in scope

- **Customer-portal & notification consolidation** — renumbered to Phase 12 (the
  training academy now occupies Phase 9).
- Live streaming/SCORM, video hosting, discussion forums and paid-in-instalments
  plans are out of scope.
- SMS/push notifications are out of scope (email only).
- DRF remains deferred — no machine client requires it yet.
- Phase 10 must **not** start without explicit owner approval.
