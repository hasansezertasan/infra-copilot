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
   export HCP_TOKEN=<token>
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


def cli_step(command: str, effect: str = 'Stores the secret.') -> str:
    return step(
        'check_summary: The secret exists.\n'
        'cli:\n'
        f'  - effect: {effect}\n'
        '    run: |\n'
        + textwrap.indent(command, '      ')
    )


def ui_step(url: str = 'https://dash.example.test/$CF_ACCOUNT_ID/r2', fields: str = 'Name | value\n') -> str:
    parts = ['check_summary: The form exists.\n', 'ui:\n']
    if url:
        parts.append(f'  - url: {url}\n')
        parts.append('    fields: |\n')
    else:
        parts.append('  - fields: |\n')
    parts.append(textwrap.indent(fields, '      '))
    return step(''.join(parts))


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

    def test_cli_entry_with_a_summary_passes(self) -> None:
        self.assertEqual([], self.errors_for(cli_step('gh secret set TOKEN_NAME\n')))

    def test_empty_check_summary_fails(self) -> None:
        errors = self.errors_for(step(
            'check_summary:\ncli:\n  - effect: Does it.\n    run: |\n      gh repo view\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('check_summary', errors[0])

    def test_cli_entry_pointing_at_another_entry_fails(self) -> None:
        errors = self.errors_for(cli_step(
            'gh repo view\n',
            effect='Creates the bucket, then run the commands from the us-east-1 entry.',
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('self-contained', errors[0])

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
                self.assertEqual([], self.errors_for(cli_step(command)))

    def test_fan_out_after_a_hidden_read_passes_whatever_the_variable_is_called(self) -> None:
        command = (
            'read -rs TOKEN\n'
            'for repo in a b; do printf %s "$TOKEN" | gh secret set APP_KEY --repo "$repo"; done\n'
        )
        self.assertEqual([], self.errors_for(cli_step(command)))

    def test_a_hidden_read_with_a_prompt_passes(self) -> None:
        for read in ('read -rsp "Token: " TOKEN', 'read -rs -p "Token: " TOKEN'):
            with self.subTest(read=read):
                command = f'{read}\nprintf %s "$TOKEN" | gh secret set APP_KEY\n'
                self.assertEqual([], self.errors_for(cli_step(command)))

    def test_a_prompt_that_mentions_secrets_does_not_make_a_read_hidden(self) -> None:
        command = 'read -r -p "Secret: " TOKEN\nprintf %s "$TOKEN" | gh secret set APP_KEY\n'
        self.assertEqual(1, len(self.errors_for(cli_step(command))))

    def test_a_file_redirect_from_a_token_named_variable_passes(self) -> None:
        self.assertEqual([], self.errors_for(cli_step('gh secret set APP_KEY < "$TOKEN_FILE"\n')))

    def test_variables_naming_a_file_path_or_secret_name_are_no_leak(self) -> None:
        for variable in ('TOKEN_FILE', 'TOKEN_PATH', 'SECRET_NAME'):
            with self.subTest(variable=variable):
                self.assertEqual([], self.errors_for(cli_step(f'gh secret set "${variable}" < key.pem\n')))

    def test_a_dash_line_inside_a_literal_block_does_not_split_an_entry(self) -> None:
        command = 'cat <<EOF\n- not an entry\nEOF\n'
        self.assertEqual([], self.errors_for(cli_step(command)))
        errors = self.errors_for(step(
            'check_summary: The form exists.\n'
            'ui:\n'
            '  - url: https://dash.example.test/$CF_ACCOUNT_ID\n'
            '    fields: |\n'
            '      Name | infra\n'
            '      - same as above | x\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('self-contained', errors[0])

    def test_assigning_a_file_path_or_name_variable_is_no_leak(self) -> None:
        for command in ('TOKEN_FILE=~/.cf-token\n', 'export SECRET_NAME=CLOUDFLARE\n', 'APP_KEY_PATH=./key.pem\n'):
            with self.subTest(command=command):
                self.assertEqual([], self.errors_for(cli_step(command)))

    def test_every_block_scalar_spelling_is_still_checked_for_secrets(self) -> None:
        for indicator in ('|', '|-', '|+', '>-'):
            with self.subTest(indicator=indicator):
                errors = self.errors_for(step(
                    'check_summary: The secret exists.\n'
                    'cli:\n'
                    '  - effect: Stores it.\n'
                    f'    run: {indicator}\n'
                    '      gh secret set APP_KEY --body hunter2\n'
                ))
                self.assertEqual(1, len(errors))
                self.assertIn('secret', errors[0])

    def test_a_cli_entry_without_a_run_block_fails(self) -> None:
        errors = self.errors_for(step(
            'check_summary: The secret exists.\n'
            'cli:\n'
            '  - effect: Stores it.\n'
            '    run: gh secret set APP_KEY --body hunter2\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('run', errors[0])

    def test_empty_structured_fields_fail(self) -> None:
        for body in (
            'check_summary: Nothing to see.\ncli:\n',
            'check_summary: Nothing to see.\ncli: []\n',
            'check_summary: Nothing to see.\nui:\n',
            'run:\n',
            'run: |\n',
        ):
            with self.subTest(body=body):
                errors = self.errors_for(step(body))
                self.assertEqual(1, len(errors))
                self.assertIn('sample', errors[0])

    def test_a_run_text_with_words_still_passes(self) -> None:
        self.assertEqual([], self.errors_for(step('run: Open the dashboard.\n')))

    def test_a_secret_named_export_in_a_ui_url_or_row_fails(self) -> None:
        for errors in (
            self.errors_for(ui_step(url='https://app.example.test/?t=$HCP_TOKEN')),
            self.errors_for(ui_step(fields='Token | $HCP_TOKEN\n')),
        ):
            self.assertEqual(1, len(errors))
            self.assertIn('secret', errors[0])

    def test_a_secret_read_visibly_before_a_hidden_read_still_fails(self) -> None:
        for command in (
            'read -r TOKEN\nprintf %s "$TOKEN" | gh secret set A\nread -rs TOKEN\n',
            'printf %s "$TOKEN" | gh secret set A\nread -rs TOKEN\n',
            'read -rs TOKEN\nread -r TOKEN\nprintf %s "$TOKEN" | gh secret set A\n',
        ):
            with self.subTest(command=command):
                errors = self.errors_for(cli_step(command))
                self.assertEqual(1, len(errors))
                self.assertIn('secret', errors[0])

    def test_a_cli_entry_without_an_effect_fails(self) -> None:
        errors = self.errors_for(step(
            'check_summary: Done.\ncli:\n  - run: |\n      gh repo view\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('effect', errors[0])

    def test_a_cli_entry_with_only_an_effect_fails(self) -> None:
        errors = self.errors_for(step(
            'check_summary: The secret exists.\ncli:\n  - effect: Stores it.\n'
        ))
        self.assertEqual(1, len(errors))
        self.assertIn('run', errors[0])

    def test_a_check_summary_block_scalar_with_no_body_fails(self) -> None:
        for indicator in ('|', '>-'):
            with self.subTest(indicator=indicator):
                errors = self.errors_for(step(
                    f'check_summary: {indicator}\n'
                    'cli:\n'
                    '  - effect: Does it.\n'
                    '    run: |\n'
                    '      gh repo view\n'
                ))
                self.assertEqual(1, len(errors))
                self.assertIn('check_summary', errors[0])

    def test_a_check_summary_block_scalar_with_a_body_passes(self) -> None:
        self.assertEqual([], self.errors_for(step(
            'check_summary: >-\n'
            '  The secret exists.\n'
            'cli:\n'
            '  - effect: Does it.\n'
            '    run: |\n'
            '      gh repo view\n'
        )))

    def test_a_cli_variable_step_zero_never_exports_fails(self) -> None:
        errors = self.errors_for(cli_step('gh repo create "$GITHUB_ORG/$NOT_EXPORTED"\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('NOT_EXPORTED', errors[0])

    def test_cli_variables_the_command_block_assigns_itself_pass(self) -> None:
        for command in (
            'for repo in a b; do gh repo view "$GITHUB_ORG/$repo"; done\n',
            'read -r name\ngh repo view "$GITHUB_ORG/$name"\n',
            'target=main\ngh repo view "$GITHUB_ORG" --branch "$target" --json "$HOME"\n',
        ):
            with self.subTest(command=command):
                self.assertEqual([], self.errors_for(cli_step(command)))

    def test_a_variable_used_before_the_command_block_assigns_it_fails(self) -> None:
        for command in (
            'tool "$TARGET"; TARGET=value\n',
            'tool "$TARGET"\nTARGET=value\n',
            'tool "$name"\nread -r name\n',
        ):
            with self.subTest(command=command):
                errors = self.errors_for(cli_step(command))
                self.assertEqual(1, len(errors))
                self.assertIn('never', errors[0])

    def test_a_variable_assigned_before_use_on_one_line_passes(self) -> None:
        self.assertEqual([], self.errors_for(cli_step('TARGET=value; tool "$TARGET"\n')))

    def test_an_exported_cli_variable_passes(self) -> None:
        self.assertEqual([], self.errors_for(cli_step('gh repo view "$GITHUB_ORG/${CF_ACCOUNT_ID}"\n')))

    def test_a_secret_variable_that_was_never_read_hidden_fails(self) -> None:
        errors = self.errors_for(cli_step('printf %s "$TOKEN" | gh secret set APP_KEY\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('secret', errors[0])

    def test_secret_passed_as_an_argument_fails(self) -> None:
        for command in (
            'tool login -password=hunter2\n',
            'curl -u admin:hunter2 https://example.test\n',
            'gh secret set APP_KEY <<< "hunter2"\n',
            'aws configure set aws_secret_access_key hunter2\n',
            'GH_TOKEN=hunter2 gh repo view\n',
            'gh secret set APP_KEY --body "hunter2"\n',
            'gh secret set APP_KEY -b hunter2\n',
            'wrangler secret put X --value "$API_TOKEN"\n',
            'gh secret set APP_KEY --body="$APP_PRIVATE_KEY"\n',
            'curl -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" https://example.test\n',
        ):
            with self.subTest(command=command):
                errors = self.errors_for(cli_step(command))
                self.assertEqual(1, len(errors))
                self.assertIn('secret', errors[0])

    def test_complete_ui_entry_passes(self) -> None:
        self.assertEqual([], self.errors_for(ui_step(
            fields='Token name | infra\nPermissions | Zone DNS Edit\n',
        )))

    def test_ui_entry_without_a_url_fails(self) -> None:
        errors = self.errors_for(ui_step(url=''))
        self.assertEqual(1, len(errors))
        self.assertIn('url', errors[0])

    def test_ui_entry_with_an_empty_field_table_fails(self) -> None:
        errors = self.errors_for(ui_step(fields='\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('field', errors[0])

    def test_a_field_row_that_is_not_a_pair_fails(self) -> None:
        errors = self.errors_for(ui_step(fields='Name | value\njust prose\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('just prose', errors[0])

    def test_back_references_between_forms_fail(self) -> None:
        for row in (
            'Everything | same as above',
            'Permissions | as above',
            'Permissions | same scopes but Edit instead',
            'Permissions | identical to the first form',
        ):
            with self.subTest(row=row):
                errors = self.errors_for(ui_step(fields=f'Name | infra\n{row}\n'))
                self.assertEqual(1, len(errors))
                self.assertIn('self-contained', errors[0])

    def test_a_url_variable_step_zero_never_exports_fails(self) -> None:
        errors = self.errors_for(ui_step(url='https://dash.example.test/$NOT_EXPORTED/r2'))
        self.assertEqual(1, len(errors))
        self.assertIn('NOT_EXPORTED', errors[0])

    def test_a_field_value_variable_step_zero_never_exports_fails(self) -> None:
        errors = self.errors_for(ui_step(fields='Account | $NOT_EXPORTED\n'))
        self.assertEqual(1, len(errors))
        self.assertIn('NOT_EXPORTED', errors[0])

    def test_braced_exported_variables_pass(self) -> None:
        self.assertEqual([], self.errors_for(ui_step(url='https://github.com/${GITHUB_ORG}/settings')))


if __name__ == '__main__':
    unittest.main()
