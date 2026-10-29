# U-CONNECT deployment and operations

## What this release changes

U-CONNECT now requires a server session for student profiles, learning progress, timetables, exams, reports, and school content. Student registration is school-code scoped and requires email verification. Administrator accounts are provisioned through a private Flask CLI prompt; public registration cannot choose a privileged role. Mutating API calls require a session CSRF token. User-specific API responses are not cacheable, and the service worker caches only the static app shell.

Existing SQLite records without an account and school association are retained but are not exposed through authenticated student or school queries. Review and migrate legitimate legacy data under an approved school/account mapping before exposing it.

## Render configuration

The included `render.yaml` configures Gunicorn, a generated `UCONNECT_SECRET_KEY`, secure cookies, a public verification URL, and SMTP settings as secrets to be entered in Render. Set these SMTP environment variables in the Render dashboard before enabling registration:

- `UCONNECT_SMTP_HOST`
- `UCONNECT_SMTP_USERNAME` and `UCONNECT_SMTP_PASSWORD` when required
- `UCONNECT_EMAIL_FROM` to a sender accepted by your mail provider
- Optionally `UCONNECT_SMTP_PORT` (default `587`) and `UCONNECT_SMTP_USE_SSL=1` for implicit TLS

Registration returns an explicit error and leaves accounts unverified if email is unavailable. Test delivery and expiry using the actual provider before launch. The verification token is never returned by the public API.

Create each school and its first administrator from a trusted deployment shell:

```powershell
python -m flask --app backend.app create-school
python -m flask --app backend.app create-admin
```

The school code is a registration selector, not an administrator credential. Distribute it only to the intended school community. Administrator passwords are entered through a hidden terminal prompt. Never expose a web endpoint for creating or promoting administrators.

## Persistence and availability

The default SQLite database is `database\unconnect.db`. Render's free web-service filesystem is ephemeral; **do not use the free plan for real accounts or student records**. Before production, configure durable persistent storage supported by the selected plan, point `UCONNECT_DATABASE` at that mount, and verify backups and restore. For multiple instances or higher write volume, migrate to a managed relational database and run migrations as a deployment step.

Set `UCONNECT_COOKIE_SECURE=1`, serve only over HTTPS, keep the generated secret private, restrict database and backup access, and use a production WSGI server (the Render command uses Gunicorn). Do not enable Flask debug mode in production.

## Local development and tests

From the repository root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$env:UCONNECT_SECRET_KEY = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
$env:UCONNECT_COOKIE_SECURE = "0"
python -m flask --app backend.app create-school
python -m flask --app backend.app create-admin
python -m flask --app backend.app run
```

For automated checks:

```powershell
python -m unittest discover -s .\backend -p "test_*.py" -v
node --check .\frontend\auth.js
node --check .\frontend\learn.js
node --check .\frontend\service-worker.js
```

## Safety and launch limitations

The Stay Safe page contains emergency guidance, but U-CONNECT does not dispatch alerts or share a user's location. This is stated in the interface; users must contact local emergency services or a trusted adult directly. Reports are visible to administrators at the reporting school. The current app is not an anonymous or confidential counselling channel and must not be presented as one.

This release does not provide a complete safeguarding/escalation process, payment processing, Trusted Adult workflow, teacher upload workflow beyond administrator-managed paper links, or age/guardian consent handling. Do not launch to minors or collect sensitive safeguarding reports until qualified safeguarding, privacy, and legal owners approve those workflows. No payment test mode is represented as a real transaction.

Production launch still requires SMTP configuration and verification, durable storage and restore testing, school/admin provisioning, dependency/security review, and a deployment smoke test on the actual Render service.
