# Install Hadar IT

From an empty folder to a running Hadar IT, in one guide. You do not need to visit the frontend and backend repositories: the commands below fetch both.

> **Alpha. For evaluation, not production.** This walkthrough creates a private local installation with fictional inventory. Use no real business data or reused passwords.

## Before you start

You need **Git**, **Bash**, **curl**, and **Docker with a recent Compose plugin** supporting `!override` (Compose 2.24.4 or later). Docker must be running and your account must be allowed to use it. You do **not** need Python, Node.js, PostgreSQL or an AI provider on the host.

The repositories are currently **private**. Your GitHub account needs access to all three, and Git must already be authenticated through your normal credential manager or GitHub CLI. Never paste a token into a clone URL.

On SELinux hosts, ask the host operator for an unused MCS level for this installation, such as `s0:c500,c501`. The value is an allocation, not a universal default; keep it for later commands. Compose requires it even on hosts without SELinux.

## 1. Get the complete application

Run these commands in order, in a new working directory. Stop if any command fails.

```bash
git --version
docker version
docker compose version

git clone --branch master --single-branch https://github.com/MrFaviod/hadar-it.git hadar-it
cd hadar-it
git clone --branch master --single-branch https://github.com/MrFaviod/hadar-it-backend.git backend
git clone --branch master --single-branch https://github.com/MrFaviod/hadar-it-frontend.git frontend
```

You now have `compose.yaml`, `deploy/`, `backend/` and `frontend/` together. They remain independent Git repositories; there are no submodules to initialize.

## 2. Configure your local installation

Inside `hadar-it/`, copy the [configuration template](.env.example) without overwriting an existing `.env`:

```bash
(umask 077; cp -n .env.example .env)
chmod 600 .env
```

Open `.env` in your editor. Set `ITSM_SELINUX_LEVEL` to the unused MCS level allocated for this installation, and `ITSM_DEV_ADMIN_PASSWORD` to a new local password of **12–128 characters**. Do not reuse a real password. Use single quotes around values containing `$` or `#`.

The template selects development mode, its matching overlay, project `hadar-local` and local ports. Optional integration credentials can stay empty. `.env` is ignored by Git: never commit it or share its contents in logs. Compose reads it explicitly; the application itself reads process environment. Docker administrators can inspect container environments, so this is not a secret vault.

Use a fresh shell if you previously exported configuration: shell exports take precedence over `.env`.

Ports **18080** and **18000** must be free. If needed, change `ITSM_FRONTEND_PORT` / `ITSM_API_PORT` in `.env` and update `ITSM_AUTH_ORIGIN`, `ITSM_REPORT_BASE_URL` and `ITSM_MONITORING_PUBLIC_URL` to match the frontend address. Adjust the browser and health-check URLs below too.

## 3. Build and start

The first build downloads the pinned container images and application dependencies. Later starts reuse the images.

```bash
docker compose --env-file .env config --quiet
docker compose --env-file .env build backend frontend
docker compose --env-file .env up -d --wait --wait-timeout 180
docker compose --env-file .env ps -a
curl --fail http://127.0.0.1:18000/api/v1/health/ready
curl --fail --output /dev/null http://127.0.0.1:18080/
```

`initialize` should exit with code **0**; the backend and frontend should be **healthy**, and the worker should be running. Initialization applies migrations, creates the `dev.admin` Superadmin and adds fictional data. It does not reset that data on a timer.

Open **<http://127.0.0.1:18080>** and sign in as **`dev.admin`**, using the password you entered. Do not use `admin/admin`: that account belongs only to the separate public-demo mode.

Inventory, directory, maintenance, dashboard and SQL search do not need an AI provider. AI conversation, live monitoring, external notifications and optional search engines need their own configuration; an unconfigured integration is not a failed installation.

## 4. Stop and start again

From `hadar-it/`, using the same `.env`:

```bash
docker compose --env-file .env down
docker compose --env-file .env up -d --wait --wait-timeout 180
```

`down` keeps the installation's named volume. **Do not add `--volumes`** unless you intend to erase it. Do not run reset commands against data you want to keep.

After opening a new terminal, enter `hadar-it/` and reuse the existing `.env`; do not copy the template again or change the project name and MCS allocation. Initialization is idempotent; changing `ITSM_DEV_ADMIN_PASSWORD` does not change an existing account's password.

## If something stops

| Symptom | What to check |
|---|---|
| Clone returns “Repository not found” | GitHub authentication and access to all three private repositories. |
| Compose rejects `!override` | Upgrade the Compose plugin; do not remove the storage override. |
| A required variable is missing | Complete the required values in `.env` and keep `--env-file .env` in the command. |
| Port is already allocated | Change the ports and matching frontend URLs in `.env` consistently. |
| Initialization failed | Run `docker compose --env-file .env logs --tail=100 initialize`. Do not bypass the preparation gate. |
| Login fails on the other hostname | Use `127.0.0.1` consistently. `localhost` is a different origin. |
| The agent is unavailable | Configure a provider/runtime; local installation does not include inference credentials. |

Health confirms readiness, not every background job or integration. To check the worker, generate a report in the application and observe its completed result.

## Beyond the local walkthrough

- **Configuration and architecture:** [technical guide](docs/technical-guide.md).
- **TLS, databases, backups and the `prod` overlay:** [operations](docs/operations.md) and [release-mode reference](docs/release-modes-deployment.md). The name `prod` selects stricter behavior; it does not make this alpha production-ready. It starts without accounts and requires explicit `bootstrap-superadmin` after initialization. Build `backend` first, then the separate `initialize` maintenance image before starting that mode.
- **A resettable shared demo:** [demo deployment](docs/release-modes-deployment.md#3-starting-a-mode). It is a different installation, with fictional data, a reset timer and disabled integrations; public exposure requires TLS.

You can stay in this repository for the complete local installation. Component guides are for people developing those components, not extra installation steps.
