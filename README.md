![Hadar IT](assets/hadar-star.webp)

# Hadar IT

Self-hosted IT asset and operations management: inventory, people, locations,
maintenance, monitoring and reporting.

**[Installation](INSTALL.md)** · [Feature guide](docs/features.md) · [Technical guide](docs/technical-guide.md)

> Alpha software. Not ready for production.

![Dashboard with fictional demo data](assets/screenshots/dashboard.png)

## Features

- **Asset inventory:** custom fields, lifecycle, attachments, warranties and asset history.
- **People and locations:** departments, responsible people, sites and floors.
- **Relationships:** infrastructure maps, dependency graphs and descriptive redundancy groups.
- **Maintenance:** preventive plans, interventions and incident records.
- **Dashboard and search:** operational summaries, filters and saved views; optional Meilisearch.
- **Monitoring and alerts:** telemetry, alert views and notifications through configured services.
- **Imports and exports:** structured data import, bulk operations and data exports.
- **Reports and labels:** report templates, queued document generation, printable labels and QR codes.
- **Access control:** roles, permissions, audit records and scoped API access.
- **AI and MCP:** an optional assistant and agent tools using the same domain permissions.
- **Extensions:** SDK v2 packages with validation and explicit human approval before installation.
- **Customization:** appearance settings, configurable fields and language packs.

AI, live monitoring and external notifications require configured services.
Queued reports and workflows require a running worker. Redundancy groups describe
relationships; they do not perform failover. See the [technical guide](docs/technical-guide.md)
for configuration and limits.

## Inventory

![Inventory with fictional assets, sites and responsible people](assets/screenshots/inventory.png)

The [feature guide](docs/features.md) covers the application with screenshots.

## Installation

Follow the [installation guide](INSTALL.md) to clone all three repositories and
start the application with Docker Compose. Repository access is required while
the project remains private.

## Work in progress

The following items are not available as completed features:

- Dependency reduction and backend optimization.
- Windows and Linux monitoring nodes.
- Ticketing with a small endpoint interface.
- Tactical RMM, AnyDesk and Zammad integrations.
- Single sign-on (SSO).
- Agent-authored extensions.
- Mobile application for notifications, alerts and QR workflows.

## Development

React and TypeScript frontend; Python and FastAPI backend.

[Documentation index](docs/README.md) · [Architecture and configuration](docs/technical-guide.md) · [Frontend](https://github.com/MrFaviod/hadar-it-frontend) · [Backend](https://github.com/MrFaviod/hadar-it-backend)

[Issues](https://github.com/MrFaviod/hadar-it/issues) · [License](LICENSE)
