# ApplyTrack

A private, single-owner job application tracker. React/TypeScript/Vite/Tailwind frontend; FastAPI/Pydantic/SQLAlchemy backend; PostgreSQL with Alembic migrations. Supabase handles passwords and sessions. The API verifies asymmetric JWT signatures using Supabase JWKS, issuer, audience, expiration, and an explicit owner UUID. Owner identity never comes from request data.

## Prerequisites

Docker Desktop with Compose. For host development: Python 3.12+ and Node 22+ (Node 20.19 also works). Ports 5173, 8000, and **55432** must be available. No deployment is configured.

## Supabase configuration

1. Create a Supabase project. Under Authentication settings, **disable “Allow new users to sign up”** (and anonymous sign-ins). No signup UI is provided here.
2. Create the owner's email/password user through the Supabase dashboard; confirm the email through the dashboard if needed. Copy the user's UUID into `OWNER_ID`.
3. Configure an **asymmetric signing key (ES256 or RS256)** in Supabase JWT signing keys. Legacy HS256 shared-secret tokens are intentionally rejected. The public JWKS endpoint is `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. New sessions must use that asymmetric key.
4. Copy the project URL to `SUPABASE_URL` and `VITE_SUPABASE_URL`. Copy a **publishable key or public anon key** to `VITE_SUPABASE_PUBLISHABLE_KEY`. Never use a service-role key.
5. Use a strong owner password. Password reset and account management currently happen in Supabase's dashboard.

## Start with Docker

From the repository root:

```sh
cp .env.example .env
# Edit .env with the Supabase values and owner UUID above.
docker compose up --build -d
```

Open http://localhost:5173. API docs: http://localhost:8000/docs. Containers automatically migrate the database before starting the API. `GET /health` is public and reports process health; every `/api` endpoint except the state-and-cookie-bound Gmail OAuth callback requires authentication. Missing auth configuration fails closed.

```sh
docker compose logs -f backend
docker compose stop
docker compose start
```

Database data persists in the `postgres_data` named volume across container restarts. `docker compose down` retains it; `docker compose down -v` **permanently deletes it**. Local development defaults are not hosted database credentials. Compose binds ports to loopback. For hosted use, supply managed PostgreSQL credentials, exact HTTPS frontend CORS origins, and serve both applications over HTTPS. Vite's development server is used by Compose; it is not a production hosting setup.

## Host development

```sh
cp .env.example .env
# Configure .env first.
docker compose up -d db
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.lock.txt
cd backend
# The backend reads .env in its working directory; use an ignored symlink.
ln -s ../.env .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

In a second terminal from the repository root:

```sh
npm ci --prefix frontend
cd frontend
ln -s ../.env .env
npm run dev
```

If you already have the symlinks, do not recreate them. Never commit `.env`. Frontend environment variables are public and bundled into the client. Rebuild/restart after configuration changes. `POSTGRES_PORT` can override Compose's 55432 host port; update the host `DATABASE_URL` to match. Container connections use the internal `db:5432` address.

## Migrations

```sh
# Docker service is already configured with the correct DB connection:
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose exec backend alembic check
# Host alternative (from backend with its .env symlink):
.venv/bin/alembic upgrade head
```

The initial migration creates applications, immutable activity events, and the reminders table. Applications have owner/status indexes and database status/name constraints. Events and reminders cascade on application deletion. Updates lock the application row and write status history in the same transaction. Production never uses `create_all`. The API returns 404 for applications belonging to another identity.

## Tests

Use a **separate, disposable PostgreSQL database**, never your application database. Create it once:

```sh
docker compose exec db createdb -U applytrack applytrack_test
```

Run from the repository root (these explicit URLs use local defaults):

```sh
cd backend
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest -q
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic check
cd ..
npm test --prefix frontend
npm run build --prefix frontend
```

Tests isolate each case in a rolled-back database transaction. CRUD tests override FastAPI dependencies only in test fixtures. Authentication tests exercise signed RSA tokens and key selection with a local controlled JWKS. No runtime bypass or fake production data exists. CI runs migrations and backend tests on PostgreSQL and frontend tests/type-check/build without Supabase credentials. No separate lint tool is configured.

## Functionality

- Email/password login and logout; owner-only API access.
- Dashboard counts for all seven statuses and clickable pipeline filters.
- Paginated company/title search with literal wildcard handling and status filtering.
- Add/edit/detail/delete, HTTP(S) job links, external job IDs, application date, notes, quick status changes, and activity timeline.
- Paste a public job URL to preview editable details before saving. New forms default to Applied; this does not verify application submission.
- Loading, empty, success, validation, and request error states; deletion confirmation; responsive navigation.
- All timestamps stored with timezone awareness; application dates entered as local calendar dates and stored at local noon to minimize date drift. API callers must send timezone-aware datetimes.

Supabase sessions now persist across refreshes using the supported `persistSession`/`autoRefreshToken` options and a browser localStorage adapter, under `applytrack.auth`. Startup waits for session restoration and a Supabase `getUser` check before opening the workspace; the backend continues verifying each JWT and owner UUID independently. Sign-out removes this browser's saved session and attempts to revoke its refresh token. See the persistence/security details below.

## Limitations

There is no signup, password recovery UI, browser-based scraping, calendar integration, AI, bulk import/export, or seed data. Job URL preview is available as described below. History records creation, status changes, and generic edits, not sensitive note snapshots. List order is last-updated first; history is currently unpaginated. Search is simple case-insensitive substring search. Database backups and production hosting are not configured. A real Supabase login requires your credentials and must be verified manually. No Playwright browser suite is included.

## Manual verification

- Configure Supabase, disable public signup, create owner, and sign in.
- Add an application with URL, date, notes, and status; verify the dashboard and list update.
- Search company/title, filter each status, and paginate after adding more than ten records.
- Open details, change status, edit notes, and confirm the timeline and counts update.
- Refresh and verify the session restores and the saved record remains.
- Restart containers and verify persistence; test at narrow mobile width and using the keyboard.
- Cancel deletion, then confirm deletion and verify counts/history are removed.
- Sign out and confirm the workspace is inaccessible. Try another Supabase user: the API must reject it with 403.
- Request `/api/applications` without a token: expect 401 with configured auth (503 if unconfigured).

## Troubleshooting

- **503 Authentication is not configured**: supply `SUPABASE_URL` and `OWNER_ID` to the backend and restart it.
- **401**: sign in again; confirm issuer URL, asymmetric signing keys and outbound backend access to Supabase JWKS.
- **403**: the signed-in user's UUID does not match `OWNER_ID`.
- **Browser network/CORS errors**: verify `VITE_API_URL`, API health, and exact `CORS_ORIGINS` (comma separated; wildcards are rejected).
- **Database unavailable**: inspect `docker compose ps` and `docker compose logs db`; host tools use port 55432, containers use 5432.
- **Port occupied**: stop the conflicting project or adjust the Compose port and environment URLs. Do not delete another project's data.

## Job URL auto-fill

In **Add application**, paste a posting into the top Job URL field and select **Auto-fill from link**. Review company, role, location, external job ID, and the job description (added as plain text to Notes). Correct any value, then explicitly select **Add application**. Preview does not create/update a record or submit anything to an employer. Missing fields stay blank (or retain existing manual entries), and manual entry remains available on failure. Applied is only a tracking default, not a verified submission. Editing existing applications retains their status and uses the normal manual form.

The authenticated endpoint is `POST /api/job-import/preview` with JSON `{"url":"https://…"}`. It returns nullable extracted fields, `canonical_url`, `source`, `missing_fields`, `warnings`, and owner-scoped `duplicate_ids`. Duplicate warnings compare external job IDs or normalized URLs against your saved records only. Normalization removes fragments, trailing slashes, and recognized tracking parameters while preserving identity parameters such as `gh_jid`. Same-host canonical metadata is accepted; cross-host/unsafe canonical hints are ignored. Existing records are not fetched remotely to resolve old redirects, and duplicate detection is advisory rather than a uniqueness constraint. Bare IDs can collide between employers; review warnings before saving.

Supported extraction paths:

- **Greenhouse** hosted `/BOARD/jobs/ID` links: [documented public Job Board API](https://docs.greenhouse.io/job-board.html).
- **Lever** hosted `/BOARD/ID` links (global and EU): [documented public Postings API](https://github.com/lever/postings-api).
- **Ashby** hosted `/BOARD/ID` links: [documented public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api), selecting the requested job from the public board response.
- Other public pages: JobPosting JSON-LD (including arrays and `@graph`), then title/Open Graph/description metadata. Metadata may describe the site rather than a job and is labeled accordingly. No employer names are inferred from board slugs. Lever/Ashby employer names require explicit public page data and may need manual entry. Custom ATS domains use the generic extraction path.

Outbound security: only HTTP/HTTPS on standard ports, no URL credentials, only globally routable addresses, and all DNS answers must be public. Each request connects directly to a validated IP while preserving the original Host and verifying the TLS hostname. This prevents a second DNS lookup/rebinding between validation and connection. Redirects revalidate the destination, including same-host redirects. IPv6 translation/tunneling ranges are rejected. No proxies, browser cookies, bearer tokens, or application notes are forwarded. Each preview has a 15-second network budget (including DNS), a maximum of three redirects across its requests, five-second individual operation timeouts, and a 2 MiB limit per response. A bounded DNS worker pool fails closed on resolution failure. Compressed/unsupported responses are rejected; scripts are never executed and extracted markup is converted to plain text.

Limitations: public, server-rendered content only; JavaScript-only pages, authenticated postings, CAPTCHAs, access-denied responses, oversized boards (including Ashby), nonstandard ports, and network restrictions can prevent extraction. No browser automation, private API, proxy workaround, or LLM is used. No new environment values, keys, dependencies, or migrations are required. Rebuild the local containers to pick up source changes with `docker compose up --build -d`; existing `.env` settings are preserved.

Manual verification:

1. Sign in, open Add application, paste a public Greenhouse, Lever, or Ashby posting, and select Auto-fill from link.
2. Confirm loading feedback, extraction source, editable values, and missing-field warnings. Check the count has not changed before saving.
3. Correct a field, add personal notes, and save; reopen the record to confirm the values and description persisted.
4. Import that same link with different tracking parameters and confirm a possible-duplicate warning. Cancel without saving.
5. Try a public generic page with JobPosting JSON-LD. Test a blocked/closed posting and confirm manual fields remain usable.
6. Try `http://127.0.0.1/` or `http://169.254.169.254/`: preview must reject it. Clear the link and complete a manual record.

## Follow-up reminders and deadlines

Open an application and select **Add reminder**. Enter a title and local due date/time. The reminder appears both on that application and in the dashboard's **Follow-ups & deadlines** section. Categories show counts and paginated lists:

- **Overdue**: incomplete and due before the current instant, including earlier today.
- **Due today**: incomplete and due from now until the next local midnight.
- **Upcoming**: incomplete and due tomorrow or later in the browser's IANA timezone.
- **Completed**: explicitly completed, regardless of due date. Complete and reopen preserve the original deadline.

Edit titles/deadlines, mark reminders complete, reopen them, or delete them with confirmation. Company/role links open the associated application. Application deletion cascades to its reminders. Reminder categories refresh every minute and when the window regains focus; no external notifications or background scheduler are implemented.

The existing reminder schema is reused without migrations or resets. All timestamps are timezone-aware instants, normalized to UTC on input and stored in PostgreSQL `timestamptz`. The browser converts the datetime-local input to UTC and displays deadlines in its current local timezone. Calendar boundaries use Python IANA `zoneinfo` data and account for 23/25-hour daylight-saving days. Nonexistent spring-forward local times are rejected; newly entered ambiguous fall-back times use the browser's earlier occurrence. Editing a title without changing the displayed time preserves the original UTC instant, including seconds and a previously saved later fall-back occurrence.

Authenticated endpoints (all ownership is checked through the associated application):

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/reminders` | Paginated list and category counts; optional `application_id`, `bucket`, IANA `timezone`, `page`, `page_size` (max 100) |
| POST | `/api/reminders` | Create with `application_id`, `title` (1–200 characters), timezone-aware `due_at` |
| GET | `/api/reminders/{id}` | Read owned reminder |
| PATCH | `/api/reminders/{id}` | Edit `title`/`due_at`, set `completed: true` or `false`; application reassignment is forbidden |
| DELETE | `/api/reminders/{id}` | Delete owned reminder |

List category counts cover the entire application/owner scope, not just the current page or selected category. Lists default to UTC if `timezone` is omitted; the UI always sends the browser timezone. Mutation/detail response categories use UTC; the UI reloads the localized list afterward. Missing/other-owner records return 404. Clients cannot supply `owner_id` or `completed_at`.

## Persistent login and security

This client-only React application uses [Supabase browser session persistence](https://supabase.com/docs/reference/javascript/auth), not custom password/token logic. Access and rotating refresh tokens are stored in **JavaScript-readable localStorage**. This enables refresh/reopen persistence but means a successful same-origin XSS attack can steal them. Use a trusted browser/device, avoid untrusted same-origin scripts, keep dependencies current, and serve over HTTPS when hosted. React renders notes/descriptions as text. An HttpOnly-cookie/BFF architecture would reduce token exposure, but is outside this focused change. Browser storage must be available for persistence; clearing site data or private browsing policies can remove the session. No service-role key belongs in the browser.

The app uses `getSession` to restore/refresh, [getUser](https://supabase.com/docs/reference/javascript/auth-getuser) to verify restored identity, and synchronous auth-event callbacks to update state without calling SDK methods inside the callback. Automatic refresh events update the active token; API requests read the current SDK token and may refresh/retry once after a 401. Rejected refresh tokens, invalid restored sessions, or a second 401 clear the local session and return to sign-in. Temporary network failures offer retry without deleting saved credentials. Focus rechecks session validity. Logout clears local state/storage even if offline; a storage-write fence prevents an in-flight refresh from restoring the logged-out session. Supabase sign-out events and browser storage changes handle logout across tabs.

[Supabase documents that access JWTs from revoked sessions remain valid until expiry](https://supabase.com/docs/guides/auth/signout). This backend deliberately preserves JWKS verification and does not perform a remote session lookup on every request. Remote revocation is therefore recognized when Supabase validation or token refresh rejects the session, rather than guaranteeing immediate access-token invalidation. Offline logout cannot confirm server-side revocation; the local session is still removed. Do not interpret a client session check as backend authorization.

Daily-use manual checks:

1. Sign in and refresh. Confirm the restoration message transitions to the workspace without re-entering credentials. Open another tab and verify logout clears both tabs; refresh again and confirm sign-in is required.
2. In an application, create one past reminder, one later today, and one tomorrow. Check dashboard category counts, company/role links, and local date/time display.
3. Edit a title/deadline, complete and reopen a reminder, cancel deletion, then confirm deletion. Refresh and confirm database persistence.
4. Test a narrow/mobile viewport and keyboard-only operation. Check empty categories and network-error retry states.
5. In Supabase, revoke the test session. Verify failed refresh returns to sign-in, allowing for the existing access JWT's expiry window. Temporarily disconnect networking to test restoration retry and local logout.
6. For daylight-saving behavior, test browser timezone overrides at spring-forward/fall-back boundaries; an impossible local time must show a validation error.

Gmail manual synchronization, classification, review, and guarded updates are implemented separately from Supabase login. Google configuration and real-mailbox validation are required before use; automatic updates remain off by default. See [GMAIL.md](../GMAIL.md) for setup, security, limitations, and the manual checklist. Supabase browser tokens are never used as Gmail credentials. Periodic scheduling remains future work.

## Gmail integration

The **Gmail integration** navigation item provides separate read-only Google OAuth connection/disconnection, resumable manual sync, a review queue, explicit accept/dismiss, update history/undo, and employer aliases. Automatic changes start disabled and require a reviewed recruiting-email dry run before enabling. Applications/reminders are preserved by additive migration `0002`; no database reset is needed.

[Full Google Cloud setup, new server-only variables, limits, retention, and real-account checklist](../GMAIL.md). Add new values to your existing `.env` yourself; do not replace it. The implementation has automated fixture coverage, but the owner reports successful OAuth connectivity; recruiting-message behavior still needs validation.
