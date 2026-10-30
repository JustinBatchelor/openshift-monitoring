#!/usr/bin/env python3
"""Read-only TrueNAS prerequisite check. Never prints API credentials."""
import argparse
import json
import re
from pathlib import Path

import websocket


class TrueNAS:
    def __init__(self, key_file, url='wss://truenas.batchelor.live/api/current'):
        self.ws = websocket.create_connection(url, timeout=20)
        self.counter = 0
        key = Path(key_file).read_text().strip()
        if not key or '\n' in key:
            raise ValueError('Expected a file containing only the API key')
        if not self.call('auth.login_with_api_key', [key]):
            raise RuntimeError('TrueNAS authentication failed')

    def call(self, method, params=None):
        self.counter += 1
        ident = self.counter
        self.ws.send(json.dumps({'jsonrpc': '2.0', 'id': ident,
                                 'method': method, 'params': params or []}))
        while True:
            response = json.loads(self.ws.recv())
            if response.get('id') != ident:
                continue
            if response.get('error'):
                # Error objects may echo arguments. Do not print them.
                error = RuntimeError('TrueNAS API method failed: ' + method)
                error.api_error = response['error']
                raise error
            return response.get('result')

    def close(self):
        self.ws.close()


def preflight(client):
    version = client.call('system.version')
    numbers = re.search(r'(\d+)\.(\d+)', version)
    if not numbers or tuple(map(int, numbers.groups())) < (25, 10):
        raise RuntimeError('TrueNAS 25.10+ required; no upgrade will be attempted')
    pools = client.call('pool.query', [[['name', '=', 'main']]])
    if len(pools) != 1 or pools[0].get('status') != 'ONLINE':
        raise RuntimeError('Pool main is missing or not ONLINE')
    datasets = client.call('pool.dataset.query', [[['id', '=', 'main']]])
    available = datasets[0]['available']['parsed']
    if int(available) < 80 * 1024**3:
        raise RuntimeError('Pool main needs at least 80 GiB available for initial provisioning')
    services = client.call('service.query', [[['service', '=', 'iscsitarget']]])
    portals = client.call('iscsi.portal.query')
    initiators = client.call('iscsi.initiator.query')
    return {'version': version, 'pool': 'main', 'pool_status': pools[0]['status'],
            'available_gib': round(int(available) / 1024**3, 1),
            'iscsi_service': [{k: s.get(k) for k in ('id', 'service', 'enable', 'state')} for s in services],
            'portals': [{'id': p['id'], 'listen': p.get('listen')} for p in portals],
            'initiators': [{'id': i['id'], 'initiators': i.get('initiators')} for i in initiators]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', required=True)
    args = parser.parse_args()
    client = None
    try:
        client = TrueNAS(args.key_file)
        print(json.dumps(preflight(client), indent=2))
    except Exception as exc:
        raise SystemExit('Preflight failed (' + type(exc).__name__ + '): ' + str(exc))
    finally:
        if client:
            client.close()
