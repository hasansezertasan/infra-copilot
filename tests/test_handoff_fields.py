"""Run the Handoff-field validator against manifest fixtures.

A HUMAN step may carry structured `cli:` and `ui:` lists and a `check_summary:` beside
its free-text `run:`. The validator accepts or rejects a manifest by those fields alone;
nothing here asserts on how it parses them.
"""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.validate import validate_handoff_fields

REFERENCES = Path('.ai-rulez/skills/infra/references')
CONFIG = """\
   export CF_ACCOUNT_ID=<cloudflare_account_id>
   export GITHUB_ORG=<github_org>
"""
CHECK = "    check: 'true'\n"


def step(body: str, *, actor: str = 'HUMAN', step_id: str = 'sample') -> str:
    return (
        f'  - id: {step_id}\n'
        f'    actor: {actor}\n'
        '    title: Sample\n'
        + textwrap.indent(textwrap.dedent(body), '    ')
        + CHECK
    )


class HandoffFieldTests(unittest.TestCase):
    def errors_for(self, *steps: str) -> list[str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / REFERENCES).mkdir(parents=True)
        (root / REFERENCES / 'steps.yaml').write_text('steps:\n' + '\n'.join(steps))
        (root / REFERENCES / 'config.md').write_text(CONFIG)
        return validate_handoff_fields(root)

    def test_run_text_alone_still_passes(self) -> None:
        self.assertEqual([], self.errors_for(step('run: |\n  Open the dashboard.\n')))

    def test_human_step_with_no_instructions_fails(self) -> None:
        errors = self.errors_for(step('why: nothing to do\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('sample', errors[0])

    def test_agent_step_needs_no_instructions(self) -> None:
        self.assertEqual([], self.errors_for(step('why: agent runs it\n', actor='AGENT')))

    def cli_step(self, command: str) -> str:
        return step(
            'check_summary: The secret exists.\n'
            'cli:\n'
            '  - effect: Stores the secret.\n'
            '    run: |\n'
            + textwrap.indent(command, '      ')
        )

    def test_cli_entry_with_a_summary_passes(self) -> None:
        self.assertEqual([], self.errors_for(self.cli_step('gh secret set TOKEN_NAME\n')))

    def test_converted_step_without_a_check_summary_fails(self) -> None:
        errors = self.errors_for(step(
            'cli:\n  - effect: Does it.\n    run: |\n      gh repo view\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('check_summary', errors[0])

    def test_hidden_prompt_file_redirect_and_read_forms_pass(self) -> None:
        for command in (
            'gh secret set APP_KEY < key.pem\n',
            'gh secret set APP_KEY\n',
            'read -rs value\nprintf %s "$value" | gh secret set APP_KEY\n',
        ):
            with self.subTest(command=command):
                self.assertEqual([], self.errors_for(self.cli_step(command)))

    def test_secret_passed_as_an_argument_fails(self) -> None:
        for command in (
            'gh secret set APP_KEY --body "hunter2"\n',
            'gh secret set APP_KEY -b hunter2\n',
            'wrangler secret put X --value "$API_TOKEN"\n',
            'gh secret set APP_KEY --body="$APP_PRIVATE_KEY"\n',
            'curl -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" https://example.test\n',
        ):
            with self.subTest(command=command):
                errors = self.errors_for(self.cli_step(command))
                self.assertEqual(1, len(errors))
                self.assertIn('secret', errors[0])

    def ui_step(self, url: str = 'https://dash.example.test/$CF_ACCOUNT_ID/r2', fields: str = 'Name | value\n') -> str:
        parts = ['check_summary: The form exists.\n', 'ui:\n']
        if url:
            parts.append(f'  - url: {url}\n')
            parts.append('    fields: |\n')
        else:
            parts.append('  - fields: |\n')
        parts.append(textwrap.indent(fields, '      '))
        return step(''.join(parts))

    def test_complete_ui_entry_passes(self) -> None:
        self.assertEqual([], self.errors_for(self.ui_step(
            fields='Token name | infra\nPermissions | Zone DNS Edit\n',
        )))

    def test_ui_entry_without_a_url_fails(self) -> None:
        errors = self.errors_for(self.ui_step(url=''))
        self.assertEqual(1, len(errors))
        self.assertIn('url', errors[0])

    def test_ui_entry_with_an_empty_field_table_fails(self) -> None:
        errors = self.errors_for(self.ui_step(fields='\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('field', errors[0])

    def test_a_field_row_that_is_not_a_pair_fails(self) -> None:
        errors = self.errors_for(self.ui_step(fields='Name | value\njust prose\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('just prose', errors[0])

    def test_back_references_between_forms_fail(self) -> None:
        for row in (
            'Everything | same as above',
            'Permissions | as above',
            'Permissions | same scopes but Edit instead',
        ):
            with self.subTest(row=row):
                errors = self.errors_for(self.ui_step(fields=f'Name | infra\n{row}\n'))
                self.assertEqual(1, len(errors))
                self.assertIn('self-contained', errors[0])

    def test_a_url_variable_step_zero_never_exports_fails(self) -> None:
        errors = self.errors_for(self.ui_step(url='https://dash.example.test/$NOT_EXPORTED/r2'))
        self.assertEqual(1, len(errors))
        self.assertIn('NOT_EXPORTED', errors[0])

    def test_braced_exported_variables_pass(self) -> None:
        self.assertEqual([], self.errors_for(self.ui_step(url='https://github.com/${GITHUB_ORG}/settings')))


if __name__ == '__main__':
    unittest.main()
