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


def run(script: str, env: dict[str, str], stubs: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['bash', '-c', stubs + script], capture_output=True, text=True,
                          env={**os.environ, **env})


@unittest.skipUnless(os.name == 'posix', 'checks require a POSIX shell')
class StateBucketTests(unittest.TestCase):
    ENV = {'STATE_BACKEND': 's3', 'STATE_BUCKET': 'b', 'STATE_REGION': 'auto',
           'STATE_LOCK_TABLE': '', 'STATE_ENDPOINT': 'https://x.r2.cloudflarestorage.com'}
    STUB = 'aws() { printf "%s\\n" "$*" >> "$AWS_LOG"; return "${AWS_STATUS:-0}"; }\n'

    def run_check(self, extra: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'aws.log'
            result = run(check_script('state-bucket'),
                         {**self.ENV, **extra, 'AWS_LOG': str(log)}, self.STUB)
            return result, log.read_text() if log.exists() else ''

    def test_endpoint_needs_only_the_bucket_to_exist(self) -> None:
        result, calls = self.run_check({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.strip().splitlines(),
                         ['s3api head-bucket --endpoint-url https://x.r2.cloudflarestorage.com --bucket b'])

    def test_endpoint_fails_when_the_bucket_is_missing(self) -> None:
        result, _ = self.run_check({'AWS_STATUS': '1'})
        self.assertEqual(result.returncode, 1)

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
    KEYS = 'AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY'

    def status(self, repo: str, env: str, endpoint: str = 'https://x.example') -> int:
        return run(check_script('backend-identity'),
                   {**self.ENV, 'STATE_ENDPOINT': endpoint, 'REPO_SECRETS': repo,
                    'ENV_SECRETS': env}, self.STUB).returncode

    def test_endpoint_requires_both_keys_at_both_scopes(self) -> None:
        self.assertEqual(self.status(self.KEYS, self.KEYS), 0)
        self.assertEqual(self.status(self.KEYS, 'AWS_ACCESS_KEY_ID'), 1)
        self.assertEqual(self.status('AWS_SECRET_ACCESS_KEY', self.KEYS), 1)

    def test_endpoint_does_not_accept_a_role_arn(self) -> None:
        self.assertEqual(self.status('AWS_ROLE_ARN', 'AWS_ROLE_ARN'), 1)

    def test_aws_s3_still_requires_the_role_arn(self) -> None:
        self.assertEqual(self.status('AWS_ROLE_ARN', 'AWS_ROLE_ARN', endpoint=''), 0)
        self.assertEqual(self.status(self.KEYS, self.KEYS, endpoint=''), 1)


if __name__ == '__main__':
    unittest.main()
