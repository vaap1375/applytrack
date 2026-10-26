# ApplyTrack — resume and interview notes

## Recommended resume bullets

- Built and deployed a private job application tracker using React, TypeScript, FastAPI, and Neon PostgreSQL on Render, with persistent Supabase authentication, owner-scoped access, status history, and timezone-aware reminders.
- Implemented editable job-posting imports for Greenhouse, Lever, Ashby, and structured metadata, with duplicate detection and SSRF protections covering DNS validation, IP-pinned connections, redirects, timeouts, and response limits.
- Developed read-only Gmail OAuth integration with encrypted refresh tokens, resumable deduplicated sync, explainable email matching, guarded status updates, and audited undo; validated the application with 206 backend and 44 frontend tests.

## Evidence and technologies

React, TypeScript, Vite, Tailwind CSS, Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL/Neon, Supabase Auth, Google Gmail API, Docker, Render, and GitHub Actions.

The owner verified production deployment, Supabase email/password login, the authenticated dashboard, application creation persisted in Neon, reminder functionality, and Gmail OAuth. The preceding production initialization reached Alembic `0002 (head)`. This final documentation pass performs no production migrations or tests.

Current local checks: **206 backend tests**, **44 frontend tests**, separate TypeScript compilation, optimized frontend build, safe test-database migration/schema checks, and production Docker image/smoke checks. See VERIFICATION.md for exact results and security scan evidence. Synthetic fixtures and mocked transports establish regression behavior, not real-world email accuracy.

## Interview talking points

- **Architecture:** one Render web service serves compiled React and the API on the same origin; Neon keeps records separate from ephemeral container storage. Explain why that is appropriate for a private personal tool.
- **Authentication:** Supabase persists and refreshes browser sessions; FastAPI independently verifies asymmetric JWT issuer/audience/expiry and enforces the configured owner. Discuss localStorage's XSS trade-off and why frontend checks alone are insufficient.
- **Persistence:** SQLAlchemy models, additive Alembic revisions, a direct migration connection versus pooled runtime connections, TLS, bounded connection pooling, and safe test-database isolation.
- **Job extraction:** use public platform endpoints before structured metadata; treat all fetched content as untrusted. Explain how validating DNS without pinning the socket would leave a rebinding gap.
- **Gmail:** read-only scope, one-time state plus browser binding and PKCE, encrypted owner-bound refresh tokens, bounded incremental sync and checkpoints. Matching evidence includes company/title/job identifiers and ambiguity; do not equate a confidence threshold with measured accuracy.
- **Change safety:** row locks and status revisions prevent stale mail/review actions from overwriting newer manual changes; terminal-status guards and audited undo keep the owner in control.
- **Testing:** separate owner-isolation and security regressions from mocked service behavior. Explain what a passing fixture cannot prove about real mail, browser sessions, provider changes, or deployment uptime.

## Honest limitations

Gmail synchronization is manual; production synchronization has not been separately confirmed by the owner. There is no scheduled inbox monitor or external reminder notification system. Real recruiting-email matching accuracy, user scale, latency, and uptime are not measured. Automatic changes default off and require reviewed dry-run evidence before opt-in. Screenshot capture and browser/mobile/accessibility checks remain manual; use demo data only. Previously exposed Google client-secret rotation remains an owner responsibility unless already completed.
