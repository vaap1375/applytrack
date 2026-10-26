# ApplyTrack — resume notes

## Implemented

A React/TypeScript job application workspace with FastAPI, PostgreSQL, SQLAlchemy/Alembic, Supabase private-owner authentication, public posting extraction, local-time reminders, and read-only Gmail integration. Production packaging serves React and API from one non-root Docker image; a Render/Neon deployment guide and GitHub Actions workflow are prepared.

Engineering challenges: SSRF-safe IP-pinned requests with DNS/redirect validation; persistent browser sessions with server-side JWT enforcement; UTC/local reminder boundaries; encrypted OAuth tokens and browser-bound state/PKCE; resumable, deduplicated email processing; ambiguous-match abstention; source-time/manual-edit/revision guards; auditable approval and undo.

## Verified here

- **206 backend tests passed**, including CRUD/owner isolation/history, URL extraction/SSRF, reminders, Gmail security/matching/sync/review/undo, and 22 production hosting/authentication checks.
- **44 frontend tests passed** across 7 files, also passing under America/Detroit; TypeScript and Vite production build passed.
- Production Docker build and local runtime routing/health/restart checks passed; Compose services rebuilt and started; personal data fingerprints remained unchanged. Alembic reports `0002 (head)` and no schema drift.
- Gitleaks reported zero candidate-source findings; final dependency audits reported zero known vulnerabilities after updating pytest.
- Synthetic classifier fixtures: 10/10 high-confidence predictions correct and 24/24 labels correct. Synthetic matching fixtures: 2/2 unique matches correct; 2/4 cases abstained. These small curated fractions **do not establish real-world accuracy** or performance.
- Owner-reported real OAuth connection and a 12-message sync with zero matches/updates establish connectivity only. No scale, latency, production uptime, or real-mail accuracy metric has been established.

## Candidate resume bullets

- Built a private job application tracker with React, TypeScript, FastAPI, and PostgreSQL, integrating persistent Supabase authentication, owner-scoped CRUD, status history, and timezone-aware follow-up reminders.
- Implemented job-link extraction across Greenhouse, Lever, Ashby, and structured metadata with DNS/IP validation, redirect checks, bounded fetches, editable previews, and duplicate detection.
- Developed read-only Gmail integration with encrypted OAuth credentials, resumable deduplicated sync, deterministic email matching, guarded status suggestions, and audited undo; validated the application with 206 backend and 44 frontend tests.

## Planned / not claimed

Cloud deployment, continuous Gmail monitoring, a hosted scheduler, external reminder notifications, real recruiting-email accuracy evaluation, and automated browser E2E coverage remain outstanding. The code is prepared for publication; GitHub write access is currently unavailable, so no successful push or hosted CI run is claimed. Browser/mobile checks and sanitized screenshots remain manual. Rotate the previously exposed Google OAuth client secret before deployment.
