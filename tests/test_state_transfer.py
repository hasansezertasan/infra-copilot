"""Committed backend history must not bypass the HUMAN frozen-transfer gate."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REFERENCES = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra-copilot/references'


@unittest.skipUnless(os.name == 'posix' and shutil.which('jq'), 'POSIX shell and jq required')
class StateTransferTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.checkout = Path(temporary.name)
        self.execute_git('init', '-q')
        (self.checkout / 'terraform/github').mkdir(parents=True)
        (self.checkout / '.infra-copilot').mkdir()
        (self.checkout / '.infra-copilot/config.md').write_text('state_transfers: {}\n')
        self.backend = self.checkout / 'terraform/github/backend.tf'
        self.environment = dict(os.environ)

    def execute_git(self, *arguments: str) -> str:
        result = subprocess.run(['git', *arguments], cwd=self.checkout, capture_output=True,
                                text=True, check=True)
        return result.stdout.strip()

    def commit_files(self) -> None:
        self.execute_git('add', 'terraform', '.infra-copilot')
        self.execute_git('-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                         'commit', '-qm', 'cutover fixture')

    def check_transfer(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(['sh', str(REFERENCES / 'checks/state-transfer.sh'), 'github'],
                              cwd=self.checkout, env=self.environment, capture_output=True, text=True)

    def prepare_migration(self) -> dict[str, object]:
        self.backend.write_text('terraform { cloud { organization = "acme" } }\n')
        self.commit_files()
        self.backend.write_text('terraform { backend "gcs" { bucket = "acme-state" } }\n')
        self.commit_files()
        return {'source_backend': 'hcp', 'workspace_id': 'ws-public123', 'serial': 42,
                'lineage': 'public-lineage', 'state_sha256': 'a' * 64,
                'hcp_locked_before_pull': True, 'destination_verified': True,
                'backend_blob': self.execute_git('hash-object', str(self.backend)),
                'verified_at': '2025-01-02T00:00:00Z'}

    def test_fresh_leaf_needs_no_migration_record(self) -> None:
        self.backend.write_text('terraform { backend "gcs" { bucket = "acme-state" } }\n')
        self.commit_files()
        self.assertEqual(self.check_transfer().returncode, 0)

    def test_backend_only_cutover_cannot_skip_transfer_evidence(self) -> None:
        self.prepare_migration()
        result = self.check_transfer()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('record the frozen, verified HUMAN HCP transfer', result.stderr)

    def test_current_record_passes_but_incomplete_or_retargeted_records_fail(self) -> None:
        transfer = self.prepare_migration()
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        self.assertEqual(self.check_transfer().returncode, 0)
        for invalid_fields in ({'hcp_locked_before_pull': False}, {'destination_verified': False},
                               {'backend_blob': 'old-backend'}, {'verified_at': '2999-01-02T00:00:00Z'},
                               {'state_sha256': ''}, {'serial': -1}):
            with self.subTest(fields=invalid_fields):
                self.environment['STATE_TRANSFERS'] = json.dumps({'github': {**transfer, **invalid_fields}})
                self.assertEqual(self.check_transfer().returncode, 1)
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        self.backend.write_text('terraform { backend "gcs" { bucket = "another-destination" } }\n')
        self.commit_files()
        self.assertEqual(self.check_transfer().returncode, 1)

    def test_backend_in_an_unhashed_file_cannot_use_an_unchanged_attestation(self) -> None:
        transfer = self.prepare_migration()
        (self.checkout / 'terraform/github/versions.tf').write_text(self.backend.read_text())
        self.backend.write_text('# backend moved elsewhere\n')
        self.commit_files()
        transfer['backend_blob'] = self.execute_git('hash-object', str(self.backend))
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        self.assertEqual(self.check_transfer().returncode, 1)

    def test_json_backend_outside_the_reviewed_file_is_rejected(self) -> None:
        transfer = self.prepare_migration()
        (self.checkout / 'terraform/github/override.tf.json').write_text(json.dumps({
            'terraform': {'backend': {'gcs': {'bucket': 'another-destination'}}}}))
        self.commit_files()
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        self.assertEqual(self.check_transfer().returncode, 1)

    def test_resource_json_does_not_invalidate_the_reviewed_backend(self) -> None:
        transfer = self.prepare_migration()
        (self.checkout / 'terraform/github/resources.tf.json').write_text(json.dumps({
            'resource': {'null_resource': {'example': {}}}}))
        self.commit_files()
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        self.assertEqual(self.check_transfer().returncode, 0)

    def test_backend_declared_outside_the_hashed_file_fails(self) -> None:
        transfer = self.prepare_migration()
        self.environment['STATE_TRANSFERS'] = json.dumps({'github': transfer})
        leaf = self.checkout / 'terraform/github'
        for name, text in (
                ('versions.tf', 'terraform {\n  backend "gcs" { bucket = "another-destination" }\n}\n'),
                ('backend_override.tf', 'terraform {\n  backend "gcs" {\n    prefix = "elsewhere"\n  }\n}\n'),
                ('versions.tf', 'terraform {\n  cloud {\n  }\n}\n'),
                ('main.tf.json', '{"terraform": {"backend": {"gcs": {"bucket": "another-destination"}}}}\n')):
            with self.subTest(file=name):
                (leaf / name).write_text(text)
                result = self.check_transfer()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f'terraform/github/{name}', result.stderr)
                (leaf / name).unlink()
        (leaf / 'versions.tf').write_text('# backend "gcs" lives in backend.tf\nterraform {}\n')
        self.assertEqual(self.check_transfer().returncode, 0)
        self.backend.write_text('terraform {}\n')
        self.commit_files()
        self.environment['STATE_TRANSFERS'] = json.dumps(
            {'github': {**transfer, 'backend_blob': self.execute_git('hash-object', str(self.backend))}})
        self.assertEqual(self.check_transfer().returncode, 1)
