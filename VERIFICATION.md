# Verification — 2026-10-26

Executed against this existing workspace. Tests use synthetic records/mocked external services and a separate local `applytrack_test` PostgreSQL database. No production cloud deployment was performed.

| Check | Executed result |
| --- | --- |
| Backend full suite | **206 passed**, one Starlette/httpx TestClient deprecation warning; 6.27 seconds on this run |
| Frontend suite | **44 passed**, 7 files |
| Frontend America/Detroit rerun | **44 passed**, 7 files |
| TypeScript + Vite build | Passed via `npm run build`; optimized assets generated |
| Alembic upgrade/check/current | Passed; no new upgrade operations; `0002 (head)` |
| npm dependency audits | Zero reported vulnerabilities, full and production-only |
| Pinned Python dependency audit | Zero reported vulnerabilities after pytest upgrade to 9.0.3 |
| Gitleaks 8.30.1 | Zero findings in publication candidate; redacted output |
| Private `.env` literal comparison | Zero private secret-value matches in source candidate or frontend build |
| Production Docker image | Built successfully; UID 10001; no `/app/.env` |
| Existing Compose services | Rebuilt backend/frontend; started successfully; PostgreSQL healthy |
| Personal record preservation | Read-only fingerprints of all existing public tables matched before/after service rebuilds |
| Browser E2E / screenshots | Not run: browser discovery returned no connected browsers |
| GitHub Actions | Workflow prepared; hosted run unavailable before publication |

The 22 new backend checks cover production configuration rejection, TLS URL normalization, static assets and SPA refresh, private-path rejection, HTTPS/host/security headers, sanitized readiness failure, dynamic port/graceful shutdown settings, redacted configuration errors, and unauthenticated rejection across all documented protected API operations.

## Container smoke checks

The root image was built with **synthetic public** Supabase values, not the owner's credentials. An isolated container on loopback port 18000 used the disposable test database and synthetic auth configuration:

- `/health`, `/ready`, `/`, and `/applications/example`: **200**.
- Applications, reminders, and Gmail connection requests without credentials: **401**.
- Unknown `/api/*`, `/.env`, and missing assets: **404**.
- Restarting that web container preserved database readiness (**200**). Personal database records were only read for comparison and were not modified.

A second container on port 18001 ran with `APP_ENV=production`, a synthetic HTTPS origin, and simulated trusted proxy headers:

- HTTPS-forwarded `/health` and `/`: **200**, HSTS present.
- Protected API: **401**; unknown API: **404**; HTTP ingress: **400**.
- `/ready`: **503**, as expected because the local PostgreSQL server does not support the production-required TLS connection. **A real Neon/TLS connection has not been tested.**

The existing local Compose frontend at `http://localhost:5173` and backend `/health` at `http://localhost:8000/health` returned **200** after rebuild. Smoke containers are separate from those services and may be removed without affecting the personal database.

## Commands

```sh
cd backend
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest -q
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic check
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic current
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest tests/test_gmail.py -k precision_report -s -q
cd ../frontend
npm test
TZ=America/Detroit npm test
npm run build
npm audit
npm audit --omit=dev
```

The separate fixture report passed **2 tests (75 deselected)**: classification high-confidence **10/10**, all labels **24/24**; unique application matches **2/2**, abstained **2/4**. These are curated regression examples, not real-world performance or accuracy measurements.

## Review coverage and remaining manual checks

The existing suites cover application CRUD/search/filter/pagination/history/owner isolation; job platform/generic fixtures, missing/malformed content, duplicates and SSRF; reminder CRUD/completion/reopening/timezone/DST behavior; Supabase restoration/refresh/logout/invalid-session behavior; Gmail OAuth/PKCE/state/cookie/token/revocation handling; parsing/classification/matching; incremental/partial/repeated sync; review approval/dismissal; stale/manual/terminal guards; undo/audit; and frontend critical forms and navigation.

External network transports are controlled in tests. Live platform posting templates, actual Supabase/browser refresh/revocation behavior, cloud HTTPS/proxy/CSP behavior, accessibility, mobile layout, and genuine recruiting-email decisions still require [manual verification](docs/SCREENSHOTS.md). The owner reports real Gmail OAuth and an initial 12-message sync with zero matches or changes; this is connectivity evidence only. Automatic status changes should stay disabled until real dry-run results are reviewed.

There was no pre-existing local Git history. The intended public remote was empty; the authenticated account had no push permission. Local source publication is documented in [the security review](docs/SECURITY.md). No hosted CI success, deployment, credential rotation, backup restore rehearsal, or scheduled Gmail sync is claimed. Existing `.env` and encryption-key values were preserved.
