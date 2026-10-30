# U-Connect backend

This is the first production-foundation stage: server-managed accounts and sessions, email-verification flow, school-scoped support requests, and server-side administrator permissions. No demo accounts or sample requests are created.

## Local setup (PowerShell)

Run these commands from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$env:UCONNECT_SECRET_KEY = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:UCONNECT_COOKIE_SECURE = "0"
.\.venv\Scripts\python.exe -m flask --app backend.app create-school
.\.venv\Scripts\python.exe -m flask --app backend.app create-admin
.\.venv\Scripts\python.exe .\backend\app.py
```

The local HTTP-only cookie setting is for development. Do not use it in production. The school command asks for a school name and a registration code; the administrator command privately prompts for an email and password. Administrator accounts are created only through this trusted command, not through public registration.

## Email verification

Registration creates an unverified account and sends a signed verification link through SMTP. Configure all of the following before enabling public registration:

- `UCONNECT_PUBLIC_BASE_URL`: the public HTTPS origin, for example `https://connect.example.org`
- `UCONNECT_SMTP_HOST` and, when needed, `UCONNECT_SMTP_PORT` (defaults to `587`)
- `UCONNECT_SMTP_USERNAME` and `UCONNECT_SMTP_PASSWORD` when the relay requires authentication
- `UCONNECT_SMTP_USE_SSL=1` for implicit TLS; otherwise STARTTLS is used
- `UCONNECT_EMAIL_FROM`: a sender address accepted by the relay

If delivery is not configured or fails, the API reports an explicit error and leaves the account unverified. It does not expose a verification token in the browser or logs.

## Production settings and persistence

Set `UCONNECT_SECRET_KEY` to a unique, randomly generated secret held in the deployment secret manager. Set `UCONNECT_COOKIE_SECURE=1`, terminate HTTPS at a trusted proxy, and restrict access to the database and backups. Never use Flask's development server as the production server.

`UCONNECT_DATABASE` selects the SQLite file; the default is `backend\instance\uconnect.sqlite3`. SQLite transactions persist account and request changes on disk and are appropriate for a single application instance on durable local storage. For multiple app instances, high write concurrency, or high availability, migrate to a managed database before launch. Back up the database and test restore procedures.

School IDs are attached to users and requests. Student request queries are scoped to the signed-in user and school; administrator queries and updates are scoped to that administrator's school. Role changes are not exposed through the web API. Requests are visible to administrators at the relevant school; this stage does not provide a confidential-request workflow, so the interface warns users not to submit sensitive details.

## Tests

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\backend -p "test_*.py" -v
node --check .\frontend\app.js
```

SMTP delivery is mocked in automated tests; configure and verify the actual relay separately before launch.

## Not included in this stage

No email provider credentials are included. Learning activity/Subjects Learn Hub, Trusted Adult, a complete Stay Safe workflow, teacher uploads and content moderation, subscription/payment processing, and production deployment validation still require product, safeguarding, provider, and hosting decisions. Do not launch for minors or collect sensitive safeguarding reports until age-appropriate consent, escalation, and privacy requirements have been reviewed. No test-mode payment is represented as a real transaction.
