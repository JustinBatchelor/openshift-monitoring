# Deployment status — October 29, 2026 (America/New_York)

## Deployed and verified

- OpenShift 4.22.18, nodes `sno` and `worker-0`.
- Official TrueNAS CSI operator 1.1.2 installed from certified-operators;
  manual future upgrade approval and pinned certified driver image.
- TrueNAS 25.10.1, pool `main` ONLINE, approximately 15.6 TiB initially available.
  iSCSI enabled with a wildcard portal because TrueNAS uses a DHCP interface.
  New targets restrict access to the two verified persistent node initiators.
- Supported iSCSI MachineConfigs rolled out worker first, then master, during
  the user-approved maintenance window. Both nodes and MCPs recovered healthy.
- Non-default `truenas-monitoring-iscsi` class: ext4, RWO, expandable only on an
  explicit PVC request, Retain. Existing `truenas-nfs` remains the default.
- Storage acceptance passed: provisioning, data persistence after pod replacement,
  1→2 GiB filesystem expansion, and PV retention after test claim deletion.
- Prometheus: 50 GiB Bound PVC, 15-day retention, 40 GB retention-size limit.
- Alertmanager: 5 GiB Bound PVC; original routing and inhibition rules preserved.
- Grafana 13.3.0: 5 GiB Bound PVC, authenticated HTTPS Route at
  <https://grafana.apps.sno.batchelor.live>, three provisioned dashboards.
- Unauthenticated Grafana API returned 401; certificate verification passed;
  Thanos datasource health and all three dashboards verified.
- A fixed-time historical Prometheus query survived pod replacement unchanged.
- A bounded Alertmanager test silence survived pod replacement and was removed.
- Grafana's saved home-dashboard preference and datasource survived pod replacement.
- NFS exports, service settings, root ACLs, and dataset access properties match
  the read-only baseline. No existing share or user permissions were changed.
- Four merge/endpoint tests passed, Helm lint/render validation passed, all scripts
  compiled, and the existing NFS chart lint/render/shell-syntax checks passed.
- Full proposed Alertmanager configuration validated using the running `amtool`,
  with nonfunctional sample URLs; no fake receivers were applied.

## Pending external setup / acceptance

Rechecked October 29 at 22:54 America/New_York (October 30, 02:54 UTC):
both nodes Ready, all operators Available/non-Degraded, monitoring and Grafana
pods Running/Ready, and all three production monitoring PVCs Bound. The storage
test namespace has no remaining pods or claims. Grafana authentication,
datasource health, three dashboards, and the unchanged NFS access baseline passed
again. Four unit tests and Helm/source validation also passed.

- Slack plugin installation is confirmed, but workspace/channel tool calls return
  `Unknown tool`. No channels or messages have been created through the connector.
- Slack webhooks for `#cluster-critical` and `#cluster-warnings` have not been
  supplied. Slack receivers are **not yet live**.
- Healthchecks account/check and ping URL have not been supplied. External
  heartbeat delivery and missing-heartbeat/recovery tests are **not yet live**.
- Slack workspace quiet hours and iPhone settings require configuration and
  daytime locked-phone validation: weekdays 09:00–18:00 America/New_York.
- 24-hour and seven-day observations remain future checks; they are not complete.

## Repository publication

The owner created `JustinBatchelor/openshift-monitoring` as a public repository
and explicitly approved publishing the NFS permission inventory after reviewing
what it reveals. The earlier private-repository requirement is superseded by
that instruction. Credentials and protected backups remain outside Git.
The sibling storage changes were pushed to `JustinBatchelor/openshift-storage`
as commit `39fbaaa` on `main`, and that remote commit was verified.

## Retained acceptance data

Two 2 GiB test PVs are Released/Retain and intentionally preserved:

- `pvc-a06cbd21-7b37-4eab-a6b7-5d44fd484b9d`
- `pvc-0ceeb9ab-55ac-403a-a353-76f46277e3f1`

The first test exposed a duplicate filesystem parameter in the initial class;
it was corrected before production volumes existed. The second full test validated
the final class UID and explicit remount handling. No automatic zvol deletion is
part of cleanup. Protected rollback snapshots and test evidence are in `.state/`.
