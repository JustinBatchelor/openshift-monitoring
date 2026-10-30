# OpenShift monitoring

Use the existing OpenShift Prometheus/Alertmanager stack. Do not install a second
Prometheus or modify operator-owned StatefulSets. Keep credentials and backups
in ignored `.secrets/` and `.state/`, mode 0600. Do not print their contents.

Run `.venv/bin/python -m unittest discover -s tests` and
`.venv/bin/python scripts/validate.py` before publishing. Live changes require
the storage gate documented in README.md. Do not change the default storage
class or existing application volumes. Never delete retained data as cleanup.

Record actual deployment and test results in STATUS.md; never equate successful
rendering or a dry run with a successful live rollout.
