> Current publication follow-up: the authenticated GitHub account is now `vaap1375`, has write access to the intended repository, and remote `main` matches the previously reviewed local commit. The owner has deployed the private application. Historical access/deployment blockers below describe the earlier readiness pass; current scan results are recorded in VERIFICATION.md. Credential rotation is not automatically performed or assumed.

# Security and publication review

Review date: 2026-10-26. This is a source/configuration review plus automated regression and dependency checks, not an independent penetration test or a claim that no vulnerabilities exist.

## Publication boundary

The workspace initially had no Git repository or history. The intended public remote is `https://github.com/vaap1375/applytrack`. For the final publication pass, authenticated account `vaap1375` has write permission and remote `main` was verified to match the reviewed local initial commit. No history overwrite or force push is used. Both `.env` and `.env.production` remain ignored and untracked; current scan results are in VERIFICATION.md.

Only reviewed source, synthetic fixtures, lockfiles, and documentation belong in the initial commit. `.env`, caches, virtual environments, node_modules, compiled output, database dumps, private keys, OAuth credential/token JSON patterns, backups, and local tooling directories are excluded by `.gitignore`. The root Docker context independently excludes private configuration and generated files. Docker named volumes are outside the source tree and are not publication material. No screenshots or mailbox export are included.

Gitleaks **8.30.1**, downloaded from its official release and verified against the published SHA-256 checksum, reported **zero findings** on a temporary copy of the publication candidate. A separate literal comparison against private secret/encryption/password/token values from the local `.env` found **zero matches** in candidate files and the compiled frontend. Values were never printed. A final staged-tree/history scan is required immediately before publication; future changes must be rescanned. A clean scanner result does not detect every possible personal record, so fixtures and file manifests were also reviewed.

`.env.example` contains placeholders and disposable local database defaults, not hosted credentials. Frontend Supabase publishable keys are public by design; service-role keys, Google secrets, and the Fernet encryption key are server-only. The production image was built with synthetic public configuration, ran as UID 10001, and contained no `/app/.env`. Docker warns about the `VITE_SUPABASE_PUBLISHABLE_KEY` build argument based on its name; it is intentionally public, not a private credential.

## Authentication and personal data

All protected API operations require server-verified owner identity. A regression test enumerates the documented API operations and checks unauthenticated rejection. Supabase JWT verification requires asymmetric ES256/RS256, issuer, audience, expiry, subject, and the configured owner. There is no production bypass. Every application's children/reminders/Gmail review operation scopes through the owner.

The sole `/api` exception is the Google callback: it uses one-time expiring hashed state, an independent browser-binding HttpOnly SameSite=Lax cookie, PKCE, and owner-bound encrypted pending verifier. HTTPS configuration sets the cookie Secure. Refresh tokens stay encrypted server-side and are never returned to React. The callback redirects only to the configured frontend result fragment. Production disables request access logs, and the callback additionally redacts query strings before access logging. Configure provider/edge logs separately; do not export OAuth callback URLs or mailbox excerpts.

Supabase uses supported browser localStorage persistence and automatic refresh. Browser-readable tokens remain vulnerable to successful same-origin XSS. Production CSP, plain text rendering, no remote HTML injection, no-store responses, and no-referrer reduce exposure; they do not make localStorage secret from scripts. Local logout clears the session; offline logout cannot guarantee remote revocation. A previously issued JWT can remain valid until expiry after remote revocation.

Gmail reads only `gmail.readonly`; it cannot send, modify, or delete messages. Only limited excerpts and matching evidence are retained, with content redaction after 90 days on a later sync. Deduplication identifiers/audit records remain until purge. Database backups and logs need their own access/retention controls. No continuous sync or retention worker exists.

## External requests and automatic changes

Public URL fetching validates all DNS results, rejects non-public and mapped/tunneled addresses, pins the actual socket to a validated IP with original TLS hostname verification, and revalidates every redirect. It allows standard public HTTP/HTTPS ports, rejects credentials and unsafe syntax, bounds DNS workers, limits redirects to 3 and response bodies to 2 MiB, and applies a 15-second total deadline. No credential/proxy forwarding, CAPTCHA bypass, LLM, or authenticated scraping is introduced.

Gmail uses fixed Google endpoints, bounded API budgets/retries, checkpoints, unique message IDs, row locks, source timestamps, and status revisions. Automatic changes default off and require reviewed dry-run evidence before opt-in. Ambiguity, stale source mail, newer manual changes, terminal statuses, unsigned/untrusted senders, and unsafe transitions block automation. Review approval is explicit and undo is audited with revision guards. These controls are covered by synthetic tests; real-message accuracy remains unestablished.

## Production configuration and dependencies

Production requires an HTTPS origin, exact same-origin CORS, a configured owner, HTTPS Supabase, and TLS-required PostgreSQL URLs. Gmail redirects must match the production origin when configured. Trusted hosts, CSP, HSTS on HTTPS, no-sniff, and no-frame headers are enabled. Unknown API routes and hidden paths cannot fall through to React. Forwarded headers are accepted only from configured proxies; wildcard trust is appropriate only behind restricted trusted platform ingress.

Database pooling is bounded; migrations use an optional direct URL and execute explicitly, one operator at a time. Existing migrations are preserved. No schema reset or personal record mutation occurred during this task; read-only fingerprints across all existing public tables matched before and after local service rebuilds.

`npm audit` (all dependencies and production-only) reported zero vulnerabilities. `pip-audit` initially identified CVE-2025-71176 / GHSA-6w46-j5rx-g56g in pytest 8.4.2 (duplicate advisory entries for one issue). Pytest was upgraded to 9.0.3; the final pinned-dependency audit reported zero known vulnerabilities. This was a test-tool local temporary-directory issue, not evidence of a remotely exploitable ApplyTrack endpoint. CI uses synthetic service credentials and read-only repository permissions; production secrets are not required to run tests or image checks.

## Outstanding release requirements

1. **Rotate the Google OAuth client secret previously exposed in a screenshot before production.** No automatic rotation was performed. Preserve and separately back up the existing encryption key.
2. Recheck remote refs and scan the exact staged content before each publication; writer access is now available.
3. The owner has deployed Render and verified core production flows; Neon initialization reached revision 0002 in the preceding session. Provider logs, backup/restore operations, browser refresh/revocation, and broader production checks still need deliberate ongoing review.
4. Validate actual recruiting emails with automation off. The owner-reported 12-message sync with zero matches establishes connectivity only.
5. Run the browser/mobile/accessibility checklist and capture only sanitized genuine screenshots. No browser was connected during this audit.
