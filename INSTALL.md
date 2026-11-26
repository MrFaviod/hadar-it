# Install Hadar IT

From an empty folder to a running Hadar IT, in one guide. You do not need to visit the frontend and backend repositories: the commands below fetch both.

> **Alpha. For evaluation, not production.** This walkthrough creates a private local installation with fictional inventory. Use no real business data or reused passwords.

## Before you start

You need **Git**, **Bash**, **curl**, and **Docker with a recent Compose plugin** supporting `!override` (Compose 2.24.4 or later). Docker must be running and your account must be allowed to use it. You do **not** need Python, Node.js, PostgreSQL or an AI provider on the host. The three repositories are public.

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

Open `.env` in your editor. Set `ITSM_SELINUX_LEVEL` to the unused MCS level allocated for this installation. Leave `ITSM_DEV_ADMIN_PASSWORD` empty: the first start opens the setup wizard, which creates the owner in your browser. Use single quotes around values containing `$` or `#`.

The template selects development mode, its matching overlay, project `hadar-local` and local ports. Optional integration credentials can stay empty. `.env` is ignored by Git: never commit it or share its contents in logs. Compose reads it explicitly; the application itself reads process environment. Docker administrators can inspect container environments, so this is not a secret vault.

Settings precedence is **process environment > installation file > documented default**. `ITSM_INSTALLATION_CONFIG` optionally names a JSON file of installation-owned settings: an absolute path, mode `0600` inside a `0700` directory, never a symlink. A value whose environment variable is present wins even when it is explicitly empty. Keep that file private and out of Git.

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

`initialize` should exit with code **0**; the backend and frontend should be **healthy**, and the worker should be running. Initialization applies migrations, claims the database for `dev` and adds fictional data. Without `ITSM_DEV_ADMIN_PASSWORD` it creates no account: the installation stays ownerless until the wizard completes. It does not reset that data on a timer.

## 4. Create the first owner in the setup wizard

Ask the running setup service for a one-time claim credential:

```bash
docker compose --env-file .env exec -T setup python -m itsm.setup.cli enable-claim
```

The command prints the credential in this terminal once. It is never written to the container logs and the browser never shows it again.

Open **<http://127.0.0.1:18080>** and complete the wizard:

1. **Claim**: paste the credential. The browser receives the setup session and owns this installation.
2. **AI**: provider endpoint, model and key. This step needs the operator key ring `ITSM_AI_CREDENTIAL_KEYS`; without it the form reports the missing key instead of hiding the field. Choose defer to continue and keep AI as a visible pending item.
3. **Storage**: check and apply the installation's database.
4. **Owner**: choose the first Superadmin username and password. This is the account you will use.
5. **Verify and complete**: the required checks run; completing disables the wizard's bootstrap mutations.

The wizard is a separate unprivileged container. It has no Docker socket, no host path and no published host port: the frontend edge proxies `/api/setup/v1/`. It answers while the API and database are absent.

Inventory, directory, maintenance, dashboard and SQL search do not need an AI provider. AI conversation, live monitoring, external notifications and optional search engines need their own configuration; an unconfigured integration is not a failed installation.

## 5. Stop and start again

From `hadar-it/`, using the same `.env`:

```bash
docker compose --env-file .env down
docker compose --env-file .env up -d --wait --wait-timeout 180
```

`down` keeps the installation's named volume. **Do not add `--volumes`** unless you intend to erase it. Do not run reset commands against data you want to keep.

After opening a new terminal, enter `hadar-it/` and reuse the existing `.env`; do not copy the template again or change the project name and MCS allocation. Initialization is idempotent; changing `ITSM_DEV_ADMIN_PASSWORD` does not change an existing account's password.

## 6. First start, update and recovery

| Situation | What to do |
|---|---|
| First start | Complete the wizard in section 4. |
| Update an existing installation | Reuse the `up` commands above; `initialize` prepares the existing volumes again. |
| Lost claim before completion | Run `python -m itsm.setup.cli rotate-claim` in the `setup` container and use the new credential. |
| Reopen configuration after completion | Run `python -m itsm.setup.cli recover` in the `setup` container. It preserves the installation and its owner. |

The two operator commands run in the same container and take no browser session:

```bash
docker compose --env-file .env exec -T setup python -m itsm.setup.cli rotate-claim
docker compose --env-file .env exec -T setup python -m itsm.setup.cli recover
```

## 7. Alternatives to the wizard

### Headless development seed

To keep the previous non-interactive path, set `ITSM_DEV_ADMIN_PASSWORD` in `.env` to a new local password of **12–128 characters** before the first start. Preparation then creates the `dev.admin` Superadmin and the fictional dataset, and the setup wizard stays disabled. Sign in as **`dev.admin`** with that password. Do not use `admin/admin`: that account belongs only to the separate public-demo mode. Setting the variable on an installation that already has a wizard-created owner does not add a second owner.

### Production owner from the CLI

The `prod` mode creates no accounts. If no browser is available for the wizard, bootstrap the owner explicitly after initialization:

```bash
docker compose --env-file .env run --rm -e ITSM_BOOTSTRAP_PASSWORD backend \
  python -m itsm.identity.cli bootstrap-superadmin --username YOUR_USERNAME --name 'Installation owner'
```

## If something stops

| Symptom | What to check |
|---|---|
| Clone returns “Repository not found” | Check the repository URL and that Git can reach GitHub. |
| Compose rejects `!override` | Upgrade the Compose plugin; do not remove the storage override. |
| A required variable is missing | Complete the required values in `.env` and keep `--env-file .env` in the command. |
| Port is already allocated | Change the ports and matching frontend URLs in `.env` consistently. |
| Initialization failed | Run `docker compose --env-file .env logs --tail=100 initialize`. Do not bypass the preparation gate. |
| The wizard offers no claim | Run `enable-claim` in the `setup` container, and check `docker compose --env-file .env ps setup`. |
| The AI step is blocked | Supply `ITSM_AI_CREDENTIAL_KEYS` or defer the step; it stays pending, never reported as configured. |
| Login fails on the other hostname | Use `127.0.0.1` consistently. `localhost` is a different origin. |
| The agent is unavailable | Configure a provider/runtime; local installation does not include inference credentials. |

Health confirms readiness, not every background job or integration. To check the worker, generate a report in the application and observe its completed result.

## Beyond the local walkthrough

- **Configuration and architecture:** [technical guide](docs/technical-guide.md).
- **TLS, databases, backups and the `prod` overlay:** [operations](docs/operations.md) and [release-mode reference](docs/release-modes-deployment.md). The name `prod` selects stricter behavior; it does not make this alpha production-ready. It starts without accounts and requires the setup wizard or an explicit `bootstrap-superadmin` after initialization. Build `backend` first, then the separate `initialize` maintenance image before starting that mode.
- **A resettable shared demo:** [demo deployment](docs/release-modes-deployment.md#3-starting-a-mode). It is a different installation, with fictional data, a reset timer and disabled integrations; public exposure requires TLS.

You can stay in this repository for the complete local installation. Component guides are for people developing those components, not extra installation steps.
