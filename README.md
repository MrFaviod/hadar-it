# Unnamed ITSM project

Development workspace for an unnamed project evolving from asset management (ITAM) toward service management (ITSM). The frontend is pre-alpha; the backend stack has not been selected. “Asset Manager” is the inherited UI label, not a final project name.

## Layout

```text
asset/                 # coordination Git repository
├── AGENTS.md          # shared development rules
├── VERSION            # independent unreleased release version: 0.0.0
├── odd/tasks/         # cross-component ODD work
├── frontend/          # independent Git; preserved frontend history
│   ├── AGENTS.md      # frontend-specific context
│   ├── package.json   # internal frontend version 0.1.0, pre-alpha
│   └── README.md      # detailed frontend commands/demo boundaries
└── backend/           # independent Git; no code or stack yet
    ├── AGENTS.md
    └── README.md
```

Root Git deliberately ignores both component repositories. **Cloning or backing up root alone does not include either component.** Each repository must be committed/backed up independently; no remotes, submodules or deployment are configured by this preparation.

## Run the existing frontend

From `asset/`:

```bash
cd frontend
npm ci                 # only if dependencies are not installed
npm run dev            # http://127.0.0.1:5173
```

Verification and local production preview:

```bash
npm --prefix frontend run check
npm --prefix frontend run build
npm --prefix frontend run preview -- --port 4173
```

The UI currently uses a React 19/TypeScript/Vite host around extensive Vue 3 domain views. It is not a full React rewrite. Authentication, monitoring and integrations remain client-side demo behavior. See [frontend/README.md](frontend/README.md).

## Versions and workflow

- Root `VERSION`: release `0.0.0` (unreleased foundation).
- Frontend: internal `0.1.0`, pre-alpha, unchanged by this relocation.
- Backend: internal version and stack not assigned yet.

Use related, verified commits in the correct repository. Branch only when a functional base needs a meaningful experiment or a separate version line; parallel writers require separate component worktrees. Read [AGENTS.md](AGENTS.md) and the relevant nested instructions. Follow ODD and load all relevant skills for both parent and subagents. Keep solutions simple.

## Next boundary

Define backend requirements and stack with the human before creating application code, dependency manifests, API contracts or database configuration. There is no backend startup command yet.
