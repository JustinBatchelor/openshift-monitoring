import copy
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monitoring import alert_config, storage_config, checked_url

SETTINGS = yaml.safe_load((Path(__file__).resolve().parents[1] / 'config/monitoring.yaml').read_text())
URL = 'https://hooks.slack.com/services/test/test/test'
PING = 'https://hc-ping.com/00000000-0000-0000-0000-000000000000'


class MonitoringMergeTest(unittest.TestCase):
    def test_storage_preserves_unrelated_configuration_and_single_replica(self):
        original = {'enableUserWorkload': False, 'prometheusK8s': {'replicas': 1, 'resources': {'requests': {'memory': '3Gi'}}}, 'alertmanagerMain': {'nodeSelector': {'kubernetes.io/hostname': 'sno'}}}
        previous = copy.deepcopy(original)
        result = storage_config(original, SETTINGS)
        self.assertEqual(original, previous)
        self.assertEqual(result['prometheusK8s']['replicas'], 1)
        self.assertEqual(result['prometheusK8s']['resources'], original['prometheusK8s']['resources'])
        self.assertEqual(result['alertmanagerMain']['nodeSelector'], original['alertmanagerMain']['nodeSelector'])
        self.assertFalse(result['enableUserWorkload'])
        self.assertEqual(result['prometheusK8s']['volumeClaimTemplate']['spec']['resources']['requests']['storage'], '50Gi')

    def test_refuses_implicit_storage_migration(self):
        with self.assertRaises(ValueError):
            storage_config({'prometheusK8s': {'volumeClaimTemplate': {'spec': {'storageClassName': 'existing'}}}}, SETTINGS)

    def test_routes_preserve_inhibition_and_watchdog_precedence(self):
        old = {'route': {'receiver': 'Default', 'routes': [{'receiver': 'Watchdog', 'matchers': ['alertname="Watchdog"']}]}, 'receivers': [{'name': 'Default'}, {'name': 'Watchdog'}], 'inhibit_rules': [{'source_matchers': ['severity="critical"'], 'target_matchers': ['severity="warning"'], 'equal': ['alertname']}]}
        before = copy.deepcopy(old)
        result = alert_config(old, SETTINGS, URL, URL, PING)
        self.assertEqual(old, before)
        self.assertEqual(result['inhibit_rules'], old['inhibit_rules'])
        self.assertEqual(result['route']['routes'][0]['receiver'], 'monitoring-watchdog')
        self.assertEqual(result['route']['routes'][-1], old['route']['routes'][0])
        self.assertEqual(result, alert_config(result, SETTINGS, URL, URL, PING))
        heartbeat = next(r for r in result['receivers'] if r['name'] == 'monitoring-watchdog')
        self.assertFalse(heartbeat['webhook_configs'][0]['send_resolved'])

    def test_only_expected_https_notification_endpoints(self):
        for url in ['http://hooks.slack.com/services/a', 'https://hooks.slack.com.evil.test/services/a', 'https://user:pass@hooks.slack.com/services/a']:
            with self.assertRaises(ValueError):
                checked_url(url, 'hooks.slack.com', '/services/')


if __name__ == '__main__':
    unittest.main()
