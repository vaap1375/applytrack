# Actual application screenshot checklist

No browser connection was available during this verification; no screenshots or browser E2E results are claimed.

1. Use an isolated demo database and demo owner. Do not replace the personal `.env` or reset the personal database. Label records **DEMO — Example Company / Software Engineer**.
2. Capture desktop overview with reminder categories, application list/filter, and application detail/history. Show job URL preview from a public posting if it contains no personal information.
3. Capture Gmail disconnected/settings or an empty review queue. Do not show an actual email address, message subject/body, mailbox IDs, or OAuth browser address bar.
4. Capture a narrow mobile viewport showing navigation and an application/reminder form. Verify keyboard focus, labels, dialog dismissal, loading/error states, and readable contrast.
5. Review every image for browser profile/avatar, notifications, names, credentials, personal records, and address-bar query strings. Store only reviewed images under `docs/screenshots/` and link them from README.

Manual E2E: sign in → refresh → add/edit/import/save application → create/complete/reopen reminder → inspect history → log out in one tab and verify the second tab logs out. Reconnect Gmail only after credential rotation; keep automatic updates off, sync a narrow range, and inspect every proposed match before approval. Verify approval, undo, and preservation of a newer manual status using disposable demo records.
