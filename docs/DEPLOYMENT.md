# Production handoff: Render + Neon

The owner has deployed [ApplyTrack on Render](https://applytrack-6mts.onrender.com) and verified production login, dashboard, application creation, reminders, and Gmail OAuth. Neon was initialized to `0002 (head)` in the preceding migration session. The instructions below remain a reproducible deployment/recovery reference; production Gmail sync is not separately confirmed.

This remains a private, single-owner application even though its source repository is public. Do not enable public signup or Gmail automation as part of deployment.

## 1. Credentials and data first

Rotate the previously screenshot-exposed Google OAuth client secret in Google Cloud before production. Update the secret securely in the existing local configuration and Render dashboard yourself; never paste it into chat. Reconnect Gmail if required. Do **not** change `GMAIL_ENCRYPTION_KEY` casually: existing owner-bound ciphertext needs the same key and owner UUID. Keep a separate encrypted backup of the key. Changing keys requires an explicit re-encryption process or disconnect/reconnect, not a database reset.

Back up the existing PostgreSQL data before migrating hosts. Creating Neon starts an empty database; existing records do not move automatically. Keep local Docker volumes intact. Do not include dumps, actual `.env` files, logs, or inbox screenshots in Git.

## 2. Create a free Neon database manually

Choose a nearby region and obtain a PostgreSQL connection string from Neon's Connect panel. Use the pooled endpoint for runtime and the direct endpoint for migrations/backup/restore. Keep `sslmode=require` or stricter; retain provider connection parameters such as `channel_binding=require`. Plain `postgresql://`, `postgres://`, and explicit `postgresql+psycopg://` are accepted and normalized to psycopg.

Use a least-privilege runtime role if practical; migration credentials need DDL privileges. Runtime pool: 2 persistent connections, up to 3 overflow, 10-second wait/connect timeout, pre-ping, 300-second recycle. One ASGI worker keeps personal-use resource demand modest. Use separate databases/projects for tests and production.

To transfer existing records: take an encrypted custom-format `pg_dump` with a PostgreSQL client compatible with the source server, restore into the **new empty** database using `pg_restore --no-owner --no-privileges`, then run additive Alembic upgrades. Review source/target carefully; do not use `--clean`, `--create`, or overwrite populated production data. Restore includes encrypted Gmail tokens and limited retained excerpts, so treat backups as private. Preserve OWNER_ID and the original encryption key. Test restore in an isolated database first.

## 3. Prepare the Render service

Manually create a **Web Service**, select the intended GitHub repository and `main`, choose **Docker** with root `Dockerfile`, and explicitly choose a free plan if available. Do not create a Render database, paid disk, worker, cron job, or domain automatically. Keep automatic deployment disabled while setting up secrets and migrations.

The image compiles React and serves it through FastAPI. Set the two public `VITE_SUPABASE_*` variables as Render Docker build arguments/environment build inputs before building; changing them requires rebuilding. The Dockerfile exposes only those public build arguments and forces `VITE_API_URL` empty. Server secrets must never be Docker build arguments.

Use the assigned HTTPS URL below as `<origin>` (no trailing slash). Set runtime variables securely:

| Variable | Production value |
| --- | --- |
| `APP_ENV` | `production` |
| `APP_ORIGIN` | `https://<service>.onrender.com` |
| `CORS_ORIGINS` | Exactly the same origin |
| `DATABASE_URL` | Neon pooled PostgreSQL URL requiring TLS |
| `MIGRATION_DATABASE_URL` | Neon direct PostgreSQL URL requiring TLS |
| `SUPABASE_URL` | Existing HTTPS Supabase project URL |
| `OWNER_ID` | Existing owner UUID |
| `VITE_SUPABASE_URL` | Same public Supabase URL; build-time |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Public publishable key; build-time |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Existing Web client ID and rotated secret; server only |
| `GMAIL_ENCRYPTION_KEY` | Existing stable Fernet key; server only |
| `GMAIL_REDIRECT_URI` | `<origin>/api/gmail/oauth/callback` |
| `GMAIL_FRONTEND_URL` | `<origin>` |
| `FORWARDED_ALLOW_IPS` | `*` **only** when all ingress is behind Render's trusted proxy |
| `STATIC_DIR` | `/app/static` (already set by the image) |
| `PORT` | Use Render's supplied value; do not hardcode |

`FORWARDED_ALLOW_IPS` otherwise defaults to loopback; use actual trusted proxy addresses outside Render. Never expose this container directly to untrusted callers with wildcard forwarded-header trust. The production application rejects HTTP requests, checks the configured host, and uses the ASGI server's trusted proxy interpretation. Render terminates TLS. Public host/health checks must use the configured hostname.

Use `/health` as the Render liveness health check. `/ready` separately verifies a database connection and returns a sanitized 503 on failure; it does not inspect schema or contact Google/Supabase. Startup does not silently migrate or reset data. CMD runs `python -m app.serve`, binds `0.0.0.0:$PORT`, disables request access logs, and allows 60 seconds for graceful shutdown. Keep provider request limits in mind for bounded Gmail sync requests.

## 4. Migrate explicitly, then deploy

Render's pre-deploy command is a paid-service feature. Free-tier setup uses an explicit local migration step before deployment, not an unreviewed startup migration. No shell access or paid job is required.

Build locally with public build values supplied securely in your shell. Never put private values on a command line:

```sh
docker build --build-arg VITE_SUPABASE_URL --build-arg VITE_SUPABASE_PUBLISHABLE_KEY -t applytrack:release .
# .env.production is your private, ignored runtime file with the variables above.
# Do not overwrite your local .env. Use restrictive permissions (chmod 600).
docker run --rm --env-file .env.production applytrack:release alembic current
docker run --rm --env-file .env.production applytrack:release alembic upgrade head
docker run --rm --env-file .env.production applytrack:release alembic check
```

Run one migration operation at a time against the direct endpoint. Existing migrations `0001` and additive `0002` are preserved; no new database migration is needed by the hosting changes. Before later schema changes: backup, test on a restored database, review migration SQL, and keep the previous application version compatible during rollout. Deploy the exact reviewed commit manually after migrations pass. Enable automatic deployments later only if migrations remain explicitly coordinated.

Rollback application code to the previous known-good image/commit first. Do not blindly downgrade schema: `0002` downgrade removes Gmail tables/columns. Prefer a forward fix; restore a tested backup into a separate database if recovery is required, verify records, then deliberately switch the connection. Never run test fixtures or destructive reset commands against production.

## 5. Supabase and Google settings

Keep the existing Supabase project, owner UUID, and asymmetric signing keys. Disable public signup. In Supabase Auth URL Configuration, set Site URL to `<origin>` and allow only the exact redirect URLs actually used; email-link flows are not implemented here. The application currently uses password login, not a Supabase OAuth callback. Remove unused development redirect entries when appropriate; don't change local credentials to do this. Production frontend public values must point to this same project.

In Google Cloud, enable Gmail API and configure the existing Web OAuth client. Add the exact authorized redirect URI `<origin>/api/gmail/oauth/callback` without a trailing slash. Keep the localhost callback only if local development is still needed. The server performs authorization-code exchange; no browser Google secret is used. Consent requests only `https://www.googleapis.com/auth/gmail.readonly`.

External OAuth apps in **Testing** normally receive seven-day refresh tokens for Gmail scopes; reconnect is expected after expiration. `gmail.readonly` is a restricted scope. Personal-use exceptions and public-distribution verification requirements differ; publishing the GitHub source does not verify the Google app. Follow Google's current requirements before expanding beyond the private owner; server-side storage/transmission of restricted data can require a security assessment for verified public distribution. Do not promise permanent token validity or bypass the consent warning. [Google token expiration](https://developers.google.com/identity/protocols/oauth2/#expiration), [restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).

The callback requires an expiring one-time state and a browser binding cookie, uses PKCE, returns only a fixed result fragment, and never returns a refresh token to React. Production callback cookies are Secure, HttpOnly, SameSite=Lax. Avoid cross-site frontend/API hosting. App callback access logs redact query strings; production disables request access logging altogether. Check platform/edge log retention and query redaction separately; never copy callback URLs into tickets.

## 6. Release smoke checks

- `/health` and `/ready` return 200; `/` and refreshed frontend paths return the compiled app; unknown `/api/*`, missing assets, and `/.env` return errors.
- Unsigned API access returns 401. A valid other-user token returns 403; the owner can perform CRUD/history/reminders/import. Never bypass authentication to test live data.
- Sign in, refresh, exercise session refresh, log out in two tabs, then refresh again. Inspect the browser console for CSP/network failures without exporting tokens.
- Test one public URL from each provider; correct extracted values before saving. Verify manual fallback.
- Verify reminder local timezone/date boundaries and completion/reopening. Check desktop, keyboard-only, and mobile layouts using demo records.
- After rotation, connect Gmail, leave automatic changes **off**, sync a narrow range, and inspect all real recruiting-message matches/abstentions. Zero matches is not accuracy validation. Review approvals and undo on disposable cases.
- Restart/redeploy the web service and confirm records remain in Neon. This does not restart or reset the database.

## 7. Operations and cost limits

Check Render logs for startup/errors and the dashboard for resource usage; request access logs are disabled to reduce personal-data exposure. `/ready` provides a minimal database failure signal, not full monitoring. Do not log request bodies, authorization headers, tokens, or email content. Review provider-level log redaction, retention, and access separately.

Store encrypted off-provider PostgreSQL backups on an owner-controlled schedule, and practice restoring them. Neon instant restore is a short recovery window, not an independent backup. Back up the Gmail encryption key separately from database dumps. Gmail excerpts are redacted after 90 days on a subsequent sync; that is not a scheduled retention worker. Backups may retain old content and need their own retention policy.

Render free web services sleep after 15 idle minutes, have cold starts, ephemeral disks, and monthly usage limits. They cannot run an always-on background sync loop; no hosted scheduler is provisioned. Neon free databases scale to zero and have storage/compute/transfer/restore limits. As checked on 2026-10-26, Neon's current announcement lists 1 GB storage and 100 CU-hours per project/month; the free restore window is six hours, also capped by history size. Plans can change—confirm the dashboard before accepting any upgrade. No paid service has been activated here.

Sources: [Render free limits](https://render.com/docs/free), [Render deployment commands](https://render.com/docs/deploys), [Render port binding](https://render.com/docs/web-services#port-binding), [Neon current free-plan announcement](https://neon.com/blog/neon-free-plan-1-gb-per-project), [Neon restore window](https://neon.com/docs/postgres/backup-restore/history-window).

Future scheduler: reuse the existing owner-scoped sync service, checkpoints, deduplication, row locks, and bounded retries. An external authenticated invocation path and hosted scheduler still need design/testing. Do not expose an unauthenticated sync endpoint or enable automatic status changes to accommodate scheduling.
