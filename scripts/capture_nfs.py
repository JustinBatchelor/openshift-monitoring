#!/usr/bin/env python3
"""Capture or compare current NFS access settings; never writes to TrueNAS."""
import argparse
import json
from pathlib import Path

from truenas_preflight import TrueNAS


def capture(client):
    shares = client.call('sharing.nfs.query')
    result = {'exports': [], 'nfsService': client.call('nfs.config')}
    for share in sorted(shares, key=lambda s: s['path']):
        entry = {'export': share, 'rootACL': client.call('filesystem.getacl', [share['path']])}
        dataset = share['path'].removeprefix('/mnt/')
        ds = client.call('pool.dataset.query', [[['id', '=', dataset]]])
        if ds:
            entry['datasetAccessProperties'] = {k: ds[0].get(k) for k in ['acltype', 'aclmode', 'aclinherit', 'readonly', 'casesensitivity', 'sync']}
        result['exports'].append(entry)
    return result


def canonical(value):
    # TrueNAS reports operational state (locked, mountpoint) alongside policy.
    # Comparison intentionally includes the entire returned policy/ACL snapshot.
    return json.dumps(value, sort_keys=True, indent=2)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key-file', required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--compare', type=Path)
    args = p.parse_args()
    c = TrueNAS(args.key_file)
    try:
        snapshot = capture(c)
    finally:
        c.close()
    if args.compare:
        if canonical(snapshot) != canonical(json.loads(args.compare.read_text())):
            raise SystemExit('NFS configuration/ACL drift detected; review without applying changes')
        print('NFS exports, service configuration, root ACLs, and dataset access settings unchanged.')
    elif args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(canonical(snapshot) + '\n')
        print('Captured', len(snapshot['exports']), 'NFS exports and their access settings.')
    else:
        p.error('Choose --output or --compare; credentials and inventory are not printed')
