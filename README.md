# OpenShift monitoring

Monitoring for `sno.batchelor.live`: existing OpenShift Prometheus/Alertmanager,
Grafana OSS, Slack mobile notifications, and a Healthchecks.io heartbeat.
See [STATUS.md](STATUS.md) for what has actually been deployed and tested.

## Layout and prerequisites

- `config/monitoring.yaml`: retention, routing, and the agreed notification window.
- `grafana/`: Helm chart and three provisioned dashboards; Grafana 13.3.0.
- `scripts/`: guarded configuration merges, storage acceptance, NFS access capture.
- `inventory/`: NFS export/permission baseline, approved by the owner for public
  publication. Credentials and protected rollback backups remain excluded.
- Sibling `../openshift-storage/truenas-csi/`: CSI operator, driver, storage class,
  MachineConfigs, and isolated storage-test resources.

Requires Python 3.9+, Helm 3, `oc`, cluster-admin access, and the two sibling
checkouts. Create a virtual environment and install `requirements.txt`.
Never put API keys, webhook URLs, rendered Alertmanager Secrets, or kubeconfigs
in Git. `.secrets/` and `.state/` are ignored. Backups are created mode 0600.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/validate.py
```

## 1. Storage and NFS preservation

Follow the sibling storage repository's `truenas-csi/README.md`. Install the
operator with manual approval; validate the exact InstallPlan before approving
version 1.1.2. Run the read-only prerequisite check, then configure iSCSI:

```sh
.venv/bin/python scripts/truenas_preflight.py --key-file /secure/path/truenas-key
.venv/bin/python scripts/setup_truenas.py --key-file /secure/path/truenas-key --apply
```

The key file must contain only the API key. The setup command does not modify
NFS exports, dataset ACLs, existing PVCs, or the default storage class.
The TrueNAS API credential is powerful: keep it restricted to CSI administrators
and rotate it when appropriate. Do not put it on the command line itself.

Apply node MachineConfigs one pool at a time during a maintenance window. They
preserve an existing initiator identity and initialize a missing one, then enable
`iscsid`. Read the **actual** resulting initiator names on both nodes and set
`iscsi.initiators` in the new storage class to exactly those values before use.
Check TCP 3260 from both nodes and verify new targets enforce that allow-list.

```sh
.venv/bin/python scripts/capture_nfs.py --key-file /secure/path/truenas-key --compare inventory/nfs-access-baseline.json
.venv/bin/python scripts/test_storage.py
```

The storage test creates only resources in `monitoring-storage-test`, verifies
provisioning, marker persistence after pod replacement, and 1→2 GiB filesystem
expansion. It removes its test Deployment/PVC, verifies the PV becomes Released,
and leaves the PV and TrueNAS data retained. It records a cluster/storage-class
specific gate in `.state/storage-validated.json`. Do not manually fabricate this
gate. Retained test data requires deliberate, separately reviewed cleanup.

## 2. Slack and Healthchecks

Create `#cluster-critical` and `#cluster-warnings` in your existing workspace.
Create a Slack app with an incoming webhook authorized for each channel; Slack
incoming webhooks are bound to their authorized channel. Store each URL in a
separate mode-0600 file under `.secrets/`, without committing it.

Create one Healthchecks.io check: name `OpenShift sno Watchdog`, simple period
**60 seconds**, grace **240 seconds**. Connect its Slack integration to
`#cluster-critical`, and save its success ping URL in a third credential file.
Do not configure a time-of-day schedule on the heartbeat check.

```sh
.venv/bin/python scripts/monitoring.py notifications \
  --critical-file .secrets/slack-critical \
  --warning-file .secrets/slack-warnings \
  --heartbeat-file .secrets/healthchecks-ping
# Repeat the same command with --apply after the dry run passes.
```

This reads the current Alertmanager configuration, preserves inhibition rules
and existing fallback routes, prepends the managed routes, validates the complete
configuration using the running Alertmanager's `amtool`, and replaces the Secret
using its resourceVersion. Existing routes for critical/warning alerts are
superseded by these channels; unrelated routes remain fallback routes. Concurrent
edits fail rather than silently overwrite. No rendered credentials are printed.

Configure Slack on the iPhone:

1. For this workspace set notification hours Monday–Friday, 09:00–18:00,
   timezone **America/New_York**. This affects the entire workspace.
2. Critical channel: all new messages. Warning channel: mentions only.
3. Mobile timing: immediately, even when active on desktop.
4. Allow Slack in the iOS Focus modes where daytime alerts should arrive.

Messages and heartbeats continue 24/7. Overnight/weekend phone silence is
intentional; push delivery and missed-alert catch-up are not guaranteed paging.

## 3. Persistence cutover and Grafana

The approved cutover starts a fresh metrics history and briefly interrupts
monitoring. The scripts save the prior ConfigMap (or its absence) and Secret in
`.state/`. Export any specific old reports you need before the cutover.
The 50 GiB iSCSI PVC is a fixed filesystem size. `allowVolumeExpansion` permits
an explicit resize request; it does not grow automatically. Prometheus removes
old data at 15 days or 40 GB, whichever comes first, with headroom for WAL and
compaction. Unlike the existing NFS directory claims, this is a real block-device
capacity limit. Retention is not a substitute for disk-space alerts.

```sh
.venv/bin/python scripts/monitoring.py storage
.venv/bin/python scripts/monitoring.py storage --apply
oc rollout status statefulset/prometheus-k8s -n openshift-monitoring --timeout=10m
oc rollout status statefulset/alertmanager-main -n openshift-monitoring --timeout=10m
oc apply -f manifests/namespace.yaml
.venv/bin/python scripts/monitoring.py grafana-admin --apply
helm template cluster-grafana grafana --namespace observability | oc apply --dry-run=server -f -
helm upgrade --install cluster-grafana grafana --namespace observability --wait --timeout 10m
```

Grafana is at <https://grafana.apps.sno.batchelor.live>. Retrieve the generated
`grafana-admin` Secret through your local OpenShift console; do not paste it into
chat or publish it. Its value is preserved on subsequent setup runs. Changing
that Secret alone does not change an already initialized Grafana database's
administrator password; use Grafana's supported password-change procedure.

The route terminates TLS at the OpenShift router; ingress to port 3000 is limited
to router namespaces. Grafana uses verified TLS to Thanos with the injected
OpenShift service CA. Its dedicated service account can read cluster metrics;
access to Grafana should therefore remain restricted to cluster administrators.

### Metrics credential rotation

`grafana-metrics-token` is a deliberately persistent service-account token Secret
because Grafana reads its datasource credential at startup. It is not a personal
admin token. Rotate by creating a new service-account-token Secret annotated for
service account `grafana`, wait for token population, set `metricsTokenSecret`
to its name in Helm values, upgrade, and verify queries. Then delete only the old
token Secret. Schedule/review rotation during routine maintenance. Never use a
short-lived `oc create token` result as permanent datasource configuration.

## Acceptance, rollback, and follow-up

Follow [docs/operations.md](docs/operations.md). Mark individual checks in
STATUS.md with evidence; a dry run does not count as live delivery or persistence.
Do not claim the 24-hour or seven-day review has passed before it occurs.

Reference documentation: [TrueNAS operator](https://www.truenas.com/docs/solutions/integrations/csidriver/),
[OpenShift monitoring](https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.22),
[Healthchecks ping API](https://healthchecks.io/docs/http_api/).
