# Operations and acceptance

## Troubleshooting from an alert

Open the linked dashboard and inspect the affected namespace/node. In OpenShift,
check `oc get clusteroperators`, `oc get events -n <namespace> --sort-by=.lastTimestamp`,
`oc describe pod ...`, and `oc logs ... --previous` as appropriate. Dashboards use
the existing metrics; missing PVC data is displayed as unavailable, never zero.
The current NFS directory PVC sizes do not enforce dataset quotas.

For storage failures, check the PVC events, CSI controller/node logs, TrueNAS pool
health, and TCP 3260. Never delete a PVC, zvol, target, or CSI driver to troubleshoot
a mount problem. Do not change existing NFS mappings, ACLs, or users.

## Acceptance checklist

- Storage test passes and the exact node initiator allow-list appears on the
  provisioned TrueNAS target; verify filesystem capacity increased, not only PVC size.
- Prometheus and Alertmanager PVCs are Bound. New metrics are queryable.
- Save a distinctive sample timestamp/query result, replace only the Prometheus
  pod, wait for Ready, and query the same historical sample successfully.
- Create a short-lived test silence for `alertname=MonitoringAcceptanceOnly`,
  record its ID, replace only the Alertmanager pod, and verify the same silence
  is still present. Remove the test silence afterward.
- Restart Grafana and verify its database, datasource, and all three dashboards.
- An unauthenticated request to `/api/search` receives 401; HTTPS is valid, HTTP
  redirects, and the authenticated datasource health check succeeds.
- Send synthetic alerts through Alertmanager `/api/v2/alerts`, with unique test
  names, namespace `monitoring-acceptance`, severity critical/warning, and bounded
  `endsAt`. Confirm separate Slack channels, grouped messages, and resolutions.
  This is a real notification test. Never install test rules in operator-managed
  namespaces or silence real cluster alerts to make a test pass.
  Use `.venv/bin/python scripts/test_notifications.py`, then rerun with
  `--resolve` after delivery to verify recovery messages. The script refuses to
  send unless the managed Slack receivers are configured.
- During the weekday notification window, confirm critical delivery with the
  iPhone locked and warning-channel silence. If testing outside the window,
  record Slack delivery separately from pending phone acceptance.
- Save Alertmanager's current Secret securely. Temporarily route only Watchdog
  to a null receiver; keep critical/warning routes active. Expect Healthchecks
  down in roughly five minutes. Restore the saved Watchdog route even if the test
  fails; confirm recovery. Never stop the cluster for this test.
- Run the NFS baseline comparison again. If anything differs, investigate rather
  than overwriting live permissions with the snapshot.

## Rollback

`scripts/monitoring.py` creates timestamped, mode-0600 JSON snapshots under
`.state/` before each mutation. A `null` storage snapshot means the ConfigMap
did not previously exist. Restore only the intended component, using the current
resourceVersion and omitting managedFields and status. Review newer edits first.
Never blindly apply a stale full snapshot over another administrator's changes.

If the ConfigMap was absent, remove only the storage/retention keys introduced
here from the current config; delete the ConfigMap only if nothing else remains.
Returning to emptyDir does not restore old metrics history. Removing a volume
claim template can recreate monitoring pods; do this during maintenance.

For notifications, restore only the saved `alertmanager.yaml` data key in the
current Secret, validate with `amtool`, and retain other current Secret metadata.
For Grafana, prefer Helm rollback to a known-good revision. Keep its PVC.
Do not uninstall CSI while volumes use it, remove node iSCSI configuration while
sessions are active, or delete retained PVs/zvols as an automatic rollback step.
The prior TrueNAS iSCSI service was disabled and stopped; do not restore that state
while any new storage consumer remains attached. Existing NFS remains independent.

## Follow-up observation

After a successful live rollout, review after 24 hours: operators, node health,
PVC usage, CSI errors, Prometheus scrape/notification failures, and the external
heartbeat history. After seven days, review alert noise and disk growth, then
adjust retention/capacity from observed ingestion. These are manual follow-ups;
this repository does not create an unrequested recurring automation.
