# U-Connect deployment

## Render setup

The repository includes a Render web-service definition in `render.yaml`. Connect
the GitHub repository to Render and deploy the feature branch only after reviewing
and merging it into the deployment branch.

The service uses:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT "backend.app:create_app()"`
- Python 3.11

Configure these secrets and environment variables in Render before enabling
registration:

- `UCONNECT_SECRET_KEY`: a unique, randomly generated secret stored in Render's
  environment settings.
- `UCONNECT_COOKIE_SECURE=1`
- `UCONNECT_PUBLIC_BASE_URL`: the app's public HTTPS origin.
- `UCONNECT_SMTP_HOST` and `UCONNECT_EMAIL_FROM`, plus the SMTP port, credentials,
  and TLS settings required by the email provider.

The app stores SQLite data at `backend/instance/uconnect.sqlite3` by default.
Render's local filesystem is not persistent across all service changes; configure
a persistent disk and set `UCONNECT_DATABASE` to a database file on that disk
before accepting real registrations or support requests. Back up the database
and test restoring it.

## Initial setup

From the repository root, create a school and an administrator using the Flask
CLI after setting the production environment variables:

```powershell
python -m flask --app backend.app create-school
python -m flask --app backend.app create-admin
```

The commands prompt for setup details. Do not create administrator accounts
through public registration.

## Verification

Check `https://<your-domain>/api/health` after deployment. Confirm that email
verification works with the configured SMTP provider before enabling public
registration. Run the backend tests and frontend syntax check from the repository
root before publishing changes:

```powershell
python -m unittest discover -s .\backend -p "test_*.py" -v
node --check .\frontend\app.js
```

Do not use the service for emergencies. Complete an age-appropriate privacy and
safeguarding review before launching to minors or accepting sensitive reports.
