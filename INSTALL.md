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

Continue in the **same Bash session**, inside `hadar-it/`. Choose a new local password of **12–128 characters** when prompted. Neither prompt writes the password into shell history.

```bash
export RELEASE_MODE=dev
export COMPOSE_PROJECT_NAME=hadar-local
export COMPOSE_FILE=compose.yaml:deploy/compose.dev.yaml
export ITSM_AUTH_ORIGIN=http://127.0.0.1:18080
export ITSM_FRONTEND_PORT=18080
export ITSM_API_PORT=18000

read -rp 'Installation MCS level (allocated for this stack): ' ITSM_SELINUX_LEVEL
export ITSM_SELINUX_LEVEL
read -rsp 'New local administrator password: ' ITSM_DEV_ADMIN_PASSWORD
printf '\n'
export ITSM_DEV_ADMIN_PASSWORD
```

No `.env` file is created or read. The explicit `--env-file /dev/null` below disables Compose's automatic `.env` loading. Configuration comes from this shell; Docker administrators can inspect container environments, so this is not a secret vault. Keep the password in your password manager, not in a repository.

Ports **18080** and **18000** must be free. If they are occupied, choose different `ITSM_FRONTEND_PORT` / `ITSM_API_PORT` values and change `ITSM_AUTH_ORIGIN` to match the frontend port before continuing. Use that same address in your browser.

## 3. Build and start

The first build downloads the pinned container images and application dependencies. Later starts reuse the images.

```bash
docker compose --env-file /dev/null config --quiet
docker compose --env-file /dev/null build backend frontend
docker compose --env-file /dev/null up -d --wait --wait-timeout 180
docker compose --env-file /dev/null ps -a
curl --fail http://127.0.0.1:18000/api/v1/health/ready
curl --fail --output /dev/null http://127.0.0.1:18080/
```

`initialize` should exit with code **0**; the backend and frontend should be **healthy**, and the worker should be running. Initialization applies migrations, creates the `dev.admin` Superadmin and adds fictional data. It does not reset that data on a timer.

Open **<http://127.0.0.1:18080>** and sign in as **`dev.admin`**, using the password you entered. Do not use `admin/admin`: that account belongs only to the separate public-demo mode.

Inventory, directory, maintenance, dashboard and SQL search do not need an AI provider. AI conversation, live monitoring, external notifications and optional search engines need their own configuration; an unconfigured integration is not a failed installation.

## 4. Stop and start again

In the same configured shell:

```bash
docker compose --env-file /dev/null down
docker compose --env-file /dev/null up -d --wait --wait-timeout 180
```

`down` keeps the installation's named volume. **Do not add `--volumes`** unless you intend to erase it. Do not run reset commands against data you want to keep.

After opening a new terminal, enter `hadar-it/` and repeat the exports and prompts from step 2 with the **same project name, ports and MCS level**. Initialization is idempotent; changing the environment password does not change an existing account's password.

## If something stops

| Symptom | What to check |
|---|---|
| Clone returns “Repository not found” | GitHub authentication and access to all three private repositories. |
| Compose rejects `!override` | Upgrade the Compose plugin; do not remove the storage override. |
| A required variable is missing | Repeat step 2 in the shell running Compose. |
| Port is already allocated | Change the two port exports and the browser origin consistently. |
| Initialization failed | Run `docker compose --env-file /dev/null logs --tail=100 initialize`. Do not bypass the preparation gate. |
| Login fails on the other hostname | Use `127.0.0.1` consistently. `localhost` is a different origin. |
| The agent is unavailable | Configure a provider/runtime; local installation does not include inference credentials. |

Health confirms readiness, not every background job or integration. To check the worker, generate a report in the application and observe its completed result.

## Beyond the local walkthrough

- **Configuration and architecture:** [technical guide](docs/technical-guide.md).
- **TLS, databases, backups and the `prod` overlay:** [operations](docs/operations.md) and [release-mode reference](docs/release-modes-deployment.md). The name `prod` selects stricter behavior; it does not make this alpha production-ready. It starts without accounts and requires explicit `bootstrap-superadmin` after initialization. Build `backend` first, then the separate `initialize` maintenance image before starting that mode.
- **A resettable shared demo:** [demo deployment](docs/release-modes-deployment.md#3-starting-a-mode). It is a different installation, with fictional data, a reset timer and disabled integrations; public exposure requires TLS.

You can stay in this repository for the complete local installation. Component guides are for people developing those components, not extra installation steps.
