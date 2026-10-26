# Gmail integration

ApplyTrack supports a separate Google authorization, manual resumable synchronization, deterministic email analysis, review suggestions, and guarded status updates. **Automatic updates are disabled by default.** No Gmail message is sent, modified, deleted, or marked read. There is no paid AI API, periodic scheduler, or queue service.

## Google Cloud setup

1. Create/select your Google Cloud project and enable **Gmail API**.
2. Configure the Google Auth Platform consent screen/audience. For personal development, use Testing and add your own Gmail account as a test user. Supply the requested app/contact information.
3. Add exactly `https://www.googleapis.com/auth/gmail.readonly` to the requested data access scopes. Do not add Gmail modify/send or broad mail access. Gmail authorization is independent from Supabase sign-in.
4. Create an OAuth client of type **Web application**. Register the exact redirect URI `http://localhost:8000/api/gmail/oauth/callback` for the default local stack. Use a separate client and an exact HTTPS callback when hosting later. A trailing slash or changing localhost to 127.0.0.1 changes the redirect URI.
5. Copy the client ID and secret into the **existing `.env` yourself**, adding the server variables below. Do not replace the file or its Supabase values. Generate and securely back up one encryption key; do not paste any of these secrets into chat or commit them.

Generate a Fernet encryption key locally:

```sh
backend/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Add these values to your existing `.env`:

```dotenv
GOOGLE_CLIENT_ID=<web-client-id>
GOOGLE_CLIENT_SECRET=<web-client-secret>
GMAIL_ENCRYPTION_KEY=<generated-fernet-key>
GMAIL_REDIRECT_URI=http://localhost:8000/api/gmail/oauth/callback
GMAIL_FRONTEND_URL=http://localhost:5173
```

All five variables are server configuration. **Never prefix secrets or encryption keys with `VITE_`.** Compose passes only the existing public Vite variables into the frontend container. No Gmail browser credentials are needed. `GMAIL_FRONTEND_URL` must match a configured `CORS_ORIGINS` origin. Missing or invalid credentials/key cause Gmail operations to fail closed; other ApplyTrack features keep working.

Restart/build without resetting data:

```sh
docker compose up --build -d backend frontend
```

The backend automatically applies additive migration `0002`. This creates four Gmail tables, adds status revision/timestamp guards to applications, and adds source metadata to application events. Existing application/reminder fields and records are retained. For host development, use the existing ignored `.env` symlink and run `alembic upgrade head` from backend as before.

Official guidance: [OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server), [Gmail scopes and verification](https://developers.google.com/workspace/gmail/api/auth/scopes), and [Gmail synchronization](https://developers.google.com/workspace/gmail/api/guides/sync). Google classifies `gmail.readonly` as a restricted scope; assess the verification/security-assessment requirements and applicable personal-use exceptions before public hosting. Testing-mode consent and token lifetimes are governed by Google; reconnect when access expires or is revoked.

## Connect and run a dry run

1. Sign in to ApplyTrack with Supabase. Open **Gmail integration** in the existing navigation.
2. Select **Connect Gmail**, choose your intended Gmail account, and consent to read-only access. Returning to ApplyTrack restores the Supabase session and opens the Gmail section. Cancellation or OAuth errors leave existing connections intact.
3. Set and save an initial lookback (1–365 days, default 30) before the first sync. Select **Sync Gmail now**. If the response has more work, select **Continue sync** until complete.
4. Review suggested classifications, candidate applications, sender/identity evidence, and the current application status. Rule strengths are not calibrated probabilities.
5. Accept a suggestion only after choosing the correct application/status and checking the explicit review box, or dismiss it. Search company/role to select applications beyond the first 100 search results. Optional per-application company aliases and employer domains help future messages; existing suggestions remain available for manual matching.
6. Leave automatic updates disabled until you have reviewed real messages. A completed sync with at least one retained recruiting-related message and an explicit review acknowledgment is required to enable automation. An empty/irrelevant scan does not unlock it.

No application is created from email. Unknown or ambiguous messages can be reviewed without inventing a match or status. Review approvals are deliberate manual corrections and can change a status that automation would protect. Approval uses the displayed status revision; a newer status edit returns a conflict and requires reloading/reviewing again.

## What can update automatically

An update requires all of the following:

- Explicit, nonconditional current-message language for confirmation, assessment, interview, rejection, or job offer.
- A unique strong application identity: exact external job ID or canonical application URL **plus** explicit company/alias and job title. A unique exact identifier may disambiguate identical titles; multiple matching identifiers/candidates remain for review.
- Gmail-added `Authentication-Results` reporting DKIM pass for the sender identity, plus an employer domain/rule or a recognized ATS sender domain. A sender's display name, shared domain, or company mention alone is insufficient. Free-mail and job-marketplace domains are not inferred as employer identities.
- A message received after automation was enabled and not implausibly future-dated.
- No newer manual correction or source status event, no Offer/Rejected/Withdrawn terminal status, and no backward progression or same-status change.

A job offer needs explicit offer language; the word “offer” in benefits, advertisements, a conditional sentence, signature, or quoted/forwarded thread is insufficient. The classifier strips common signatures, plain-text quotes, wrapped reply headers, HTML blockquotes/Gmail quote blocks, and ignores attachments. Conflicting/conditional/negated statements remain uncertain. Rules currently target English messages; unusual templates, encoded content, and other languages often require review.

An interview invitation changes at most the **Interview status**. It never asserts that a time was accepted, creates an interview date, or schedules a reminder.

Each applied change records an application event with old/new statuses, Gmail message ID, source timestamp, processing timestamp, and a non-content reason. Source timestamps govern automatic ordering; manual status selections (even selecting the same status) increment a revision and protect against older email changes. Accepting/undoing a suggestion counts as a manual correction.

**Undo change** retains the original event and appends a reversal. Undo is blocked after any newer status revision, so it cannot silently overwrite another manual/automatic change. Use the normal application editor when deliberate reconciliation is necessary.

## Synchronization and limits

Initial search is a bounded recruiting-keyword query within the lookback window. It does not list the whole mailbox. The mailbox profile's history ID is captured before the search so later incremental sync can recover arrivals during initial paging. Subsequent sync uses `history.list` with message-added history. Only newly added messages are fetched; known IDs are skipped. This may inspect new non-recruiting mail to determine relevance, but it does not rescan the whole mailbox on every sync.

History/page cursors, pending IDs, statistics, and the last fully successful sync are persisted. Each manual request processes at most 25 message IDs and has a 35-HTTP-request / approximately 45-second Google-network budget. Gmail responses are limited to 4 MiB; useful body text is limited to 32,000 characters and MIME traversal to 100 parts. Attachments are never downloaded separately. Large/malformed messages are ignored or leave a resumable safe error; no speculative status is applied. Rate limits/transient 5xx responses receive bounded backoff (up to two retries); partial checkpoints keep completed work and resume remaining IDs. Concurrent sync/disconnect/settings operations use a per-connection database lock rather than an external queue.

Expired history IDs (404) or expired pagination tokens trigger a fresh **bounded lookback recovery**, with a visible warning. Already recorded message IDs prevent repeated status events. Mail older than that configured window is not recovered automatically. Lookback changes affect the next initial/recovery scan, not a normal incremental sync. Last successful sync advances only after all pages/pending IDs complete. Counts shown are for the current/last sync cycle, including partial progress.

## Data, disconnect, and privacy

Only message IDs, limited metadata, a maximum 500-character current-message excerpt, classification/match evidence, and action state are retained. Full MIME bodies and access tokens are not persisted. Irrelevant/excluded/malformed messages retain only an ID/timestamp tombstone for deduplication. Email subject/sender/excerpt fields older than 90 days are redacted on sync; there is no independent retention scheduler yet. IDs, outcomes, and application audit events remain until explicitly purged where applicable.

Refresh tokens and PKCE verifiers are Fernet-encrypted with owner-bound payloads under the server-only key. Losing/changing that key makes existing credentials unreadable; restore it from a separate secure backup or disconnect/delete and reconnect. Key rotation/re-encryption is a future operational procedure. Database/application access must still be protected; encryption does not replace access control.

OAuth uses a single-use hashed random state, a ten-minute HttpOnly SameSite=Lax browser-binding cookie, PKCE S256, offline consent, and fixed configured redirects. The callback is the sole Gmail route without a Supabase bearer token; it authenticates the pending link through state plus that browser cookie. It never returns authorization codes or OAuth tokens to the frontend. Code exchange and refresh use HTTPS POST bodies. Google requests are fixed-host, refuse redirects, ignore ambient proxies, and do not forward Supabase credentials.

The application removes callback query strings before Uvicorn access logging and sets no-store/no-referrer response headers. **Any reverse proxy, load balancer, or tracing service must separately suppress/redact OAuth callback query strings and request/response bodies**; do not enable sensitive HTTP/body/SQL parameter logging. Existing SQLAlchemy parameter hiding is preserved.

Disconnect always removes local tokens and pending OAuth state, attempts Google token revocation, and disables automation. The confirmation defaults to deleting retained Gmail message/rule/sync data. You may retain local review history instead, but you must purge the previous connection before linking a different Gmail account. Applied application statuses and audit events are intentionally preserved; disconnect does not revert them. Offline/unavailable revocation cannot be guaranteed: remove access through your Google account's connected-app controls if necessary.

For deployment, use HTTPS and a same-site frontend/backend or an appropriate same-origin reverse proxy. Browsers can block the OAuth binding cookie when it is set through cross-site API fetches. The local localhost ports are same-site. Do not mix localhost/127.0.0.1 origins during setup. Supabase browser persistence/XSS considerations remain documented in README.md.

## Real Gmail manual verification

Automated tests use synthetic data and mocked Google transport. **The owner reports a successful real OAuth connection and an initial sync of 12 messages with zero matches or updates. This verifies connectivity only; real recruiting-message classification, matching, consent/revocation, and pagination behavior still require validation.**

1. Configure a Google test user/client, server secrets/key, and exact redirects. Keep automation disabled.
2. Connect, cancel one consent attempt, reconnect, refresh ApplyTrack, and verify the intended mailbox and Supabase session remain separate.
3. Create existing tracked applications matching real messages, including multiple roles at one employer. Run a narrow dry run and continue all batches. Compare subjects, classifications, matches, and abstentions against Gmail manually.
4. Verify explicit confirmations, assessments, interview invites, rejections, offers, conditional/negative wording, signatures, quotes, and forwarded messages. Confirm an invitation never creates a calendar date/reminder.
5. Repeat sync and check no duplicate suggestions/events. Have a new recruiting message arrive, sync incrementally, and verify only new IDs are processed. Test rate-limit/retry behavior with automated fixtures rather than flooding Gmail.
6. Accept/dismiss suggestions, correct a status manually, and test stale approval/undo conflicts. Undo one untouched change and inspect both audit events.
7. Only after inspecting real dry-run results, acknowledge review and enable automation. Verify a newly received strongly identified message can update, while a generic/ambiguous/unsigned or stale one cannot. Keep a same-company ambiguous case for review. Disable automation again if results are unsuitable.
8. Revoke access in Google, then sync and check reconnect-required state. Disconnect with deletion, verify retained excerpts/credentials disappear, and confirm applications, reminders, and audit history remain intact.
9. Check mobile width, keyboard navigation, loading/error/empty states, and logout. Never paste real message bodies or tokens into bug reports; use redacted fixtures.

## Tests and production readiness

Run from the repository root after migrating the disposable test database:

```sh
cd backend
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/python -m pytest tests/test_gmail.py -k precision_report -s -q
DATABASE_URL=postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack_test .venv/bin/alembic check
cd ..
TZ=America/Detroit npm test --prefix frontend
npm run build --prefix frontend
```

Fixture precision is reported with sample counts; these small curated examples are regression checks, **not a real-world accuracy estimate**. Before production: complete real mailbox validation, review restricted-scope requirements, protect/rotate/back up secrets, configure HTTPS/same-site routing and log redaction, establish DB backups/retention operations, and validate any host request-timeout limits against manual sync budgets. A future periodic scheduler can reuse the owner-scoped synchronization checkpoints/locking; it is deliberately not implemented in this phase.
