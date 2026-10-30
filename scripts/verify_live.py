#!/usr/bin/env python3
"""Verify dashboards and, explicitly, pod-replacement persistence on this cluster."""
import argparse
import base64
import datetime
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from monitoring import get, oc, backup

BASE = 'https://grafana.apps.sno.batchelor.live'


def grafana(path, auth=None, payload=None):
    headers = {}
    if auth:
        headers['Authorization'] = 'Basic ' + auth
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(BASE + path, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None,
                                     method='PUT' if payload is not None else 'GET')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def local_api(component, port, path, payload=None, method=None):
    args = ['exec']
    if payload is not None:
        args += ['-i']
    args += ['-n', 'openshift-monitoring', component + '-0', '-c', 'prometheus' if component == 'prometheus-k8s' else 'alertmanager', '--', 'curl', '-fsS']
    if method:
        args += ['-X', method]
    if payload is not None:
        args += ['-H', 'Content-Type: application/json', '--data-binary', '@-']
    args += [f'http://localhost:{port}' + path]
    response = oc(*args, payload=json.dumps(payload) if payload is not None else None)
    return json.loads(response) if response else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--restart-pods', action='store_true', help='Disruptively verify one component at a time')
    args = p.parse_args()
    creds = get('secret', 'grafana-admin', 'observability')['data']
    user = base64.b64decode(creds['username']).decode()
    password = base64.b64decode(creds['password']).decode()
    auth = base64.b64encode((user + ':' + password).encode()).decode()
    try:
        grafana('/api/search')
        raise RuntimeError('Anonymous dashboard access unexpectedly allowed')
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise
    print('Unauthenticated API rejected with 401; HTTPS verified.', flush=True)
    health = grafana('/api/datasources/uid/openshift/health', auth)
    if health.get('status') != 'OK':
        raise RuntimeError('Thanos datasource health check failed')
    dashboards = grafana('/api/search?type=dash-db', auth)
    uids = {d['uid'] for d in dashboards}
    if not {'cluster-health', 'workload-resources', 'capacity-storage'} <= uids:
        raise RuntimeError('Provisioned dashboards missing')
    print('Thanos datasource and all three dashboards verified.', flush=True)
    if not args.restart_pods:
        return
    # Verify actual stored samples at an earlier, fixed evaluation time.
    timestamp = time.time() - 15
    query = '/api/v1/query?' + urllib.parse.urlencode({'query': 'sum(up)', 'time': timestamp})
    before = local_api('prometheus-k8s', 9090, query)
    if not before['data']['result']:
        raise RuntimeError('Wait for scrape data before testing Prometheus persistence')
    backup({'timestamp': timestamp, 'query': 'sum(up)', 'result': before['data']['result']}, 'prometheus-persistence-evidence')
    oc('delete', 'pod', 'prometheus-k8s-0', '-n', 'openshift-monitoring', '--wait=true', '--timeout=120s')
    oc('wait', 'pod/prometheus-k8s-0', '-n', 'openshift-monitoring', '--for=condition=Ready', '--timeout=10m')
    after = local_api('prometheus-k8s', 9090, query)
    if before['data']['result'] != after['data']['result']:
        raise RuntimeError('Historical Prometheus sample changed after pod replacement')
    print('Prometheus historical sample survived pod replacement.', flush=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    silence = {'matchers': [{'name': 'alertname', 'value': 'MonitoringAcceptanceOnly', 'isRegex': False, 'isEqual': True}],
               'startsAt': now.isoformat(), 'endsAt': (now + datetime.timedelta(hours=1)).isoformat(),
               'createdBy': 'monitoring-acceptance', 'comment': 'Persistence test; matches no production alert'}
    sid = local_api('alertmanager-main', 9093, '/api/v2/silences', silence, 'POST')['silenceID']
    try:
        oc('delete', 'pod', 'alertmanager-main-0', '-n', 'openshift-monitoring', '--wait=true', '--timeout=120s')
        oc('wait', 'pod/alertmanager-main-0', '-n', 'openshift-monitoring', '--for=condition=Ready', '--timeout=10m')
        restored = local_api('alertmanager-main', 9093, '/api/v2/silence/' + sid)
        if restored['id'] != sid or restored['comment'] != silence['comment']:
            raise RuntimeError('Alertmanager silence did not survive pod replacement')
        print('Alertmanager silence survived pod replacement.', flush=True)
    finally:
        local_api('alertmanager-main', 9093, '/api/v2/silence/' + sid, method='DELETE')
    preferences = grafana('/api/org/preferences', auth)
    preferences.update(homeDashboardUID='cluster-health', timezone='America/New_York')
    grafana('/api/org/preferences', auth, preferences)
    oc('rollout', 'restart', 'deployment/grafana', '-n', 'observability')
    oc('rollout', 'status', 'deployment/grafana', '-n', 'observability', '--timeout=10m')
    restored = grafana('/api/org/preferences', auth)
    if restored.get('homeDashboardUID') != 'cluster-health':
        raise RuntimeError('Grafana preferences did not survive restart')
    if grafana('/api/datasources/uid/openshift/health', auth).get('status') != 'OK':
        raise RuntimeError('Datasource failed after restart')
    print('Grafana database preferences and datasource survived pod replacement.', flush=True)


if __name__ == '__main__':
    main()
