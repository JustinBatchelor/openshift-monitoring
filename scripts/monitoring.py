#!/usr/bin/env python3
"""Merge supported monitoring settings, with protected backups and explicit stages."""
import argparse
import base64
import copy
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]


def oc(*args, payload=None, allow_missing=False):
    result = subprocess.run(['oc', *args], input=payload, text=True, capture_output=True)
    if result.returncode:
        if allow_missing and 'NotFound' in result.stderr:
            return None
        # Avoid printing requests or API errors containing credentials.
        raise RuntimeError('oc operation failed: ' + ' '.join(args[:3]))
    return result.stdout


def get(kind, name, namespace):
    value = oc('get', kind, name, '-n', namespace, '-o', 'json', allow_missing=True)
    return json.loads(value) if value else None


def backup(obj, label):
    state = ROOT / '.state'
    state.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = state / (stamp + '-' + label + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(obj, out, indent=2)
    return path


def write_object(obj, old=None, dry_run=False):
    obj = copy.deepcopy(obj)
    obj['metadata'].pop('managedFields', None)
    obj['metadata'].get('annotations', {}).pop('kubectl.kubernetes.io/last-applied-configuration', None)
    obj.pop('status', None)
    action = 'replace' if old else 'create'
    args = [action, '-f', '-']
    if dry_run:
        args += ['--dry-run=server']
    oc(*args, payload=json.dumps(obj))


def storage_config(existing, settings):
    result = copy.deepcopy(existing or {})
    for key, source in [('prometheusK8s', 'prometheus'), ('alertmanagerMain', 'alertmanager')]:
        component = result.setdefault(key, {})
        template = component.setdefault('volumeClaimTemplate', {})
        spec = template.setdefault('spec', {})
        if spec.get('storageClassName') not in (None, settings['storageClass']):
            raise ValueError('Existing storage class differs; a data migration must be planned')
        spec.update(storageClassName=settings['storageClass'], accessModes=['ReadWriteOnce'], volumeMode='Filesystem')
        spec.setdefault('resources', {}).setdefault('requests', {})['storage'] = settings[source]['storage']
    result['prometheusK8s'].update(retention=settings['prometheus']['retention'], retentionSize=settings['prometheus']['retentionSize'])
    return result


def checked_url(value, host, prefix):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname != host or not parsed.path.startswith(prefix):
        raise ValueError('Unexpected notification endpoint host or scheme')
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('Malformed notification endpoint')
    return value


def alert_config(existing, settings, critical, warning, heartbeat):
    critical = checked_url(critical, 'hooks.slack.com', '/services/')
    warning = checked_url(warning, 'hooks.slack.com', '/services/')
    heartbeat = checked_url(heartbeat, 'hc-ping.com', '/')
    result = copy.deepcopy(existing)
    route = result.setdefault('route', {'receiver': 'Default'})
    result.setdefault('receivers', [{'name': 'Default'}])
    managed = {'monitoring-critical', 'monitoring-warnings', 'monitoring-watchdog'}
    # Keep existing routes/inhibitions as fallback, but do not let the default
    # Watchdog discard receiver consume the heartbeat first.
    old_routes = [r for r in route.get('routes', []) if r.get('receiver') not in managed]
    slack = settings['slack']
    common = {'group_by': ['cluster', 'namespace', 'alertname'],
              'group_wait': slack['groupWait'], 'group_interval': slack['groupInterval']}
    route['routes'] = [
        {'matchers': ['alertname="Watchdog"'], 'receiver': 'monitoring-watchdog',
         'group_by': ['alertname'], 'group_wait': '0s', 'group_interval': '1m', 'repeat_interval': '1m'},
        dict(common, matchers=['severity="critical"'], receiver='monitoring-critical', repeat_interval=slack['criticalRepeat']),
        dict(common, matchers=['severity="warning"'], receiver='monitoring-warnings', repeat_interval=slack['warningRepeat']),
        *old_routes,
    ]
    text = ('{{ range .Alerts }}*{{ .Labels.alertname }}* ({{ .Labels.severity }})\n'
            '{{ .Annotations.summary }}\n{{ .Annotations.description }}\n'
            'Namespace: {{ .Labels.namespace }} Node: {{ .Labels.node }} Pod: {{ .Labels.pod }}\n'
            '{{ if .Annotations.runbook_url }}Runbook: {{ .Annotations.runbook_url }}\n{{ end }}'
            '{{ if .Annotations.dashboard_url }}Dashboard: {{ .Annotations.dashboard_url }}\n{{ end }}'
            '{{ end }}\nGrafana: https://grafana.apps.sno.batchelor.live')
    def receiver(name, url, channel):
        return {'name': name, 'slack_configs': [{'api_url': url, 'channel': channel,
                'send_resolved': True, 'title': '[{{ .Status | toUpper }}] sno: {{ .CommonLabels.alertname }}', 'text': text}]}
    result['receivers'] = [r for r in result['receivers'] if r['name'] not in managed] + [
        receiver('monitoring-critical', critical, slack['criticalChannel']),
        receiver('monitoring-warnings', warning, slack['warningChannel']),
        {'name': 'monitoring-watchdog', 'webhook_configs': [{'url': heartbeat, 'send_resolved': False, 'max_alerts': 1}]},
    ]
    return result


def storage_ready():
    gate = ROOT / '.state' / 'storage-validated.json'
    if not gate.exists():
        raise RuntimeError('Storage acceptance test has not passed; run the storage validation runbook first')
    data = json.loads(gate.read_text())
    sc = json.loads(oc('get', 'storageclass', 'truenas-monitoring-iscsi', '-o', 'json'))
    cluster = json.loads(oc('get', 'clusterversion', 'version', '-o', 'json'))
    if data.get('storageClassUID') != sc['metadata']['uid'] or data.get('clusterID') != cluster['spec']['clusterID']:
        raise RuntimeError('Storage validation belongs to a different cluster or storage class')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['storage', 'notifications', 'grafana-admin'])
    parser.add_argument('--apply', action='store_true', help='Apply; otherwise server-side dry run')
    parser.add_argument('--critical-file', type=Path)
    parser.add_argument('--warning-file', type=Path)
    parser.add_argument('--heartbeat-file', type=Path)
    args = parser.parse_args()
    settings = yaml.safe_load((ROOT / 'config/monitoring.yaml').read_text())
    if args.stage == 'storage':
        storage_ready()
        old = get('configmap', 'cluster-monitoring-config', 'openshift-monitoring')
        obj = copy.deepcopy(old) if old else {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'cluster-monitoring-config', 'namespace': 'openshift-monitoring'}}
        data = obj.setdefault('data', {})
        merged = storage_config(yaml.safe_load(data.get('config.yaml', '{}')), settings)
        data['config.yaml'] = yaml.safe_dump(merged, sort_keys=False)
    elif args.stage == 'notifications':
        if not all([args.critical_file, args.warning_file, args.heartbeat_file]):
            parser.error('Notification stage requires all three credential file paths')
        old = get('secret', 'alertmanager-main', 'openshift-monitoring')
        if not old:
            raise RuntimeError('Existing Alertmanager configuration Secret is missing')
        obj = copy.deepcopy(old)
        config = yaml.safe_load(base64.b64decode(old['data']['alertmanager.yaml']))
        merged = alert_config(config, settings, *[p.read_text().strip() for p in [args.critical_file, args.warning_file, args.heartbeat_file]])
        rendered = yaml.safe_dump(merged, sort_keys=False)
        oc('exec', '-i', '-n', 'openshift-monitoring', 'alertmanager-main-0', '-c', 'alertmanager', '--', 'amtool', 'check-config', '/dev/stdin', payload=rendered)
        obj['data']['alertmanager.yaml'] = base64.b64encode(rendered.encode()).decode()
    else:
        old = get('secret', 'grafana-admin', 'observability')
        if old:
            print('Grafana admin Secret already exists; password preserved.')
            return
        obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'grafana-admin', 'namespace': 'observability'}, 'type': 'Opaque', 'stringData': {'username': 'admin', 'password': secrets.token_urlsafe(32)}}
    if args.apply:
        path = backup(old, args.stage)
        print('Protected rollback snapshot:', path)
    write_object(obj, old, dry_run=not args.apply)
    print(args.stage + (' applied.' if args.apply else ' server-side dry run passed.'))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc))
