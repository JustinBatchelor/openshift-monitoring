#!/usr/bin/env python3
"""Offline validation of rendered Kubernetes resources and dashboard sources."""
import json
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['helm', 'lint', str(ROOT / 'grafana')], check=True)
rendered = subprocess.check_output(['helm', 'template', 'cluster-grafana', str(ROOT / 'grafana'), '--namespace', 'observability'], text=True)
docs = list(yaml.safe_load_all(rendered))
for obj in docs:
    assert obj.get('apiVersion') and obj.get('kind') and obj.get('metadata', {}).get('name')
    if obj['kind'] == 'Secret':
        assert not obj.get('data') and not obj.get('stringData'), 'Credential must not be rendered from source'
    if obj['kind'] == 'PersistentVolumeClaim':
        assert obj['spec']['storageClassName'] == 'truenas-monitoring-iscsi'
        assert obj['metadata']['annotations']['helm.sh/resource-policy'] == 'keep'
for path in (ROOT / 'grafana/dashboards').glob('*.json'):
    obj = json.loads(path.read_text())
    assert obj['refresh'] == '1m'
    assert obj['panels']
    for panel in obj['panels']:
        assert panel['fieldConfig']['defaults']['noValue'] == 'No metrics'
        assert 'or vector(0)' not in panel['targets'][0]['expr']
assert len(list((ROOT / 'grafana/dashboards').glob('*.json'))) == 3
print('Validated', len(docs), 'Kubernetes resources and 3 dashboards.')
