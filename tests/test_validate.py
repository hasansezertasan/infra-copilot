from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    JSON_MANIFESTS,
    MAX_DESCRIPTION_BUDGET,
    TOOL_PIN_SPECS,
    TOOL_PIN_WORKFLOWS,
    VERSIONLESS_MANIFESTS,
    collect_manifest_errors,
    skill_descriptions,
    validate_config_fallbacks,
    _looks_like_marker,
    fenced_lines,
    frontmatter_bounds,
    frontmatter_keys,
    validate_customization_markers,
    validate_description_budget,
    validate_json_manifests,
    validate_links,
    validate_manifest_paths,
    validate_phase_five_rule,
    validate_toolchain_contract,
    audited_version,
    validate_shipped_check_paths,
    validate_skill_sections,
    validate_tool_pins,
    validate_versions,
)


class ValidateLinksTests(unittest.TestCase):
    def test_rejects_link_that_resolves_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            repository = workspace / "repo"
            docs = repository / "docs"
            docs.mkdir(parents=True)
            (workspace / "outside.md").write_text("outside", encoding="utf-8")
            (docs / "guide.md").write_text(
                "[outside](../../outside.md)", encoding="utf-8"
            )

            self.assertEqual(
                validate_links(repository),
                [
                    "docs/guide.md: link '../../outside.md' resolves outside the "
                    "repository"
                ],
            )

    def test_accepts_existing_link_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            docs = repository / "docs"
            docs.mkdir()
            (repository / "README.md").write_text("read me", encoding="utf-8")
            (docs / "guide.md").write_text(
                "[read me](../README.md)", encoding="utf-8"
            )

            self.assertEqual(validate_links(repository), [])


class ValidateConfigFallbacksTests(unittest.TestCase):
    def test_canonical_entrypoints_document_legacy_fallback(self) -> None:
        self.assertEqual(validate_config_fallbacks(), [])


class CustomizationMarkerTests(unittest.TestCase):
    """The markers are comments, so this validator is their only enforcement."""

    REFERENCES = ".ai-rulez/skills/infra-copilot/references"

    def test_shipped_examples_carry_balanced_markers(self) -> None:
        self.assertEqual(validate_customization_markers(), [])

    def _repository(self, temporary_directory: str, **files: str) -> Path:
        """A tree holding both examples and the rule document.

        Every file has to exist: the validator reads all three, so a partial
        fixture fails on a missing file rather than on the case under test.
        """
        repository = Path(temporary_directory)
        defaults = {
            "config.md.example": (
                "---\n# infra-copilot:customization start\nhcp_org: x\n"
                'hcp_status_check_id: ""\n'
                "# infra-copilot:customization end\n---\n"
            ),
            "decisions.md.example": (
                "<!-- infra-copilot:customization start -->\n"
                "| Decision | Choice | Status | Rationale |\n"
                "<!-- infra-copilot:customization end -->\n"
            ),
            "config.md": "preserve it verbatim. Never merge by inference.\n",
        }
        defaults.update(files)
        for name, body in defaults.items():
            document = repository / self.REFERENCES / name
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text(body, encoding="utf-8")
        return repository

    def test_every_frontmatter_field_is_required_inside_the_region(self) -> None:
        """Derived, not enumerated.

        The first version listed two of the seven fields, so the other five
        could drift out of the region while validation stayed green. Listing
        them would only move the gap to whichever field is added next.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra-copilot:customization start\n"
                        'hcp_org: x\nhcp_status_check_id: ""\n'
                        "# infra-copilot:customization end\n"
                        "github_org: x\napex_domain: x\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'github_org:' is outside "
                    "the infra-copilot:customization region a re-scaffold preserves",
                    f"{self.REFERENCES}/config.md.example: 'apex_domain:' is outside "
                    "the infra-copilot:customization region a re-scaffold preserves",
                ],
            )

    def test_protects_a_field_added_to_the_template_later(self) -> None:
        """The point of deriving: no list to remember to update."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra-copilot:customization start\n"
                        'hcp_org: x\nhcp_status_check_id: ""\n'
                        "# infra-copilot:customization end\n"
                        "gcp_project: your-project\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'gcp_project:' is outside "
                    "the infra-copilot:customization region a re-scaffold preserves"
                ],
            )

    def test_rejects_markers_that_enclose_nothing(self) -> None:
        """Balanced and ordered, but the region is empty.

        Two markers sitting together above the frontmatter satisfy every count
        and order check while preserving nothing, so a re-scaffold would
        overwrite exactly the values the pair exists to protect.

        This shape also displaces the frontmatter from line 0. The frontmatter
        containment rule now catches that directly, so this fixture keeps the
        delimiters intact and only collapses the region.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra-copilot:customization start\n"
                        "# infra-copilot:customization end\n"
                        "hcp_org: x\nhcp_status_check_id: \"\"\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'hcp_status_check_id:' is "
                    "outside the infra-copilot:customization region a re-scaffold "
                    "preserves",
                    f"{self.REFERENCES}/config.md.example: 'hcp_org:' is outside the "
                    "infra-copilot:customization region a re-scaffold preserves",
                ],
            )

    def test_rejects_markers_inside_a_fenced_code_block(self) -> None:
        """A column-zero fence neutralises the region without any indentation.

        Markdown renders the markers as text and does not render the table, so
        the indentation rule cannot catch this shape.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "```\n<!-- infra-copilot:customization start -->\n"
                        "| Decision | Choice | Status | Rationale |\n"
                        "<!-- infra-copilot:customization end -->\n```\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra-copilot:customization marker on line 2 is inside a "
                    "fenced code block, so Markdown renders it as text rather "
                    "than a comment",
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra-copilot:customization marker on line 4 is inside a "
                    "fenced code block, so Markdown renders it as text rather "
                    "than a comment",
                ],
            )

    def test_rejects_indented_markers(self) -> None:
        """Indented four spaces, Markdown reads the region as a code block.

        The markers become displayed text and the config block stops being
        frontmatter, while strip() still saw a well-formed marker.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "    <!-- infra-copilot:customization start -->\n"
                        "    | Decision | Choice | Status | Rationale |\n"
                        "    <!-- infra-copilot:customization end -->\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra-copilot:customization marker on line 1 is indented; "
                    "markers must start at column 0, or Markdown reads the region "
                    "as a code block",
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra-copilot:customization marker on line 3 is indented; "
                    "markers must start at column 0, or Markdown reads the region "
                    "as a code block",
                ],
            )

    def test_rejects_a_marker_that_is_not_a_comment(self) -> None:
        """A marker that loses its "#" becomes a stray line among the fields."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\ninfra-copilot:customization start\nhcp_org: x\n"
                        'hcp_status_check_id: ""\n'
                        "# infra-copilot:customization end\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: line 2 carries "
                    "infra-copilot:customization but is not a well-formed comment "
                    "marker: 'infra-copilot:customization start'"
                ],
            )

    def test_rejects_the_other_file_s_comment_syntax(self) -> None:
        """An HTML comment is inert inside YAML frontmatter, and vice versa."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "# infra-copilot:customization start\n| a |\n"
                        "<!-- infra-copilot:customization end -->\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: line 1 carries "
                    "infra-copilot:customization but is not a well-formed comment "
                    "marker: '# infra-copilot:customization start'"
                ],
            )

    def test_rejects_a_marker_outside_the_frontmatter_delimiters(self) -> None:
        """Frontmatter intact, but the region spills past its closing ---."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra-copilot:customization start\nhcp_org: x\n"
                        'hcp_status_check_id: ""\n---\n'
                        "# infra-copilot:customization end\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: "
                    "infra-copilot:customization marker on line 6 is outside the "
                    "frontmatter delimiters (lines 1 and 5), so the preserved "
                    "region no longer matches the fields a human fills in"
                ],
            )

    def test_rejects_a_config_template_with_no_frontmatter(self) -> None:
        """A start marker above the opening --- stops it being frontmatter."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "# infra-copilot:customization start\n---\nhcp_org: x\n"
                        'hcp_status_check_id: ""\n'
                        "# infra-copilot:customization end\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: no YAML frontmatter, "
                    "so its markers cannot be inside it"
                ],
            )

    def test_prose_naming_the_token_is_not_a_broken_marker(self) -> None:
        """Both real templates explain the markers in prose that names the token.

        Matching the bare token flagged those sentences as malformed markers.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "Keep the two `infra-copilot:customization` comments.\n"
                        "<!-- infra-copilot:customization start -->\n"
                        "| Decision | Choice | Status | Rationale |\n"
                        "<!-- infra-copilot:customization end -->\n"
                    )
                },
            )

            self.assertEqual(validate_customization_markers(repository), [])

    def test_rejects_one_field_drifting_out_of_the_region(self) -> None:
        """The realistic drift: a template edit moves one line past the end marker."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra-copilot:customization start\nhcp_org: x\n"
                        "# infra-copilot:customization end\n"
                        'hcp_status_check_id: ""\n---\n'
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'hcp_status_check_id:' is "
                    "outside the infra-copilot:customization region a re-scaffold "
                    "preserves",
                ],
            )

    def test_reports_an_unreadable_document_instead_of_raising(self) -> None:
        """Validators accumulate into one list, so a raise prints none of it.

        config.md.example is not covered by the layout short-circuit in main,
        so this guard is the only thing between a missing file and a traceback.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(temporary_directory)
            (repository / self.REFERENCES / "config.md.example").unlink()

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: unreadable, "
                    "cannot check markers"
                ],
            )

    def test_rejects_an_unbalanced_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{"config.md.example": "---\n# infra-copilot:customization start\n---\n"},
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: expected exactly one "
                    "infra-copilot:customization pair, found 1 start and 0 end"
                ],
            )

    def test_rejects_a_duplicated_start(self) -> None:
        """Two starts are balanced by a naive count of the token alone."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "# infra-copilot:customization start\n"
                        "# infra-copilot:customization start\n"
                        "# infra-copilot:customization end\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: expected exactly one "
                    "infra-copilot:customization pair, found 2 start and 1 end"
                ],
            )

    def test_rejects_an_end_before_its_start(self) -> None:
        """One of each, so counting alone calls this file well-formed."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "# infra-copilot:customization end\nhcp_org: x\n"
                        "# infra-copilot:customization start\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: "
                    "infra-copilot:customization end precedes its start"
                ],
            )

    def test_requires_the_preserve_and_hand_off_rule(self) -> None:
        """Markers with no documented rule preserve nothing."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory, **{"config.md": "Re-scaffold as you see fit.\n"}
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md: re-scaffold rule missing 'verbatim'",
                    f"{self.REFERENCES}/config.md: re-scaffold rule missing "
                    "'Never merge by inference'",
                ],
            )

    def test_accepts_a_rule_whose_phrase_wraps_across_lines(self) -> None:
        """Prose re-wraps on edit; a raw-text match would report a false failure."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{"config.md": "preserve it\nverbatim. **Never merge by\ninference.**\n"},
            )

            self.assertEqual(validate_customization_markers(repository), [])


class FrontmatterKeyTests(unittest.TestCase):
    def test_reads_top_level_keys_only(self) -> None:
        lines = [
            "---",
            "hcp_org: x",
            "managed_repos:",
            "  - owner/name",
            "---",
            "body: not frontmatter",
        ]
        self.assertEqual(frontmatter_keys(lines), ["hcp_org", "managed_repos"])

    def test_documents_without_frontmatter_have_no_keys(self) -> None:
        """decisions.md.example is a plain body; the derived rule is a no-op there."""
        self.assertEqual(frontmatter_keys(["# heading", "key: value"]), [])
        self.assertEqual(frontmatter_keys([]), [])


class LooksLikeMarkerTests(unittest.TestCase):
    """Which lines count as an attempted marker, and so as malformed."""

    def test_a_bare_token_counts(self) -> None:
        self.assertTrue(_looks_like_marker("infra-copilot:customization start"))

    def test_the_wrong_comment_syntax_counts(self) -> None:
        self.assertTrue(_looks_like_marker("# infra-copilot:customization start"))
        self.assertTrue(
            _looks_like_marker("<!-- infra-copilot:customization end -->")
        )

    def test_explanatory_prose_inside_a_comment_does_not_count(self) -> None:
        """The token and edge must follow the prefix, not appear anywhere."""
        self.assertFalse(
            _looks_like_marker(
                "<!-- Use infra-copilot:customization start before editing. -->"
            )
        )
        self.assertFalse(
            _looks_like_marker("# Keep infra-copilot:customization end in place")
        )

    def test_prose_naming_the_token_without_an_edge_does_not_count(self) -> None:
        self.assertFalse(
            _looks_like_marker("Keep the two `infra-copilot:customization` comments.")
        )


class FencedLinesTests(unittest.TestCase):
    def test_tracks_a_backtick_fence(self) -> None:
        self.assertEqual(fenced_lines(["a", "```", "b", "```", "c"]), {1, 2, 3})

    def test_an_info_string_still_opens_a_fence(self) -> None:
        self.assertEqual(fenced_lines(["```yaml", "b", "```"]), {0, 1, 2})

    def test_a_shorter_run_does_not_close_a_longer_fence(self) -> None:
        """CommonMark requires a closer at least as long as its opener.

        Tracking only the fence character closed a ```` block on ```, which put
        the lines after it outside the fenced set while Markdown still rendered
        them as code.
        """
        self.assertEqual(
            fenced_lines(["````", "```", "a", "````"]), {0, 1, 2, 3}
        )

    def test_a_closer_may_be_longer_than_its_opener(self) -> None:
        self.assertEqual(fenced_lines(["```", "a", "`````"]), {0, 1, 2})

    def test_a_line_with_an_info_string_is_not_a_closer(self) -> None:
        """```python inside an open block is content, not a terminator."""
        self.assertEqual(
            fenced_lines(["```", "```python", "a", "```"]), {0, 1, 2, 3}
        )

    def test_a_backtick_opener_may_not_carry_a_backtick_info_string(self) -> None:
        self.assertEqual(fenced_lines(["``` a ` b", "x"]), set())

    def test_four_space_indent_opens_no_fence(self) -> None:
        """At four spaces it is an indented code block, not a fence."""
        self.assertEqual(fenced_lines(["    ```", "a", "    ```"]), set())

    def test_up_to_three_spaces_still_opens_a_fence(self) -> None:
        self.assertEqual(fenced_lines(["   ```", "a", "   ```"]), {0, 1, 2})

    def test_a_different_fence_character_does_not_close(self) -> None:
        """Only the same character terminates, so ``` inside ~~~ is content."""
        self.assertEqual(fenced_lines(["~~~", "```", "b", "~~~"]), {0, 1, 2, 3})

    def test_unclosed_fence_swallows_the_rest(self) -> None:
        self.assertEqual(fenced_lines(["```", "a", "b"]), {0, 1, 2})

    def test_no_fence_means_no_fenced_lines(self) -> None:
        self.assertEqual(fenced_lines(["a", "b"]), set())


class FrontmatterBoundsTests(unittest.TestCase):
    def test_finds_the_delimiters(self) -> None:
        self.assertEqual(frontmatter_bounds(["---", "a: 1", "---", "body"]), (0, 2))

    def test_requires_frontmatter_to_start_at_line_zero(self) -> None:
        """A YAML block below anything else is not frontmatter."""
        self.assertIsNone(frontmatter_bounds(["# comment", "---", "a: 1", "---"]))

    def test_indented_delimiters_are_not_frontmatter(self) -> None:
        """strip() reduced an indented delimiter to ---; column 0 is required."""
        self.assertIsNone(frontmatter_bounds(["    ---", "a: 1", "    ---"]))
        self.assertIsNone(frontmatter_bounds(["---", "a: 1", "    ---"]))

    def test_trailing_whitespace_on_a_delimiter_is_tolerated(self) -> None:
        """Only leading whitespace changes how Markdown reads the line."""
        self.assertEqual(frontmatter_bounds(["--- ", "a: 1", "---  "]), (0, 2))

    def test_unterminated_frontmatter_has_no_bounds(self) -> None:
        self.assertIsNone(frontmatter_bounds(["---", "a: 1"]))
        self.assertIsNone(frontmatter_bounds([]))


class ValidatePhaseFiveRuleTests(unittest.TestCase):
    def test_status_skill_requires_empty_import_set(self) -> None:
        self.assertEqual(validate_phase_five_rule(), [])

    def test_rejects_rule_that_accepts_a_clean_run_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            document = repository / ".ai-rulez/skills/status/SKILL.md"
            document.parent.mkdir(parents=True)
            document.write_text(
                "Infer done from the workspace's latest HCP run being clean.",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_phase_five_rule(repository),
                [
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'imports: 0'",
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'incomplete'",
                    ".ai-rulez/skills/status/SKILL.md: phase-5 completion rule "
                    "missing 'status `applied`'",
                ],
            )


class SingleVersionAuthorityTests(unittest.TestCase):
    """External versions live in scripts/upstream.json and nowhere else.

    validate_toolchain_contract used to hardcode the cf-terraforming pin, so a
    drift update passed check_upstream and then failed here with nothing
    pointing at the second copy.
    """

    def test_toolchain_contract_reads_the_manifest(self) -> None:
        self.assertEqual(validate_toolchain_contract(), [])

    def test_unreadable_manifest_is_reported_not_raised(self) -> None:
        """main() evaluates every validator into one list.

        Raising here would replace the errors already collected with a
        traceback, which is the bug collect_manifest_errors exists to prevent.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            source = Path(__file__).resolve().parents[1]
            shutil.copytree(
                source / ".ai-rulez", repository / ".ai-rulez"
            )
            (repository / "scripts").mkdir()  # no upstream.json

            errors = validate_toolchain_contract(repository)

            self.assertTrue(
                any("cannot read the cf-terraforming pin" in error for error in errors),
                errors,
            )

    def test_unreadable_workflow_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "Makefile").write_text(
                "AI_RULEZ_VERSION := 4.11.3\nSKILLS_VERSION := 1.5.23\n", encoding="utf-8"
            )
            (repository / "README.md").write_text(
                "ai-rulez@4.11.3 skills@1.5.23\n", encoding="utf-8"
            )

            errors = validate_tool_pins(repository)

            self.assertTrue(
                any("cannot read workflow" in error for error in errors), errors
            )

    def test_unknown_entry_raises_rather_than_defaulting(self) -> None:
        with self.assertRaises(KeyError):
            audited_version("not-an-entry")

    def test_no_validator_hardcodes_an_audited_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        audited = {
            str(entry["audited"])
            for entry in json.loads(
                (root / "scripts/upstream.json").read_text(encoding="utf-8")
            )["entries"]
        }
        source = (root / "scripts/validate.py").read_text(encoding="utf-8")
        for version in audited:
            if len(version) < 4:  # a bare major appears in unrelated contexts
                continue
            with self.subTest(version=version):
                self.assertNotIn(
                    version,
                    source,
                    "read it via audited_version() instead of repeating the literal",
                )


class ShippedCheckPathTests(unittest.TestCase):
    """A check naming a shipped script fails obscurely in a consuming repo."""

    def test_real_manifest_resolves_its_shipped_checks(self) -> None:
        self.assertEqual(validate_shipped_check_paths(), [])

    def test_missing_script_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            manifest = repository / "skills/infra-copilot/references/steps.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                'preflight:\n  - tool: infra-copilot-references\n'
                'steps:\n  - check: sh "$INFRA_COPILOT_REFERENCES/checks/gone.sh"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                validate_shipped_check_paths(repository),
                [
                    "skills/infra-copilot/references/steps.yaml: check references "
                    "$INFRA_COPILOT_REFERENCES/checks/gone.sh, which does not exist"
                ],
            )

    def test_paths_escaping_the_references_tree_are_reported(self) -> None:
        """The path comes out of a shell string, so it can be absolute or traverse.

        `Path("a") / "/abs"` discards the prefix and `..` walks upward, so
        without a containment check the existence test could pass on an
        unrelated filesystem path.
        """
        for payload in ("/etc/passwd", "../../../../etc/passwd", "checks/../../.."):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    references = repository / "skills/infra-copilot/references"
                    (references / "checks").mkdir(parents=True)
                    (references / "steps.yaml").write_text(
                        "preflight:\n  - tool: infra-copilot-references\n"
                        f'steps:\n  - check: sh "$INFRA_COPILOT_REFERENCES/{payload}"\n',
                        encoding="utf-8",
                    )

                    errors = validate_shipped_check_paths(repository)

                    self.assertEqual(len(errors), 1, errors)
                    self.assertIn("resolves outside", errors[0])

    def test_shipped_check_without_a_preflight_guard_is_reported(self) -> None:
        """The export is the precondition; a check that needs it must be gated."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            references = repository / "skills/infra-copilot/references"
            (references / "checks").mkdir(parents=True)
            (references / "checks/present.sh").write_text("exit 0\n", encoding="utf-8")
            (references / "steps.yaml").write_text(
                'steps:\n  - check: sh "$INFRA_COPILOT_REFERENCES/checks/present.sh"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                validate_shipped_check_paths(repository),
                [
                    "skills/infra-copilot/references/steps.yaml: a check resolves a "
                    "shipped script but preflight has no infra-copilot-references guard"
                ],
            )


class LintScopeTests(unittest.TestCase):
    """The canonical sources must be linted, with width relaxed only there."""

    def test_root_config_lints_the_canonical_sources(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = (root / ".markdownlint-cli2.jsonc").read_text(encoding="utf-8")
        self.assertIn(".ai-rulez/**/*.md", config)

    def test_nested_config_relaxes_only_line_width(self) -> None:
        """Deleting this file silently reintroduces 119 findings, so pin its purpose.

        `make lint` is the real enforcement — it fails loudly if a future
        markdownlint version stops applying nested configuration — but nothing
        stopped someone deleting the file as apparently inert.
        """
        root = Path(__file__).resolve().parents[1]
        nested = root / ".ai-rulez/.markdownlint-cli2.jsonc"
        self.assertTrue(nested.is_file(), "canonical sources need their own lint config")
        body = nested.read_text(encoding="utf-8")
        self.assertRegex(body, r'"MD013"\s*:\s*false')


class SkillSectionTests(unittest.TestCase):
    """Four shapes across four skills is how the same concept got two names."""

    def test_every_skill_has_the_required_sections(self) -> None:
        self.assertEqual(validate_skill_sections(), [])

    def test_missing_section_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            skill = repository / ".ai-rulez/skills/partial"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: partial\n---\n\n## Workflow\n\n## Guardrails\n",
                encoding="utf-8",
            )

            errors = validate_skill_sections(repository)

            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(any("'validation'" in error for error in errors), errors)
            self.assertTrue(any("'example'" in error for error in errors), errors)

    def test_matching_is_lenient_about_wording(self) -> None:
        """`## Example report` must satisfy `example`.

        The goal is that each concern is addressed somewhere findable, not that
        headings be identical across skills.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            skill = repository / ".ai-rulez/skills/worded"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: worded\n---\n\n## How the workflow runs\n\n"
                "## Guardrails\n\n## Validation checkpoint\n\n## Example report\n",
                encoding="utf-8",
            )

            self.assertEqual(validate_skill_sections(repository), [])

    def test_the_completion_section_has_one_name_everywhere(self) -> None:
        """`Done signal` in setup and `Success signal` in import was the bug."""
        root = Path(__file__).resolve().parents[1]
        for skill in sorted((root / ".ai-rulez/skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill.parent.name):
                body = skill.read_text(encoding="utf-8")
                self.assertNotIn("## Done signal", body)
                self.assertNotIn("## Success signal", body)


class DescriptionBudgetTests(unittest.TestCase):
    """Descriptions load into the host prompt every session, whether used or not."""

    def test_real_skills_are_within_budget(self) -> None:
        self.assertEqual(validate_description_budget(), [])

    def test_over_budget_is_reported(self) -> None:
        """Built from several skills, because that is the only way it can happen.

        validate_skills caps each description at 1024 characters, so no single
        skill can exceed a 2000-character aggregate on its own.
        """
        per_skill = 900
        needed = MAX_DESCRIPTION_BUDGET // per_skill + 1
        self.assertLess(per_skill, 1024, "each skill must stay under the per-skill cap")
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            for index in range(needed):
                skill = repository / f".ai-rulez/skills/verbose{index}"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    f'---\nname: verbose{index}\n'
                    f'description: "{"x" * per_skill}"\n---\n',
                    encoding="utf-8",
                )

            errors = validate_description_budget(repository)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("description budget", errors[0])

    def test_no_description_enumerates_trigger_phrases(self) -> None:
        """Phrase lists were the bulk of the 3.7 KB this budget replaced.

        The SessionStart hook now answers "this plugin exists", so a
        description only has to answer "which skill".
        """
        for name, description in skill_descriptions().items():
            with self.subTest(skill=name):
                self.assertNotIn("Trigger on:", description)
                self.assertLessEqual(
                    description.count("'"),
                    2,
                    "quoted trigger phrases belong in the hook's job, not here",
                )

    def test_provider_specific_tooling_is_not_described_as_general(self) -> None:
        """cf-terraforming is Cloudflare-only; the body warns what happens otherwise.

        Running the Cloudflare steps for a GitHub request mints an irrelevant
        token and writes to the wrong leaf, so a description that implies the
        tool is provider-agnostic causes exactly that misrouting.
        """
        for name, description in skill_descriptions().items():
            if "cf-terraforming" in description:
                with self.subTest(skill=name):
                    self.assertIn("Cloudflare", description)

    def test_each_action_skill_still_disambiguates_itself(self) -> None:
        """Trimming must not remove the add-vs-import distinction.

        That pairing is the genuinely hard one: both touch a working repo, and
        the difference is only whether the resource already exists.
        """
        descriptions = skill_descriptions()
        self.assertIn("infra-copilot:import", descriptions["add"])
        self.assertIn("infra-copilot:add", descriptions["import"])
        self.assertIn("infra-copilot:import", descriptions["setup"])
        self.assertIn("Read-only", descriptions["status"])


class GeneratedInventoryDocsTests(unittest.TestCase):
    """The docs quote a generated-file count and a headerless list; both drifted once."""

    def test_docs_quote_the_real_counts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        outputs = sorted(
            json.loads((root / ".ai-rulez-generated.json").read_text(encoding="utf-8"))[
                "outputs"
            ]
        )
        headerless = [
            path
            for path in outputs
            if "AI-RULEZ :: GENERATED FILE"
            not in (root / path).read_text(encoding="utf-8", errors="replace")
        ]
        for document in ("AGENTS.md", "CONTRIBUTING.md"):
            text = (root / document).read_text(encoding="utf-8")
            self.assertIn(
                str(len(outputs)), text, f"{document} does not quote {len(outputs)} outputs"
            )
            for path in headerless:
                self.assertIn(
                    Path(path).name,
                    text,
                    f"{document} omits headerless generated file {path}",
                )


class ValidateReleaseSurfacesTests(unittest.TestCase):
    def test_json_manifests_parse(self) -> None:
        self.assertEqual(validate_json_manifests(), [])

    def test_manifest_paths_stay_inside_repository(self) -> None:
        self.assertEqual(validate_manifest_paths(), [])

    def test_makefile_and_documentation_tool_pins_match(self) -> None:
        self.assertEqual(validate_tool_pins(), [])

    #: Fixture versions per package, one deliberately overridable via readme_version.
    PIN_FIXTURE = {"ai-rulez": "4.11.3", "skills": "1.5.23", "markdownlint-cli2": "0.23.2"}

    def _pin_workspace(self, root: Path, *, readme_version: str) -> None:
        """A self-consistent pin workspace, derived from TOOL_PIN_SPECS.

        Hard-coding the pins here meant adding a fourth tool broke three
        unrelated tests with a message about a missing variable.
        """
        versions = dict(self.PIN_FIXTURE)
        self.assertEqual(
            set(versions), set(TOOL_PIN_SPECS), "PIN_FIXTURE must cover every pinned tool"
        )
        (root / "Makefile").write_text(
            "".join(
                f"{variable} := {versions[package]}\n"
                for package, variable in TOOL_PIN_SPECS.items()
            ),
            encoding="utf-8",
        )
        versions["ai-rulez"] = readme_version
        (root / "README.md").write_text(
            "".join(
                f"npx --yes {package}@{version} run\n"
                for package, version in versions.items()
            ),
            encoding="utf-8",
        )
        for relative in TOOL_PIN_WORKFLOWS:
            workflow = root / relative
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text("run: make check\n", encoding="utf-8")

    def test_readme_pin_must_match_the_makefile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._pin_workspace(repository, readme_version="4.10.0")

            self.assertEqual(
                validate_tool_pins(repository),
                ["ai-rulez: README documents 4.10.0, Makefile pins 4.11.3"],
            )

    def test_workflow_may_not_reintroduce_its_own_pin(self) -> None:
        """The Makefile is the only definition; a second one is the drift itself.

        Both workflows previously carried their own copy of each version, which
        is why they could disagree.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._pin_workspace(repository, readme_version="4.11.3")
            reintroduced = repository / TOOL_PIN_WORKFLOWS[0]
            reintroduced.write_text(
                "run: npx --yes ai-rulez@4.9.0 validate\n", encoding="utf-8"
            )

            self.assertEqual(
                validate_tool_pins(repository),
                [
                    f"{TOOL_PIN_WORKFLOWS[0]}: invokes ai-rulez@… directly; "
                    "call `make` so Makefile stays the only definition"
                ],
            )

    def test_every_linux_workflow_is_registered_with_the_pin_validator(self) -> None:
        """A workflow outside TOOL_PIN_WORKFLOWS could pin a package unnoticed."""
        root = Path(__file__).resolve().parents[1]
        workflows = {
            f".github/workflows/{path.name}"
            for pattern in ("*.yml", "*.yaml")  # GitHub supports both
            for path in (root / ".github/workflows").glob(pattern)
        }
        unregistered = workflows - set(TOOL_PIN_WORKFLOWS)

        self.assertEqual(
            unregistered,
            set(),
            "add these to TOOL_PIN_WORKFLOWS so validate_tool_pins scans them",
        )

    def test_workflow_may_not_reintroduce_an_indirect_pin(self) -> None:
        """The replaced form kept the version in `env:`, not next to the `@`.

        A guard that only matched a literal semver after `@` would miss the
        exact pattern this change removes.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._pin_workspace(repository, readme_version="4.11.3")
            (repository / TOOL_PIN_WORKFLOWS[0]).write_text(
                "env:\n  PIN: 4.9.0\nrun: npx --yes ai-rulez@${PIN} validate\n",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_tool_pins(repository),
                [
                    f"{TOOL_PIN_WORKFLOWS[0]}: invokes ai-rulez@… directly; "
                    "call `make` so Makefile stays the only definition"
                ],
            )

    def test_versions_agree_across_every_manifest_and_the_changelog(self) -> None:
        self.assertEqual(validate_versions(), [])

    @staticmethod
    def _version_fixture(
        root: Path,
        *,
        changelog: str = "## 9.9.9 (unreleased)\n",
        version: str = "9.9.9",
    ) -> None:
        """A self-consistent repository at 9.9.9.

        Every input has to come from `root`; an earlier version of
        `validate_versions` read the changelog from the supplied root but the
        config and manifests from the module-level one, so a fixture could
        appear to pass while comparing against the real checkout.
        """
        (root / ".ai-rulez").mkdir(parents=True, exist_ok=True)
        (root / ".ai-rulez/config.toml").write_text(
            f'[plugin]\nversion = "{version}"\n', encoding="utf-8"
        )
        (root / "CHANGELOG.md").write_text(f"# Changelog\n\n{changelog}", encoding="utf-8")
        for relative in JSON_MANIFESTS:
            manifest = root / relative
            manifest.parent.mkdir(parents=True, exist_ok=True)
            if relative in VERSIONLESS_MANIFESTS:
                body = '{"name": "infra-copilot"}'
            elif "marketplace" in relative:
                body = f'{{"plugins": [{{"version": "{version}"}}]}}'
            else:
                body = f'{{"version": "{version}"}}'
            manifest.write_text(body, encoding="utf-8")

    def test_fixture_is_read_entirely_from_the_supplied_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)

            self.assertEqual(validate_versions(repository), [])

    def test_changelog_heading_drift_is_caught(self) -> None:
        """The CHANGELOG was the one version string nothing compared."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository, changelog="## 9.9.8 (unreleased)\n")

            self.assertEqual(
                validate_versions(repository),
                ["CHANGELOG.md: version '9.9.8' != '9.9.9'"],
            )

    def test_newest_changelog_heading_must_parse(self) -> None:
        """A malformed newest heading must not fall through to an older one.

        `## 9.9.9.1` also must not pass by matching only its `9.9.9` prefix.
        """
        for changelog, reported in (
            ("## 0.3 (unreleased)\n\n## 9.9.9\n", "0.3 (unreleased)"),
            ("## 9.9.9.1 (unreleased)\n", "9.9.9.1 (unreleased)"),
        ):
            with self.subTest(changelog=changelog):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    self._version_fixture(repository, changelog=changelog)

                    self.assertEqual(
                        validate_versions(repository),
                        [
                            f"CHANGELOG.md: newest heading {reported!r} does not "
                            "start with a version"
                        ],
                    )

    def test_missing_version_field_is_reported(self) -> None:
        """Deleting the key must fail, not silently drop out of the comparison.

        `.agents/plugins/marketplace.json` is hand-authored, so it is the one
        this check exists to guard.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / ".agents/plugins/marketplace.json").write_text(
                '{"plugins": [{}]}', encoding="utf-8"
            )

            self.assertEqual(
                validate_versions(repository),
                [".agents/plugins/marketplace.json#plugins[0]: no version field found"],
            )

    def test_sibling_entry_cannot_hide_a_missing_version(self) -> None:
        """One entry losing its version must not pass because another has one."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / ".claude-plugin/marketplace.json").write_text(
                '{"plugins": [{}, {"version": "9.9.9"}]}', encoding="utf-8"
            )

            self.assertEqual(
                validate_versions(repository),
                [".claude-plugin/marketplace.json#plugins[0]: no version field found"],
            )

    def test_full_semver_is_not_reported_malformed(self) -> None:
        """Prerelease and build metadata can both appear in one version.

        `VERSION_PATTERN` allowed only one of the two, so a real release of
        0.3.0-rc.1+build.5 would have failed `make check` on the changelog.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(
                repository,
                version="9.9.9-rc.1+build.5",
                changelog="## 9.9.9-rc.1+build.5 (unreleased)\n",
            )

            self.assertEqual(validate_versions(repository), [])

    def test_malformed_manifest_does_not_mask_the_parse_error(self) -> None:
        """Version discovery must not raise over a manifest that cannot parse.

        Root `plugin.json` carries no version, so the old check never loaded
        it; traversing every manifest means an unparseable one would replace
        `collect_manifest_errors`'s diagnostic with a traceback.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / "plugin.json").write_text("{not json", encoding="utf-8")

            self.assertEqual(validate_versions(repository), [])

    def test_malformed_manifest_is_reported_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            for relative in JSON_MANIFESTS:
                manifest = repository / relative
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
            (repository / ".claude-plugin/marketplace.json").write_text(
                "{not json", encoding="utf-8"
            )

            # Path validation indexes into these manifests, so reaching it with
            # `{}` would raise KeyError and this call would never return.
            errors = collect_manifest_errors(repository)

        self.assertTrue(
            any(
                error.startswith(".claude-plugin/marketplace.json: invalid JSON")
                for error in errors
            ),
            errors,
        )


class ValidateToolchainContractTests(unittest.TestCase):
    def test_committed_pins_flow_to_hcp(self) -> None:
        self.assertEqual(validate_toolchain_contract(), [])

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not available")
    def test_repo_config_sync_check_preserves_zsh_path(self) -> None:
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")
        step = re.search(
            r"^  - id: repo-config-sync\n(?P<metadata>(?:(?!^  - id:).*(?:\n|\Z))*)",
            steps,
            re.MULTILINE,
        )
        self.assertIsNotNone(step)
        check = re.search(
            r"^    check: >-\n(?P<body>(?:      .*\n)+)",
            step.group("metadata"),
            re.MULTILINE,
        )
        self.assertIsNotNone(check)
        command = "\n".join(
            line.removeprefix("      ")
            for line in check.group("body").splitlines()
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "scripts").mkdir()
            sync_helper = repository / "scripts/sync-config.sh"
            sync_helper.write_text("#!/bin/sh\n", encoding="utf-8")
            sync_helper.chmod(0o755)
            (repository / ".infra-copilot").mkdir()
            (repository / ".infra-copilot/config.md").write_text(
                "hcp_org: test-org\n", encoding="utf-8"
            )
            for terraform_root in ("cloudflare", "github"):
                versions = repository / f"terraform/{terraform_root}/versions.tf"
                versions.parent.mkdir(parents=True)
                versions.write_text(
                    'cloud {\n  organization = "test-org"\n}\n', encoding="utf-8"
                )
            subprocess.run(
                ["git", "init", "--quiet"], cwd=repository, check=True
            )
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
                cwd=repository,
                check=True,
            )

            result = subprocess.run(
                ["zsh", "-c", command],
                cwd=repository,
                env={**os.environ, "ORG": "test-org"},
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_toolchain_bootstrap_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            text = re.sub(
                r"  - id: toolchain-pin\n(?:(?!  - id: hcp-login).)*",
                "",
                text,
                count=1,
                flags=re.DOTALL,
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(any("first phase-0 step" in error for error in errors), errors)

    def test_rejects_a_step_before_toolchain_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            text = text.replace(
                "steps:\n",
                "steps:\n"
                "  - id: premature-step\n"
                "    phase: 0\n"
                "    provider: repo\n"
                "    actor: AGENT\n"
                "    check: 'true'\n",
                1,
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(any("first phase-0 step" in error for error in errors), errors)

    def test_rejects_missing_repo_config_sync_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            text = re.sub(
                r"  - id: repo-config-sync\n(?:(?!  - id: hcp-login).)*",
                "",
                text,
                count=1,
                flags=re.DOTALL,
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("repo-config-sync contract is incomplete" in error for error in errors),
            errors,
        )

    def test_rejects_agent_running_repository_sync_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            start = text.index("  - id: repo-config-sync\n")
            end = text.index("  - id: hcp-login\n", start)
            sync_step = text[start:end].replace(
                "    actor: HUMAN\n", "    actor: AGENT\n", 1
            )
            steps.write_text(text[:start] + sync_step + text[end:], encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("repo-config-sync contract is incomplete" in error for error in errors),
            errors,
        )

    def test_rejects_zsh_special_repo_config_sync_loop_variable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8").replace(
                "for config_file in terraform/cloudflare/versions.tf",
                "for path in terraform/cloudflare/versions.tf",
                1,
            ).replace('"$config_file"', '"$path"')
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("repo-config-sync contract is incomplete" in error for error in errors),
            errors,
        )

    def test_rejects_uncommitted_repo_config_sync_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8").replace(
                "git diff --cached --quiet HEAD -- .infra-copilot/config.md",
                "true # omitted staged-state check for .infra-copilot/config.md",
                1,
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("repo-config-sync contract is incomplete" in error for error in errors),
            errors,
        )

    def test_rejects_missing_shared_config_workspace_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            hcp = repository / ".ai-rulez/skills/infra-copilot/references/hcp.md"
            text = hcp.read_text(encoding="utf-8").replace(
                '"trigger-patterns":[$dir+"/**", ".infra-copilot/config.md"]',
                '"trigger-patterns":[$dir+"/**"]',
                1,
            )
            hcp.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("workspace creation must include" in error for error in errors),
            errors,
        )

    def test_rejects_missing_shared_trigger_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            hcp = repository / ".ai-rulez/skills/infra-copilot/references/hcp.md"
            text = hcp.read_text(encoding="utf-8")
            start = text.index("  set_workspace_config () {")
            end = text.index("\n  }", start)
            reconciliation = text[start:end].replace(
                '"trigger-patterns":[$dir+"/**", ".infra-copilot/config.md"]',
                '"trigger-patterns":[$dir+"/**"]',
                1,
            )
            hcp.write_text(
                text[:start] + reconciliation + text[end:], encoding="utf-8"
            )

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("trigger patterns must be" in error for error in errors), errors
        )

    def test_rejects_status_report_without_repo_config_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            status = repository / ".ai-rulez/skills/status/SKILL.md"
            text = status.read_text(encoding="utf-8").replace(
                "  ✓ repo-config-sync", "", 1
            )
            status.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("phase-0 report must include" in error for error in errors), errors
        )

    def test_rejects_toolchain_step_check_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            start = text.index("  - id: toolchain-pin\n")
            end = text.index("  - id: hcp-login\n", start)
            bootstrap = text[start:end].replace(
                "      mise --version >/dev/null &&\n",
                "      mise --version >/dev/null 2>&1 &&\n",
                1,
            )
            steps.write_text(text[:start] + bootstrap + text[end:], encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("must match the mise preflight check" in error for error in errors),
            errors,
        )

    def test_rejects_missing_mise_preflight_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            text = re.sub(
                r"  - tool: mise\n(?:(?!  - tool: terraform).)*",
                "",
                text,
                count=1,
                flags=re.DOTALL,
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("missing mise preflight check" in error for error in errors), errors
        )

    def test_rejects_shell_specific_pin_word_splitting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
            )
            text = steps.read_text(encoding="utf-8")
            portable = (
                "printf '%s\\n' \"$pinned\" |\n"
                "      while IFS= read -r tool; do\n"
                "      [ -z \"$tool\" ] && continue;\n"
                "      MISE_LOCKED=1 mise install --dry-run \"$tool\" "
                ">/dev/null 2>&1 || exit 1;\n"
                "      done"
            )
            text = text.replace(
                portable,
                "MISE_LOCKED=1 mise install --dry-run $pinned >/dev/null 2>&1",
            )
            steps.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("shell-specific word splitting" in error for error in errors), errors
        )

    def test_rejects_active_mise_state_and_unlocked_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            references = repository / ".ai-rulez/skills/infra-copilot/references"
            steps = references / "steps.yaml"
            hcp = references / "hcp.md"
            setup = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/docs/setup.md"
            )
            import_guide = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/docs/import.md"
            )
            config = (
                repository
                / ".ai-rulez/skills/infra-copilot/references/config.md"
            )
            status = repository / ".ai-rulez/skills/status/SKILL.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True)
            steps.write_text("pin=$(mise current terraform)", encoding="utf-8")
            hcp.write_text("terraform-version", encoding="utf-8")
            setup.write_text("mise trust mise.toml", encoding="utf-8")
            import_guide.write_text("", encoding="utf-8")
            config.write_text(
                "export TERRAFORM_VERSION=$(mise config get)", encoding="utf-8"
            )
            status.write_text("", encoding="utf-8")
            (references / "docs/ci.md").write_text("", encoding="utf-8")
            (references / "decisions.md.example").write_text("", encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(any("active mise state" in error for error in errors), errors)
        self.assertTrue(
            any("MISE_LOCKED=1 mise install" in error for error in errors), errors
        )
        self.assertTrue(
            any("review must precede trust" in error for error in errors), errors
        )
        self.assertTrue(any("MISE_LOCKED=1" in error for error in errors), errors)
        self.assertTrue(any("before preflight" in error for error in errors), errors)
        self.assertTrue(any("without pin state" in error for error in errors), errors)

    def test_rejects_unlocked_conditional_tools_and_unactivated_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            references = repository / ".ai-rulez/skills/infra-copilot/references"
            steps = references / "steps.yaml"
            hcp = references / "hcp.md"
            setup = references / "docs/setup.md"
            import_guide = references / "docs/import.md"
            config = references / "config.md"
            status = repository / ".ai-rulez/skills/status/SKILL.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True)
            # A fixed tool list leaves conditionally configured tools unvalidated.
            steps.write_text(
                "MISE_LOCKED=1 mise install --dry-run terraform gh jq", encoding="utf-8"
            )
            hcp.write_text("terraform-version", encoding="utf-8")
            # Installs the toolchain but never activates it or uses `mise exec`.
            setup.write_text(
                "cat -- mise.toml\nmise trust mise.toml\ntouch mise.lock\n"
                "mise lock\nMISE_LOCKED=1 mise install\n",
                encoding="utf-8",
            )
            # Installs cf-terraforming as it writes the pin, before the lock exists.
            import_guide.write_text(
                "mise use --path mise.toml github:cloudflare/cf-terraforming@0.27.0\n"
                "mise lock\ngit add mise.toml mise.lock\n"
                # Bare invocation, and terraform resolved by the outer shell.
                'cf-terraforming generate --terraform-binary-path "$(which terraform)"\n',
                encoding="utf-8",
            )
            config.write_text("", encoding="utf-8")
            status.write_text("", encoding="utf-8")
            # CI picks its own Terraform, and the decision claims parity anyway.
            (references / "docs/ci.md").write_text(
                "- uses: hashicorp/setup-terraform@v3\n", encoding="utf-8"
            )
            (references / "decisions.md.example").write_text(
                "| Toolchain | pins | locked | Same versions locally, in CI |\n",
                encoding="utf-8",
            )

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("enumerate the committed tool list" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("must be activated" in error for error in errors), errors
        )
        self.assertTrue(
            any("installs the pin before locking" in error for error in errors), errors
        )
        self.assertTrue(
            any("instead of the merged config" in error for error in errors), errors
        )
        self.assertTrue(
            any("through the pinned environment" in error for error in errors), errors
        )
        self.assertTrue(
            any("not the outer shell" in error for error in errors), errors
        )
        self.assertTrue(
            any("must be an exact version" in error for error in errors), errors
        )
        self.assertTrue(
            any("repository-pinned toolchain" in error for error in errors), errors
        )
        self.assertTrue(
            any("workflow that backs it" in error for error in errors), errors
        )

    # The manifest's `check` snippets are POSIX shell by contract, and this test
    # proves them by executing them against shell fixtures. Windows has no
    # /bin/sh, so the assertion is unrunnable there rather than failing.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_tool_checks_reject_non_exact_selectors(self) -> None:
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")

        def check_for(tool: str) -> str:
            match = re.search(
                rf"  - tool: {tool}\n(?:(?!  - tool:).*\n)*?    check: >-\n"
                rf"(?P<body>(?:      [^\n]*\n)+)",
                steps,
                re.MULTILINE,
            )
            self.assertIsNotNone(match)
            return "\n".join(
                line[6:] for line in match.group("body").splitlines()
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            binary_directory = Path(temporary_directory)
            scripts = {
                "mise": """#!/bin/sh
if [ "$1" = config ]; then printf '%s\n' "$PIN"; else exit 0; fi
""",
                "terraform": """#!/bin/sh
printf '%s\n' '{"terraform_version":"1.15.9"}'
""",
                "gh": """#!/bin/sh
printf '%s\n' 'gh version 2.81.0 (fixture)'
""",
                "jq": """#!/bin/sh
if [ "$1" = --version ]; then printf '%s\n' 'jq-1.8.1';
else cat >/dev/null; printf '%s\n' '1.15.9'; fi
""",
            }
            for name, body in scripts.items():
                executable = binary_directory / name
                executable.write_text(body, encoding="utf-8")
                executable.chmod(0o755)

            environment = os.environ | {
                "PATH": f"{binary_directory}:/usr/bin:/bin",
            }
            exact = {"terraform": "1.15.9", "gh": "2.81.0", "jq": "1.8.1"}
            for tool, version in exact.items():
                command = check_for(tool)
                passing = subprocess.run(
                    ["/bin/sh", "-c", command],
                    env=environment | {"PIN": version},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                self.assertEqual(passing.returncode, 0, tool)
                for selector in ("latest", ">=1.9", "1.15"):
                    rejected = subprocess.run(
                        ["/bin/sh", "-c", command],
                        env=environment | {"PIN": selector},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    self.assertNotEqual(rejected.returncode, 0, (tool, selector))


    # Executed against shell fixtures, so POSIX-only for the same reason as above.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_lock_check_covers_every_configured_tool(self) -> None:
        """The locked dry-run must cover conditionally added tools, not a fixed set."""
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"  - tool: mise\n    check: >-\n(?P<body>(?:      [^\n]*\n)+)", steps
        )
        self.assertIsNotNone(match)
        check = " ".join(
            line[6:] for line in match.group("body").splitlines()
        )

        # `mise install` here stands in for the real locked install: it fails for any
        # requested tool absent from LOCKED, exactly as --locked fails for a tool with
        # no lockfile entry for the current platform.
        fixture_mise = """#!/bin/sh
case "$1" in
  --version) exit 0 ;;
  config) sed -n '/^\\[tools\\]/,$p' ./mise.toml | sed '1d' ;;
  install)
    shift 2
    for requested in "$@"; do
      found=1
      for locked in $LOCKED; do
        [ "$requested" = "$locked" ] && found=0
      done
      [ "$found" = 0 ] || exit 1
    done
    ;;
esac
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            binaries = repository / "bin"
            binaries.mkdir()
            executable = binaries / "mise"
            executable.write_text(fixture_mise, encoding="utf-8")
            executable.chmod(0o755)
            # gcloud is the conditional pin: configured, but absent from the lock.
            committed_mise = (
                '[tools]\nterraform = "1.15.9"\ngh = "2.81.0"\njq = "1.8.1"\n'
                'gcloud = "551.0.0"\n'
            )
            (repository / "mise.toml").write_text(committed_mise, encoding="utf-8")
            (repository / "mise.lock").write_text("# @generated\n", encoding="utf-8")
            # A contributor's global config (commit.gpgsign, core.hooksPath, a
            # gpg.format) would otherwise fail these commits and error the test for
            # a reason unrelated to the contract under test.
            git = os.environ | {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
            }
            for command in (
                ["git", "init", "-q"],
                ["git", "add", "mise.toml", "mise.lock"],
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=test",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "pins",
                ],
            ):
                subprocess.run(command, cwd=repository, env=git, check=True)

            def run(locked: str) -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {
                        "PATH": f"{binaries}:/usr/bin:/bin",
                        "LOCKED": locked,
                    },
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            # The old fixed list would have passed this: gcloud is configured but
            # has no lock data, so a fresh clone's locked install would fail.
            self.assertNotEqual(run("terraform gh jq"), 0)
            # Withhold the *first* key's lock data too, so a check that drops a tool
            # from either end of the enumerated list is caught.
            self.assertNotEqual(run("gh jq gcloud"), 0)
            self.assertEqual(run("terraform gh jq gcloud"), 0)

            # `git diff HEAD` reads the final working-tree content. If a different
            # pin is staged and the file is then restored to HEAD, only --cached
            # detects that the next commit would carry an unchecked version.
            (repository / "mise.toml").write_text(
                committed_mise.replace("1.15.9", "1.15.10"), encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "mise.toml"], cwd=repository, env=git, check=True
            )
            (repository / "mise.toml").write_text(committed_mise, encoding="utf-8")
            self.assertNotEqual(run("terraform gh jq gcloud"), 0)
            subprocess.run(
                ["git", "add", "mise.toml"], cwd=repository, env=git, check=True
            )

            # A floating selector must fail even when the lock is refreshed and
            # every tool therefore resolves: the contract is exact pins, and only
            # terraform/gh/jq/gcloud have dedicated per-tool checks.
            for selector in ("latest", "0.27", ">=0.27"):
                (repository / "mise.toml").write_text(
                    '[tools]\nterraform = "1.15.9"\ngh = "2.81.0"\njq = "1.8.1"\n'
                    'gcloud = "551.0.0"\n'
                    f'"github:cloudflare/cf-terraforming" = "{selector}"\n',
                    encoding="utf-8",
                )
                subprocess.run(["git", "add", "-A"], cwd=repository, env=git, check=True)
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.email=test@example.com",
                        "-c",
                        "user.name=test",
                        "-c",
                        "commit.gpgsign=false",
                        "commit",
                        "-qm",
                        selector,
                    ],
                    cwd=repository,
                    env=git,
                    check=True,
                )
                self.assertNotEqual(
                    run("terraform gh jq gcloud github:cloudflare/cf-terraforming"),
                    0,
                    selector,
                )

            # An unpinned repository must not pass on file presence alone.
            (repository / "mise.toml").write_text("[tools]\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repository, env=git, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=test",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "empty",
                ],
                cwd=repository,
                env=git,
                check=True,
            )
            self.assertNotEqual(run("terraform gh jq gcloud"), 0)


    # Needs a real jq, since the point of the assertion is which JSON field the
    # check asks for. POSIX-only for the same reason as the checks above.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_gcloud_check_reads_the_sdk_version_field(self) -> None:
        """`core` is a release date; the pin matches the Google Cloud SDK field."""
        jq = shutil.which("jq")
        if jq is None:
            self.skipTest("jq is required to exercise the gcloud check")
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"  - tool: gcloud\n(?:(?!  - tool:).*\n)*?    check: >-\n"
            r"(?P<body>(?:      [^\n]*\n)+)",
            steps,
        )
        self.assertIsNotNone(match)
        check = " ".join(line[6:] for line in match.group("body").splitlines())

        # Verbatim shape of `gcloud version --format=json` from SDK 551.0.0: the
        # component named `core` carries a release date, not the SDK version.
        fixture_gcloud = """#!/bin/sh
cat <<'JSON'
{
  "Google Cloud SDK": "551.0.0",
  "bq": "2.1.26",
  "core": "2026.01.02",
  "gcloud-crc32c": "1.0.0",
  "gsutil": "5.35"
}
JSON
"""
        fixture_mise = """#!/bin/sh
[ "$1" = config ] && printf '%s\\n' "$PIN"
exit 0
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            binaries = repository / "bin"
            binaries.mkdir()
            for name, body in (("gcloud", fixture_gcloud), ("mise", fixture_mise)):
                executable = binaries / name
                executable.write_text(body, encoding="utf-8")
                executable.chmod(0o755)
            (binaries / "jq").symlink_to(jq)

            def run(pin: str) -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {"PATH": f"{binaries}:/usr/bin:/bin", "PIN": pin},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            # Without terraform/gcp the pin is not yet required.
            self.assertEqual(run("551.0.0"), 0)

            (repository / "terraform/gcp").mkdir(parents=True)
            # The regression: matching pin and installed SDK must agree. Reading
            # `core.version` yielded an empty string and kept this red.
            self.assertEqual(run("551.0.0"), 0)
            # Drift, the release date mistaken for a version, and non-exact
            # selectors all have to fail.
            for pin in ("550.0.0", "2026.01.02", "latest", ">=551", "551"):
                self.assertNotEqual(run(pin), 0, pin)


if __name__ == "__main__":
    unittest.main()
