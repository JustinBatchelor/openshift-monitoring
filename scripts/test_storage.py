#!/usr/bin/env python3
"""Live acceptance test on isolated disposable resources; retains the test PV."""
import datetime
import json
import subprocess
import time
from pathlib import Path

from monitoring import ROOT, backup, oc

STORAGE = ROOT.parent / 'openshift-storage' / 'truenas-csi'
NS = 'monitoring-storage-test'
CLAIM = 'monitoring-iscsi-test'


def wait_for(fn, description, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            print(description + ' passed.', flush=True)
            return
        time.sleep(5)
    raise RuntimeError('Timed out: ' + description)


def get(kind, name):
    return json.loads(oc('get', kind, name, '-n', NS, '-o', 'json'))


def rollout():
    oc('rollout', 'status', 'deployment/monitoring-storage-test', '-n', NS, '--timeout=10m')


def marker():
    return oc('exec', '-n', NS, 'deployment/monitoring-storage-test', '--', 'cat', '/data/persistence-marker').strip()


def main():
    sc = json.loads(oc('get', 'storageclass', 'truenas-monitoring-iscsi', '-o', 'json'))
    if sc['provisioner'] != 'csi.truenas.io' or sc['reclaimPolicy'] != 'Retain':
        raise RuntimeError('Unexpected storage class; refusing test')
    for name in ['namespace.yaml', 'pvc.yaml', 'consumer.yaml']:
        oc('apply', '-f', str(STORAGE / 'tests' / name))
    wait_for(lambda: get('pvc', CLAIM).get('status', {}).get('phase') == 'Bound', 'PVC provisioning')
    rollout()
    before = marker()
    if not before:
        raise RuntimeError('Empty persistence marker')
    oc('rollout', 'restart', 'deployment/monitoring-storage-test', '-n', NS)
    rollout()
    if marker() != before:
        raise RuntimeError('Marker changed after pod replacement')
    print('Pod replacement persistence passed.', flush=True)
    oc('patch', 'pvc', CLAIM, '-n', NS, '--type=merge', '--patch-file=/dev/stdin',
       payload=json.dumps({'spec': {'resources': {'requests': {'storage': '2Gi'}}}}))
    wait_for(lambda: get('pvc', CLAIM).get('status', {}).get('allocatedResources', {}).get('storage') == '2Gi', 'Backend expansion')
    # This driver can require a remount to complete node filesystem expansion.
    oc('rollout', 'restart', 'deployment/monitoring-storage-test', '-n', NS)
    rollout()
    wait_for(lambda: get('pvc', CLAIM).get('status', {}).get('capacity', {}).get('storage') == '2Gi', 'PVC expansion')
    capacity = int(oc('exec', '-n', NS, 'deployment/monitoring-storage-test', '--', 'df', '-B1', '--output=size', '/data').splitlines()[-1].strip())
    if capacity < 1500 * 1024**2 or marker() != before:
        raise RuntimeError('Filesystem did not grow or marker changed')
    pv_name = get('pvc', CLAIM)['spec']['volumeName']
    pv = json.loads(oc('get', 'pv', pv_name, '-o', 'json'))
    if pv['spec']['claimRef']['namespace'] != NS or pv['spec']['claimRef']['name'] != CLAIM:
        raise RuntimeError('Test PV ownership mismatch')
    backup(pv, 'retained-storage-test-pv')
    # These exact test resources were created by this test. Data remains retained.
    oc('delete', 'deployment', 'monitoring-storage-test', '-n', NS, '--wait=true', '--timeout=120s')
    wait_for(lambda: not json.loads(oc('get', 'pods', '-n', NS, '-l', 'app=monitoring-storage-test', '-o', 'json'))['items'], 'Test pod termination', 120)
    oc('delete', 'pvc', CLAIM, '-n', NS, '--wait=true', '--timeout=120s')
    wait_for(lambda: json.loads(oc('get', 'pv', pv_name, '-o', 'json')).get('status', {}).get('phase') == 'Released', 'PV retention')
    cluster = json.loads(oc('get', 'clusterversion', 'version', '-o', 'json'))
    result = {'clusterID': cluster['spec']['clusterID'], 'storageClassUID': sc['metadata']['uid'],
              'testedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'retainedTestPV': pv_name,
              'checks': ['provisioning', 'pod-replacement', 'filesystem-expansion', 'retained-pv']}
    path = ROOT / '.state/storage-validated.json'
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')
    path.chmod(0o600)
    print('Storage gate passed. Retained test PV:', pv_name, flush=True)


if __name__ == '__main__':
    main()
