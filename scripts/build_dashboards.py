#!/usr/bin/env python3
"""Generate deterministic, provisioned dashboards from reviewed PromQL."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def panel(title, expression, index, unit='short', description=''):
    return {'id': index + 1, 'title': title, 'type': 'timeseries', 'description': description,
            'gridPos': {'h': 8, 'w': 12, 'x': (index % 2)*12, 'y': (index//2)*8},
            'datasource': {'type': 'prometheus', 'uid': 'openshift'},
            'targets': [{'refId': 'A', 'expr': expression, 'legendFormat': '{{namespace}} {{pod}} {{node}} {{name}} {{persistentvolumeclaim}} {{instance}}'}],
            'fieldConfig': {'defaults': {'unit': unit, 'noValue': 'No metrics', 'custom': {'spanNulls': False}}, 'overrides': []},
            'options': {'legend': {'displayMode': 'table', 'placement': 'bottom'}, 'tooltip': {'mode': 'multi'}}}


DASHBOARDS = {
    'cluster-health': [
        ('Nodes ready', 'kube_node_status_condition{condition="Ready",status="true"}', 'short'),
        ('Operators available', 'cluster_operator_conditions{condition="Available"}', 'short'),
        ('Operators degraded', 'cluster_operator_conditions{condition="Degraded"}', 'short'),
        ('Firing alerts by severity', 'count by (severity) (ALERTS{alertstate="firing",alertname!="Watchdog"})', 'short'),
        ('Monitoring scrape targets', 'up{namespace="openshift-monitoring"}', 'short'),
        ('Notification failures in 1 hour', 'sum by (integration) (increase(alertmanager_notifications_failed_total[1h]))', 'short'),
    ],
    'workload-resources': [
        ('CPU used by namespace (cores)', 'sum by (namespace) (rate(container_cpu_usage_seconds_total{container!="",container!="POD",namespace!=""}[5m]))', 'cores'),
        ('CPU requested by namespace', 'sum by (namespace) (kube_pod_container_resource_requests{resource="cpu"})', 'cores'),
        ('CPU limits by namespace', 'sum by (namespace) (kube_pod_container_resource_limits{resource="cpu"})', 'cores'),
        ('Memory used by namespace', 'sum by (namespace) (container_memory_working_set_bytes{container!="",container!="POD",namespace!=""})', 'bytes'),
        ('Memory requested by namespace', 'sum by (namespace) (kube_pod_container_resource_requests{resource="memory"})', 'bytes'),
        ('Memory limits by namespace', 'sum by (namespace) (kube_pod_container_resource_limits{resource="memory"})', 'bytes'),
        ('Container restarts in 1 hour', 'sum by (namespace,pod) (increase(kube_pod_container_status_restarts_total[1h]))', 'short'),
    ],
    'capacity-storage': [
        ('Node CPU utilization', '1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))', 'percentunit'),
        ('Node memory utilization', '1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes', 'percentunit'),
        ('Local filesystem available', 'node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"}', 'bytes'),
        ('PVC available capacity (reported only)', 'kubelet_volume_stats_available_bytes', 'bytes'),
        ('PVC used capacity (reported only)', 'kubelet_volume_stats_used_bytes', 'bytes'),
        ('Prometheus samples ingested per second', 'rate(prometheus_tsdb_head_samples_appended_total[5m])', 'ops'),
        ('Prometheus persistent block storage', 'prometheus_tsdb_storage_blocks_bytes', 'bytes'),
    ],
}


def build():
    dest = ROOT / 'grafana/dashboards'
    dest.mkdir(parents=True, exist_ok=True)
    for name, entries in DASHBOARDS.items():
        dashboard = {'uid': name, 'title': name.replace('-', ' ').title(), 'schemaVersion': 39,
                     'version': 1, 'editable': False, 'timezone': 'America/New_York', 'refresh': '1m',
                     'time': {'from': 'now-6h', 'to': 'now'}, 'tags': ['openshift', 'managed'],
                     'panels': [panel(title, expr, i, unit, 'Missing series means unavailable telemetry, not zero usage. NFS directory PVCs may not report capacity or enforce quotas.') for i, (title, expr, unit) in enumerate(entries)]}
        (dest / (name + '.json')).write_text(json.dumps(dashboard, indent=2) + '\n')


if __name__ == '__main__':
    build()
