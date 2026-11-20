# Documentation

[Project overview](../README.md) · [Installation](../INSTALL.md) · [Feature tour](features.md) · [Technical guide](technical-guide.md)

Every maintained guide for Hadar IT lives here, grouped by topic. Component repositories hold code, tests and short READMEs. Hadar IT is alpha and not certified for production.

## Start here

- [Install Hadar IT](../INSTALL.md): from an empty folder to a running local instance.
- [Feature tour](features.md): the application in ten stops, with screenshots.
- [Technical guide](technical-guide.md): architecture, deployment modes and what each capability needs.
- [Infrastructure and identity operations](operations.md) ([español](operations.es.md)): configuration, modes, TLS, integrations, upgrades, backups and checks.
- [Advanced operation of the installation](user-operations.en.md) ([español](user-operations.md)): a shorter path for whoever administers the server.
- [Glossary](../GLOSSARY.md): infrastructure and redundancy terms.

## Inventory and assets

Asset records, the catalog that shapes them, identification and attachments.

- [Asset core: common fields, lifecycle, history and media](backend/asset-core.md)
- [Inventory service and agent interfaces](backend/inventory.md)
- [Inventory catalog and form configuration](backend/inventory-catalog.md)
- [Inventory identification, catalog validation and tool projections](backend/inventory-identification.md)
- [Asset attachments](backend/attachments.md)
- [Inventory in the frontend](frontend/inventory.md)

## People, places and infrastructure

The directory, locations and floor plans, relationships between assets and redundancy groups.

- [Directory: inventory people, departments and hierarchical locations](backend/directory.md)
- [Directory floor-plan media](backend/directory-media.md)
- [Asset organization: sites, locations, people, positions and map data](backend/asset-organization.md)
- [Relationships and structured history](backend/relationships.md)
- [Redundancy groups](backend/redundancy.md)
- [Directory, relationships, graph and map](frontend/organization.md)
- [Map and graph explorer](frontend/explorer.md)
- [Redundancy groups in the interface](frontend/redundancy.md)
- [Infrastructure expansion](frontend/infrastructure-expansion.md)

## Maintenance, monitoring and notifications

Preventive plans, interventions and incidents, monitoring with Prometheus and Alertmanager, and how events reach people.

- [Preventive maintenance](backend/maintenance.md)
- [Technical interventions and incidents](backend/interventions.md)
- [Monitoring, alerts and maintenance windows](backend/monitoring.md)
- [Infrastructure monitoring on the canvases](frontend/infrastructure-monitoring.md)
- [Notifications](backend/notifications.md)
- [Entity change events](backend/entity-events.md)

## Dashboard, search, reports and data

The operational dashboard, global search, documents and labels, and imports and exports.

- [Operations dashboard and workspace](backend/workspace.md)
- [Dashboard, workspace and universal search (frontend)](frontend/workspace.md)
- [Global search](backend/search.md)
- [Reports, QR codes, labels and generated documents](backend/reports.md)
- [Report rendering engine](backend/report-rendering.md)
- [Reports, labels and QR codes (frontend)](frontend/reports.md)
- [Workflows](backend/workflows.md)
- [Imports, exports and bulk workflows (frontend)](frontend/workflows.md)

## Identity and access

Accounts, roles and permissions, the system profiles and personal API keys for REST and MCP.

- [Identity, authentication and authorization](backend/identity.md)
- [System profiles (frontend)](frontend/system-profiles.md)
- [Personal API keys for REST and MCP](backend/personal-api-keys.md)

## AI, agents and MCP

The built-in assistant, external engines (Hermes, OpenCode), MCP tools, skills, the AI gateway and usage quotas.

- [Conversation and AI](frontend/unified-ai-experience.md)
- [Agent engines and integrations (frontend)](frontend/agent-integrations.md)
- [Guarded chat attachments](frontend/ai-multimodal.md)
- [Agent integrations and conversational control](backend/agent-integrations.md)
- [Agent integration installer](backend/agent-installer.md)
- [Agent skill catalog and module extensions](backend/agent-skills.md)
- [Agent and MCP domain tools](backend/agent-tools.md)
- [Compact operational tools for agents and MCP](backend/workspace-agent-tools.md)
- [External agent engines](backend/external-engines.md)
- [Engine profile verification](backend/engine-profile-verification.md)
- [Managed AI gateway](backend/ai-gateway.md)
- [Disposable managed native runs](backend/ai-managed.md)
- [AI runtime isolation](backend/ai-runtime-isolation.md)
- [AI usage quotas](backend/ai-usage.md)
- [AI usage evidence](backend/ai-usage-evidence.md)

## Extensions

The SDK v2 package contract, the host that validates and isolates it, and the interface it can draw.

- [Extension SDK](backend/extensions-sdk.md)
- [Native extension host (SDK v2)](backend/extensions-host.md)
- [Extensions: interface and review (SDK v2)](frontend/extensions-sdk.md)

## Appearance, language and design

Branding, appearance presets, translations and the rules behind the interface.

- [Brand](frontend/brand.md)
- [Interface design](frontend/design.md)
- [Installation appearance and per-user mode](frontend/appearance.md)
- [Installation appearance](backend/appearance.md)
- [Frontend internationalization (`ui.*`)](frontend/i18n.md)
- [Internationalization (core, registry and language packs)](backend/i18n.md)
- [In-app help](frontend/user-help.md)

## Deployment, operations and development

Release modes, preparation and backups, the demo, system operations and working on each component.

- [Release-mode deployment: `dev`, `prod` and `demo`](release-modes-deployment.md)
- [Release modes: `dev`, `prod`, `demo`](backend/release-modes.md)
- [Mode preparation and backup scheduler](backend/deployment-preparation.md)
- [Backup, restore, retention and guarded upgrade](backend/ops-backup-restore.md)
- [System operations](backend/system-operations.md)
- [Isolated demonstration installation](backend/demo.md)
- [Public demo: restricted administrator and exposure limits](backend/demo-public.md)
- [Shared demo reset](backend/demo-reset.md)
- [Development mode: initialize, inspect and reset a dev database](backend/dev-mode.md)
- [Backend foundation](backend/foundation.md)
- [Backend development](backend/development.md)
- [Frontend development](frontend/development.md)
- [Setup and onboarding contract](onboarding-contract.md)
