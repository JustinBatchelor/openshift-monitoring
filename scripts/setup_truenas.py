#!/usr/bin/env python3
"""Configure only the additional iSCSI service/portal and CSI credential Secret."""
import argparse
import base64
from pathlib import Path

from monitoring import backup, get, write_object
from truenas_preflight import TrueNAS, preflight


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key-file', required=True, type=Path)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    client = TrueNAS(args.key_file)
    try:
        preflight(client)
        before = {'shares': client.call('sharing.nfs.query'), 'iscsi': client.call('service.query', [[['service', '=', 'iscsitarget']]]), 'portals': client.call('iscsi.portal.query')}
        if args.apply:
            backup(before, 'truenas-service')
            if not before['portals']:
                # TrueNAS only offers wildcard portal addresses when its NIC uses DHCP.
                client.call('iscsi.portal.create', [{'comment': 'OpenShift monitoring CSI; DHCP interface', 'listen': [{'ip': '0.0.0.0'}]}])
            service = before['iscsi'][0]
            if not service['enable']:
                client.call('service.update', [service['id'], {'enable': True}])
            if service['state'] != 'RUNNING':
                client.call('service.start', ['iscsitarget'])
            old = get('secret', 'truenas-api-credentials', 'truenas-csi')
            metadata = old['metadata'] if old else {'name': 'truenas-api-credentials', 'namespace': 'truenas-csi'}
            obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': metadata, 'type': 'Opaque', 'data': {'api-key': base64.b64encode(args.key_file.read_bytes().strip()).decode()}}
            write_object(obj, old)
            if client.call('sharing.nfs.query') != before['shares']:
                raise RuntimeError('NFS export drift detected; stop and investigate')
            print('iSCSI service and CSI credential configured; existing NFS exports unchanged.')
        else:
            print('TrueNAS prerequisites passed. No configuration changed.')
    finally:
        client.close()
