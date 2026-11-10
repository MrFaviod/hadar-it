# A walk through Hadar IT

[Install Hadar](../INSTALL.md) · [Project overview](../README.md) · [Technical guide](technical-guide.md)

Start with the department, then follow a piece of equipment through its day-to-day work.
These are real application screenshots using fictional demo records. The interface shown
is in Spanish. Demo monitoring is synthetic; the assistant needs a configured model.

## 1. Start with the whole picture

Open **Panel** for a shared overview of assets, maintenance and monitoring.
Use it to decide where to look next, rather than opening every asset one by one.

![Department dashboard](../assets/screenshots/dashboard.png)

## 2. Find the equipment

Open **Inventario**. Search or filter the list, then open an asset to see the details
that travel with it: category, location, responsible person and history.

![Inventory](../assets/screenshots/inventory.png)

The asset record brings its documents, relationships and maintenance into the same workspace.
The example below is a fictional hypervisor, not a real device.

![Asset record](../assets/screenshots/asset.png)

## 3. Connect people and places

**Personas** keeps responsible people and departments close to the equipment they use.

![People and departments](../assets/screenshots/people.png)

In **Infraestructura**, move between sites on the map and explore equipment relationships
in the graph. The graph describes dependencies; it does not perform automatic failover.

![Sites on the map](../assets/screenshots/infrastructure.png)

![Equipment relationship graph](../assets/screenshots/relationships.png)

## 4. Plan the next intervention

**Mantenimiento** brings scheduled work, plans and interventions together.
Open a task in the context of the affected equipment instead of keeping a separate checklist.
An unavailable engine is shown in the demo screen below.

![Maintenance workspace](../assets/screenshots/maintenance.png)

## 5. Follow monitoring and alerts

**Supervisión** brings monitored equipment and alerts into one view.
Connect your monitoring engine and targets for live telemetry; the demo uses synthetic signals.
No data is not the same as a healthy or failed device.

![Monitoring and alerts](../assets/screenshots/monitoring.png)

## 6. Keep warranties close

Open **Garantías** to review coverage and approaching expiry dates.
The report-preparation control shown here is not available yet.

![Warranties](../assets/screenshots/warranties.png)

## 7. Prepare reports and labels

In **Reportes**, choose the information and output format you need.
A running worker handles queued generation.

![Report setup](../assets/screenshots/reports.png)

In **Etiquetas**, choose a sheet or roll format and the assets to identify.
QR codes connect a physical label with the equipment record. These screenshots show
preparation screens, not generated documents.

![Label setup](../assets/screenshots/labels.png)

## 8. Bring existing records with you

Open **Datos → Importar** to start the import wizard. Review the mapping and validation
before confirming changes to inventory. This screenshot shows the first step.

![Import wizard](../assets/screenshots/data.png)

## 9. Make the workspace yours

In **Configuración → Apariencia**, adjust the installation name, logos and colors.

![Appearance settings](../assets/screenshots/appearance.png)

In **Usuarios y permisos**, give each person the access their work requires.
The server enforces those permissions, including actions requested by an assistant.

![Roles and permissions](../assets/screenshots/permissions.png)

## 10. Add an assistant

Open **Conversación** to work with the configured assistant and authorized inventory tools.
The demo below has no model configured, so it does not produce an AI response.

![Conversation before model configuration](../assets/screenshots/conversation.png)

Ready to try it? **[Follow the installation guide →](../INSTALL.md)**
