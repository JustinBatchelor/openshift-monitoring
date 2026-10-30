#!/usr/bin/env python3
"""Send bounded acceptance alerts only after notification receivers are configured."""
import argparse
import base64
import datetime
import json

import yaml

from monitoring import ROOT, get
from verify_live import local_api


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resolve', action='store_true')
    args = p.parse_args()
    secret = get('secret', 'alertmanager-main', 'openshift-monitoring')
    config = yaml.safe_load(base64.b64decode(secret['data']['alertmanager.yaml']))
    names = {r['name'] for r in config['receivers'] if r.get('slack_configs')}
    if not {'monitoring-critical', 'monitoring-warnings'} <= names:
        raise SystemExit('Configure Slack receivers before sending acceptance alerts')
    state = ROOT / '.state' / 'notification-test.json'
    now = datetime.datetime.now(datetime.timezone.utc)
    if args.resolve:
        alerts = json.loads(state.read_text())
        for alert in alerts:
            alert['endsAt'] = now.isoformat()
    else:
        alerts = [{'labels': {'alertname': 'MonitoringAcceptance' + level.title(), 'severity': level,
                              'cluster': 'sno', 'namespace': 'monitoring-acceptance'},
                   'annotations': {'summary': 'Monitoring delivery acceptance test',
                                   'description': 'Synthetic test; no production fault. Expires automatically in 10 minutes.'},
                   'startsAt': now.isoformat(), 'endsAt': (now + datetime.timedelta(minutes=10)).isoformat()}
                  for level in ['critical', 'warning']]
        state.parent.mkdir(mode=0o700, exist_ok=True)
        state.write_text(json.dumps(alerts))
        state.chmod(0o600)
    local_api('alertmanager-main', 9093, '/api/v2/alerts', alerts, 'POST')
    print('Acceptance alerts ' + ('resolved.' if args.resolve else 'sent. Confirm separate Slack channels and daytime phone delivery.'))
