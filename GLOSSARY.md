# Infrastructure inventory language

Terms for representing physical and virtual infrastructure and redundancy. These describe inventory, not automated infrastructure operations.

## Hosting and redundancy

**Instance**:
An independently identified asset, such as a VM or container, that can have its own host and technical characteristics.
_Avoid_: Treating two replicas as one asset installed on two hosts

**Host**:
The asset on which an instance is hosted. Changing the recorded host updates the inventory; it does not perform a live migration.

**Redundancy group**:
A named set of independently identified instances that provide backup or share the same workload, regardless of their individual hosts.
_Avoid_: Using multiple hosting relationships to represent replicas

**Active/passive**:
A redundancy arrangement in which a primary instance serves the workload and a backup instance is available to take over.

**Active/active**:
A redundancy arrangement in which multiple instances serve the workload concurrently.

**Traffic share**:
The configured percentage of a group's workload assigned to a member, for example 40% and 60%. It is descriptive inventory information, not measured utilization or host resource allocation.
_Avoid_: Capacity percentage, CPU allocation
