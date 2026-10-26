# ApplyTrack

A private job application workspace that turns public job links and recruiting emails into editable tracking information, follow-ups, and an auditable application timeline.

Job hunting scatters context across job boards, spreadsheets, and an inbox. ApplyTrack keeps that context together while leaving the owner in control of what gets saved or changed.

## What works today

- **Applications:** CRUD, seven statuses, notes, dates, search, filters, pagination, and timestamped history.
- **Paste a job link:** preview Greenhouse, Lever, Ashby, or generic structured metadata; edit extracted fields and review duplicate warnings before explicitly saving.
- **Follow-ups:** application-linked reminders, overdue/today/upcoming views, completion and reopening, UTC storage with local display.
- **Private access:** persistent Supabase sessions, refresh and logout handling, server-verified asymmetric JWTs, and owner-scoped queries.
- **Gmail:** read-only OAuth, encrypted refresh tokens, manual incremental sync, deterministic classification and matching, approval/dismissal, guarded opt-in status changes, and audited undo.

Gmail sync runs when requested; there is no continuous inbox monitor. Automatic changes default to off. The owner reports a successful real OAuth connection and a first sync of 12 messages with zero matches or updates. That demonstrates connectivity, not classification accuracy.

## Architecture

```mermaid
flowchart LR
    Browser[React + TypeScript] -->|Same-origin API / Bearer JWT| App[FastAPI + compiled React]
    Browser -->|Sign-in / session refresh| Auth[Supabase Auth]
    App -->|Verify JWT using JWKS| Auth
    App -->|SQLAlchemy / TLS| DB[(PostgreSQL / Neon)]
    App -->|Validated public requests| Jobs[Job posting APIs / metadata]
    App -->|Read-only OAuth / manual sync| Gmail[Gmail API]
    GitHub[GitHub Actions] -->|Tests + production image build| App
```

React, TypeScript, Vite, Tailwind CSS, FastAPI, Python, SQLAlchemy, Alembic, PostgreSQL, Supabase Auth, Docker, and GitHub Actions. The prepared hosting model is one Render Docker web service with Neon; no cloud infrastructure has been deployed by this task.

### Engineering highlights

- SSRF defenses validate every resolved address and redirect, pin connections to approved IPs, retain TLS hostname verification, and bound time, redirects, and response size.
- Gmail uses state, a browser-bound HttpOnly cookie, PKCE, owner-bound encrypted refresh tokens, checkpointed sync, deduplication, row locks, status revisions, and stale/manual/terminal-status guards.
- Unknown or ambiguous email matches remain reviewable. External descriptions and email excerpts render as text; no LLM or remote HTML execution is used.
- Additive migrations preserve existing records. Production uses a non-root container, same-origin API routing, TLS-required database configuration, and explicit proxy trust.

## Run locally

Requires Docker Compose, Node 22, and Python 3.12 for host-side checks.

```sh
# New checkout only. If .env already exists, preserve it.
cp -n .env.example .env
# Configure Supabase and OWNER_ID locally; never commit .env.
docker compose up --build -d
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs in development. The local database persists in the Compose named volume. Never run `docker compose down -v` against data you need.

Create the owner manually in Supabase; disable public signup and enable an asymmetric ES256 or RS256 signing key. Set `OWNER_ID` to that user's UUID. Only the public Supabase URL and publishable key belong in frontend configuration. See [local setup and manual feature checks](docs/LOCAL_SETUP.md) for detailed setup and test commands.

### Environment configuration

[`.env.example`](.env.example) contains placeholders and disposable local database defaults.

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL`, optional `MIGRATION_DATABASE_URL` | Runtime database and optional direct migration connection; production requires TLS |
| `SUPABASE_URL`, `OWNER_ID` | JWT issuer and sole authorized owner |
| `CORS_ORIGINS` | Explicit allowed origin; production equals `APP_ORIGIN` |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Public frontend values embedded during build |
| `VITE_API_URL` | Local override; production image builds with same-origin API requests |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Server-only Google Web OAuth credentials |
| `GMAIL_ENCRYPTION_KEY` | Server-only Fernet key; preserve it to decrypt existing tokens |
| `GMAIL_REDIRECT_URI`, `GMAIL_FRONTEND_URL` | Exact OAuth callback and workspace origin |
| `APP_ENV`, `APP_ORIGIN`, `STATIC_DIR`, `FORWARDED_ALLOW_IPS`, `PORT` | Production validation, static hosting, trusted proxies, and dynamic server port |

Gmail is optional. Follow [Gmail setup, safeguards, and validation](GMAIL.md). Never add a private value to a `VITE_` variable: frontend variables are public.

## Verification

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt
# Create a separate disposable applytrack_test database first; see local setup.
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest -q
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic check
cd ../frontend
npm ci
npm test
npm run build
```

See [verification evidence](VERIFICATION.md) for actual results, limitations, and production container checks. Tests use synthetic fixtures and mocked Google/Supabase transports; fixture results are not real-world accuracy estimates.

## Deployment and security

[Production deployment guide](docs/DEPLOYMENT.md) covers Render, Neon, migrations, backups, Supabase, Google redirects, free-tier limits, and rollback. [Security review](docs/SECURITY.md) records publication checks and remaining requirements.

**Before production, rotate the Google OAuth client secret previously exposed in a screenshot.** Keep the existing encryption key secure and stable. Neither credential rotation nor deployment has been performed here.

Browser sessions use Supabase-supported localStorage persistence. Successful same-origin XSS can read browser tokens; CSP and text rendering reduce risk but do not eliminate it. Backend JWT checks remain mandatory. Revoked sessions can retain access until a previously issued JWT expires.

## Screenshots

No sanitized browser screenshots were captured automatically because no browser was connected. Use the [short screenshot checklist](docs/SCREENSHOTS.md) to capture the actual application with clearly labeled demo data before adding images here. Do not publish personal records or inbox content.

## Limits and roadmap

URL preview supports public, server-readable postings; authenticated pages, CAPTCHAs, JavaScript-only pages, and changed platform templates may require manual entry. Gmail classification is deterministic and English-focused; generic or ambiguous messages need review. In-app reminders do not send notifications. Free hosting sleeps and has usage limits. Real browser/mobile and real recruiting-email validation remain manual release checks.

Future work: review real-message outcomes, add a secure hosted scheduler when justified, and consider external reminder notifications. No scheduled Gmail sync or production accuracy claim is made.

[Resume notes](RESUME_NOTES.md) distinguish implemented, tested, and planned work.
