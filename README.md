![Hadar IT — Bring your own department.](assets/banner.svg)

**Hadar IT** is a self-hosted, agent-first IT service management tool for small and mid-size companies with a small IT team. Inventory, people, sites, maintenance, monitoring and reports live in one place, and the built-in assistant, MCP clients and the REST API work on that same data under the same server-enforced permissions. The extension SDK lets each department shape it to the way it works.

**[Install](INSTALL.md)** · [Feature tour](docs/features.md) · [Technical guide](docs/technical-guide.md) · [All documentation](docs/README.md)

> [!WARNING]
> **Alpha.** Not ready for production. Evaluate it with fictional data and [report what breaks](https://github.com/MrFaviod/hadar-it/issues).

![Dashboard with fictional demo data](assets/screenshots/dashboard.png)

## What it covers

| Area | What you get |
|---|---|
| **Inventory** | Assets with custom fields, lifecycle, attachments, warranties and history. Structured imports, bulk operations and exports. |
| **People and places** | Departments, responsible people, sites, floors and floor plans. |
| **Infrastructure** | Relationship maps, dependency graphs and descriptive redundancy groups. |
| **Maintenance** | Preventive plans, interventions and incident records. |
| **Monitoring** | Telemetry, alert views and notifications through the services you connect. |
| **Dashboard and search** | Operational summaries, filters and saved views. SQL search built in; Meilisearch optional. |
| **Reports and labels** | Report templates, queued document generation, printable labels and QR codes. |
| **Access control** | Roles, permissions, audit records and personal API keys that never exceed their creator's current permissions. |
| **Agents and MCP** | A built-in assistant and an MCP server that act through the same domain permissions as a person would. |
| **Extensions** | SDK v2 packages, validated and installed only after explicit human approval. |
| **Customization** | Installation name, logos, colors, configurable fields and language packs. |

Some of this needs more than the base install. AI conversation, live monitoring and external notifications need their services configured. Queued reports and workflows need a running worker. Redundancy groups describe how equipment backs each other up; they do not perform failover. The [technical guide](docs/technical-guide.md#what-needs-configuration) lists what each capability requires.

## Try it

The [installation guide](INSTALL.md) takes you from an empty folder to a running instance with Docker Compose and fictional data, in four steps. You do not need Python, Node.js or a database on the host. The repositories are private for now, so your GitHub account needs access to all three.

Then follow the [feature tour](docs/features.md): ten short stops through the application, with screenshots.

![Inventory with fictional assets, sites and responsible people](assets/screenshots/inventory.png)

## Work in progress

Planned, not shipped:

- Fewer dependencies and backend optimization.
- Windows and Linux monitoring nodes.
- Ticketing with a small endpoint interface.
- Tactical RMM, AnyDesk and Zammad integrations.
- Single sign-on (SSO).
- Extensions written by the agent.
- A mobile app for notifications, alerts and QR workflows.

## Repositories

Hadar IT is three Git repositories cloned into one workspace:

| Repository | Contents |
|---|---|
| [hadar-it](https://github.com/MrFaviod/hadar-it) | This one: Compose, deployment modes, installation and all maintained documentation. |
| [hadar-it-frontend](https://github.com/MrFaviod/hadar-it-frontend) | Browser application: React and TypeScript host with Vue domain views. |
| [hadar-it-backend](https://github.com/MrFaviod/hadar-it-backend) | API, domain services, worker, agents and extension host: Python and FastAPI. |

Contributors start with the [technical guide](docs/technical-guide.md), then the [frontend](docs/frontend/development.md) or [backend](docs/backend/development.md) development guide.

## License

[MIT](LICENSE). It is yours to run, change and extend.

[![Built with Gentle-AI](https://raw.githubusercontent.com/Gentleman-Programming/gentle-ai/main/docs/assets/brand/built-with-gentle-ai.png)](https://github.com/Gentleman-Programming/gentle-ai)
