"""Run the s3 checks of the state steps against an S3-compatible store without cloud access."""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / '.ai-rulez/skills/infra/references/steps.yaml'


def check_script(step_id: str) -> str:
    """Return the literal `check: |` body of one step."""
    block = MANIFEST.read_text().split(f'\n  - id: {step_id}\n', 1)[1].split('\n  - id: ', 1)[0]
    body = block.split('\n    check: |\n', 1)[1]
    lines = []
    for line in body.split('\n'):
        if line and not line.startswith('      '):
            break
        lines.append(line)
    return textwrap.dedent('\n'.join(lines))


def run(script: str, env: dict[str, str], stubs: str,
        cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['bash', '-c', stubs + script], capture_output=True, text=True,
                          env={**os.environ, **env}, cwd=cwd)


DECISIONS = (
    '<!-- infra:decisions start -->\n\n| Decision | Choice | Status | Rationale |\n|---|---|---|---|\n'
    '| State history | {choice} | {status} | R2 has no versioning |\n\n'
    '<!-- infra:decisions end -->\n'
)


@unittest.skipUnless(os.name == 'posix', 'checks require a POSIX shell')
class StateBucketTests(unittest.TestCase):
    ENV = {'STATE_BACKEND': 's3', 'STATE_BUCKET': 'b', 'STATE_REGION': 'auto',
           'STATE_LOCK_TABLE': '', 'STATE_ENDPOINT': 'https://x.r2.cloudflarestorage.com'}
    STUB = ('aws() { printf "%s\\n" "$*" >> "$AWS_LOG"; '
            'case "$*" in *get-bucket-versioning*) printf "%s\\n" "$AWS_VERSIONING"; return 0 ;; '
            '*get-bucket-policy*) printf "%s\\n" "$AWS_POLICY"; return "${AWS_POLICY_STATUS:-0}" ;; esac; '
            'return "${AWS_STATUS:-0}"; }\n')

    def run_check(self, extra: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'aws.log'
            status = extra.pop('DECISION', 'locked')
            choice = extra.pop('CHOICE', 'no-versioning')
            if status != 'absent':
                (Path(tmp) / 'README.md').write_text(DECISIONS.format(status=status, choice=choice))
            result = run(check_script('state-bucket'),
                         {**self.ENV, **extra, 'AWS_LOG': str(log)}, self.STUB, cwd=Path(tmp))
            return result, log.read_text() if log.exists() else ''

    def test_endpoint_needs_only_the_bucket_to_exist(self) -> None:
        result, calls = self.run_check({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.strip().splitlines(),
                         ['s3api head-bucket --endpoint-url https://x.r2.cloudflarestorage.com --region auto --bucket b'])

    def test_r2_requires_the_locked_state_history_decision(self) -> None:
        for decision in ('proposed', 'absent'):
            with self.subTest(decision=decision):
                result, _ = self.run_check({'DECISION': decision})
                self.assertEqual(result.returncode, 1)
        result, _ = self.run_check({'CHOICE': 'versioning'})
        self.assertEqual(result.returncode, 1)

    def test_endpoint_fails_when_the_bucket_is_missing(self) -> None:
        result, _ = self.run_check({'AWS_STATUS': '1'})
        self.assertEqual(result.returncode, 1)

    def test_other_stores_still_require_versioning(self) -> None:
        minio = {'STATE_ENDPOINT': 'http://minio.example:9000',
                 'AWS_POLICY': 'An error occurred (NoSuchBucketPolicy)', 'AWS_POLICY_STATUS': '254'}
        result, calls = self.run_check({**minio, 'AWS_VERSIONING': 'Enabled'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('get-bucket-versioning --endpoint-url http://minio.example:9000 --region auto', calls)
        result, _ = self.run_check({**minio, 'AWS_VERSIONING': 'None'})
        self.assertEqual(result.returncode, 1)

    def test_other_stores_must_not_allow_anonymous_access(self) -> None:
        minio = {'STATE_ENDPOINT': 'http://minio.example:9000', 'AWS_VERSIONING': 'Enabled'}
        public = '{"Statement":[{"Effect":"Allow","Principal":{"AWS":["*"]},"Action":"s3:GetObject"}]}'
        scoped = '{"Statement":[{"Effect":"Allow","Principal":{"AWS":["arn:aws:iam::1:root"]},"Action":"s3:*"}]}'
        for policy, status, error, expected in (
            (public, '0', '', 1),
            ('{"Statement":[{"Principal":"*"}]}', '0', '', 1),
            ('{"Statement":[{"Effect":"Allow","Principal":{"AWS":"*","Service":"x"},"Action":"s3:*"}]}', '0', '', 1),
            ('{"Statement":[{"Effect":"Allow","NotPrincipal":{"AWS":"arn:aws:iam::1:root"},"Action":"s3:*"}]}', '0', '', 1),
            ('{"Statement":{"Effect":"Allow","Principal":"*","Action":"s3:GetObject"}}', '0', '', 1),
            ('not json', '0', '', 1),
            ('{"Statement":[{"Effect":"Deny","Principal":"*","Action":"s3:*"}]}', '0', '', 0),
            (scoped, '0', '', 0),
            ('An error occurred (NoSuchBucketPolicy)', '254', '', 0),
            ('An error occurred (AccessDenied)', '254', '', 1),
        ):
            with self.subTest(policy=policy):
                result, _ = self.run_check({**minio, 'AWS_POLICY': policy, 'AWS_POLICY_STATUS': status})
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_aws_s3_still_requires_a_lock_table(self) -> None:
        result, calls = self.run_check({'STATE_ENDPOINT': ''})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, '')


@unittest.skipUnless(os.name == 'posix', 'checks require a POSIX shell')
class BackendIdentityTests(unittest.TestCase):
    STUB = textwrap.dedent('''\
        gh() {
          case "$*" in
            *"--env production"*) printf '%s\\n' $ENV_SECRETS ;;
            *) printf '%s\\n' $REPO_SECRETS ;;
          esac
        }
    ''')
    ENV = {'STATE_BACKEND': 's3', 'REPO': 'o/r', 'STATE_ENDPOINT': 'https://x.example'}
    KEYS = 'STATE_ACCESS_KEY_ID STATE_SECRET_ACCESS_KEY'

    def status(self, repo: str, env: str, endpoint: str = 'https://x.example') -> int:
        return run(check_script('backend-identity'),
                   {**self.ENV, 'STATE_ENDPOINT': endpoint, 'REPO_SECRETS': repo,
                    'ENV_SECRETS': env}, self.STUB).returncode

    def test_endpoint_requires_both_keys_at_both_scopes(self) -> None:
        self.assertEqual(self.status(self.KEYS, self.KEYS), 0)
        self.assertEqual(self.status(self.KEYS, 'STATE_ACCESS_KEY_ID'), 1)
        self.assertEqual(self.status('STATE_SECRET_ACCESS_KEY', self.KEYS), 1)

    def test_endpoint_does_not_accept_a_role_arn(self) -> None:
        self.assertEqual(self.status('AWS_ROLE_ARN', 'AWS_ROLE_ARN'), 1)

    def test_aws_s3_still_requires_the_role_arn(self) -> None:
        self.assertEqual(self.status('AWS_ROLE_ARN', 'AWS_ROLE_ARN', endpoint=''), 0)
        self.assertEqual(self.status(self.KEYS, self.KEYS, endpoint=''), 1)


@unittest.skipUnless(os.name == 'posix', 'checks require a POSIX shell')
class BackendConfigTests(unittest.TestCase):
    ENDPOINT = 'https://x.r2.cloudflarestorage.com'
    BLOCK = '''terraform {
  backend "s3" {
    bucket = "b"
    key    = "terraform/state/cloudflare/terraform.tfstate"
    region = "auto"

    endpoints = {
      s3 = "https://x.r2.cloudflarestorage.com"
    }
    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
'''

    def status(self, text: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            leaf = Path(tmp) / 'terraform/cloudflare'
            leaf.mkdir(parents=True)
            (leaf / 'backend.tf').write_text(text)
            env = {'STATE_BACKEND': 's3', 'STATE_BUCKET': 'b', 'STATE_PREFIX': 'terraform/state',
                   'STATE_ENDPOINT': self.ENDPOINT, 'INFRA_REFERENCES': '/nonexistent',
                   'OBJECT_STORAGE_BOOTSTRAP_LEAVES': '["cloudflare"]'}
            # The state-transfer check is covered elsewhere; stub the `sh` it runs through.
            return run(check_script('backend-config'), env, 'sh() { return 0; }\n', cwd=Path(tmp)).returncode

    def test_complete_endpoint_stanza_passes(self) -> None:
        self.assertEqual(self.status(self.BLOCK), 0)

    def test_inline_endpoint_map_is_accepted(self) -> None:
        inline = self.BLOCK.replace(f'    endpoints = {{\n      s3 = "{self.ENDPOINT}"\n    }}\n',
                                    f'    endpoints = {{ s3 = "{self.ENDPOINT}" }}\n')
        self.assertNotEqual(inline, self.BLOCK)
        self.assertEqual(self.status(inline), 0)

    def test_endpoint_outside_the_backend_block_does_not_count(self) -> None:
        broken = self.BLOCK.replace(f's3 = "{self.ENDPOINT}"', 's3 = "https://s3.amazonaws.com"')
        self.assertEqual(self.status(broken + f'# {self.ENDPOINT}\nlocals {{ e = "{self.ENDPOINT}" }}\n'), 1)

    def test_leftover_dynamodb_table_or_false_flag_fails(self) -> None:
        self.assertEqual(self.status(self.BLOCK.replace('    region = "auto"\n',
                                                         '    region = "auto"\n    dynamodb_table = "locks"\n')), 1)
        self.assertEqual(self.status(self.BLOCK.replace('use_path_style              = true',
                                                         'use_path_style              = false')), 1)


if __name__ == '__main__':
    unittest.main()
