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
    RELEASE_PLEASE_CONFIG,
    MAX_DESCRIPTION_BUDGET,
    VERSIONLESS_MANIFESTS,
    collect_manifest_errors,
    skill_descriptions,
    CONFIG_FALLBACK_DOCUMENTS,
    validate_config_fallbacks,
    _looks_like_marker,
    frontmatter_bounds,
    validate_customization_markers,
    validate_description_budget,
    validate_json_manifests,
    validate_links,
    validate_manifest_paths,
    validate_phase_five_rule,
    validate_release_please,
    validate_toolchain_contract,
    audited_version,
    validate_shipped_check_paths,
    validate_exact_pins,
    validate_skill_sections,
    validate_version_locations,
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
    def test_canonical_entrypoints_document_the_readme_config_and_unsupported_legacy(self) -> None:
        self.assertEqual(validate_config_fallbacks(), [])

    def test_a_skill_that_does_not_say_legacy_state_is_unsupported_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            for relative in CONFIG_FALLBACK_DOCUMENTS:
                document = repository / relative
                document.parent.mkdir(parents=True, exist_ok=True)
                document.write_text(
                    "Load the README Config block. .infra-copilot/ and "
                    ".claude/infra-copilot.local.md are read as a fallback.\n",
                    encoding="utf-8",
                )

            errors = validate_config_fallbacks(repository)

        self.assertEqual(len(errors), len(CONFIG_FALLBACK_DOCUMENTS))
        self.assertTrue(all("'unsupported'" in error for error in errors), errors)


class CustomizationMarkerTests(unittest.TestCase):
    """The markers are comments, so this validator is their only enforcement."""

    REFERENCES = ".ai-rulez/skills/infra/references"

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
                "---\n# infra:customization start\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                'hcp_status_check_id: ""\n'
                "# infra:customization end\n---\n"
            ),
            "decisions.md.example": (
                "<!-- infra:customization start -->\n"
                "| Decision | Choice | Status | Rationale |\n"
                "<!-- infra:customization end -->\n"
            ),
            "config.md": "preserve it verbatim. Never merge by inference. refuse to edit anything outside them.\n",
        }
        defaults.update(files)
        for name, body in defaults.items():
            document = repository / self.REFERENCES / name
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text(body, encoding="utf-8")
        return repository

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
                        "---\n# infra:customization start\n"
                        "# infra:customization end\n"
                        "leaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\nhcp_status_check_id: \"\"\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: {key!r} is outside the "
                    "infra:customization region a re-scaffold preserves"
                    for key in (
                        "leaf_backends:",
                        "state_transfers:",
                        "github_apps:",
                        "hcp_status_check_id:",
                        "additional_providers:",
                    )
                ],
            )

    def test_rejects_any_fenced_block_in_the_template(self) -> None:
        """The document is refused rather than interpreted.

        Deciding whether a fence neutralises the markers, the required content,
        or neither means implementing Markdown; five review rounds found five
        defects in trying. These templates have never needed a fence.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "```\n<!-- infra:customization start -->\n"
                        "| Decision | Choice | Status | Rationale |\n"
                        "<!-- infra:customization end -->\n```\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: line 1 opens or "
                    "closes a code fence; this template may not contain fenced "
                    "blocks, because whether a fence neutralises the markers "
                    "cannot be decided without a Markdown parser",
                    f"{self.REFERENCES}/decisions.md.example: line 5 opens or "
                    "closes a code fence; this template may not contain fenced "
                    "blocks, because whether a fence neutralises the markers "
                    "cannot be decided without a Markdown parser",
                ],
            )

    def test_rejects_a_fence_around_only_the_required_content(self) -> None:
        """Both markers valid and unfenced; the table alone inside a fence.

        The substring check on the region found the header regardless, so this
        shape passed while Markdown rendered the table as code.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "<!-- infra:customization start -->\n```\n"
                        "| Decision | Choice | Status | Rationale |\n```\n"
                        "<!-- infra:customization end -->\n"
                    )
                },
            )

            self.assertEqual(
                len(validate_customization_markers(repository)),
                2,
                "both fence delimiters should be reported",
            )

    def test_rejects_indented_required_content(self) -> None:
        """An indented field is a nested YAML key, not the field itself."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra:customization start\n"
                        "leaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n  hcp_status_check_id: \"\"\n"
                        "# infra:customization end\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'hcp_status_check_id:' "
                    "is outside the infra:customization region a "
                    "re-scaffold preserves"
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
                        "    <!-- infra:customization start -->\n"
                        "    | Decision | Choice | Status | Rationale |\n"
                        "    <!-- infra:customization end -->\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra:customization marker on line 1 is indented; "
                    "markers must start at column 0, or Markdown reads the region "
                    "as a code block",
                    f"{self.REFERENCES}/decisions.md.example: "
                    "infra:customization marker on line 3 is indented; "
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
                        "---\ninfra:customization start\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                        'hcp_status_check_id: ""\n'
                        "# infra:customization end\n---\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: line 2 carries "
                    "infra:customization but is not a well-formed comment "
                    "marker: 'infra:customization start'"
                ],
            )

    def test_rejects_the_other_file_s_comment_syntax(self) -> None:
        """An HTML comment is inert inside YAML frontmatter, and vice versa."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "decisions.md.example": (
                        "# infra:customization start\n| a |\n"
                        "<!-- infra:customization end -->\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/decisions.md.example: line 1 carries "
                    "infra:customization but is not a well-formed comment "
                    "marker: '# infra:customization start'"
                ],
            )

    def test_rejects_a_marker_outside_the_frontmatter_delimiters(self) -> None:
        """Frontmatter intact, but the region spills past its closing ---."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "---\n# infra:customization start\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                        'hcp_status_check_id: ""\n---\n'
                        "# infra:customization end\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: "
                    "infra:customization marker on line 9 is outside the "
                    "frontmatter delimiters (lines 1 and 8), so the preserved "
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
                        "# infra:customization start\n---\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                        'hcp_status_check_id: ""\n'
                        "# infra:customization end\n---\n"
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
                        "Keep the two `infra:customization` comments.\n"
                        "<!-- infra:customization start -->\n"
                        "| Decision | Choice | Status | Rationale |\n"
                        "<!-- infra:customization end -->\n"
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
                        "---\n# infra:customization start\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                        "# infra:customization end\n"
                        'hcp_status_check_id: ""\n---\n'
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: 'hcp_status_check_id:' is "
                    "outside the infra:customization region a re-scaffold "
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
                **{"config.md.example": "---\n# infra:customization start\n---\n"},
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: expected exactly one "
                    "infra:customization pair, found 1 start and 0 end"
                ],
            )

    def test_rejects_a_duplicated_start(self) -> None:
        """Two starts are balanced by a naive count of the token alone."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "# infra:customization start\n"
                        "# infra:customization start\n"
                        "# infra:customization end\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: expected exactly one "
                    "infra:customization pair, found 2 start and 1 end"
                ],
            )

    def test_rejects_an_end_before_its_start(self) -> None:
        """One of each, so counting alone calls this file well-formed."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{
                    "config.md.example": (
                        "# infra:customization end\nleaf_backends: {}\nstate_transfers: {}\ngithub_apps: {}\nadditional_providers: []\n"
                        "# infra:customization start\n"
                    )
                },
            )

            self.assertEqual(
                validate_customization_markers(repository),
                [
                    f"{self.REFERENCES}/config.md.example: "
                    "infra:customization end precedes its start"
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
                    f"{self.REFERENCES}/config.md: re-scaffold rule missing "
                    "'refuse to edit anything outside them'",
                ],
            )

    def test_accepts_a_rule_whose_phrase_wraps_across_lines(self) -> None:
        """Prose re-wraps on edit; a raw-text match would report a false failure."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = self._repository(
                temporary_directory,
                **{"config.md": "preserve it\nverbatim. **Never merge by\ninference.** And refuse to edit\nanything outside them.\n"},
            )

            self.assertEqual(validate_customization_markers(repository), [])


class LooksLikeMarkerTests(unittest.TestCase):
    """Which lines count as an attempted marker, and so as malformed."""

    def test_a_bare_token_counts(self) -> None:
        self.assertTrue(_looks_like_marker("infra:customization start"))

    def test_the_wrong_comment_syntax_counts(self) -> None:
        self.assertTrue(_looks_like_marker("# infra:customization start"))
        self.assertTrue(
            _looks_like_marker("<!-- infra:customization end -->")
        )

    def test_explanatory_prose_inside_a_comment_does_not_count(self) -> None:
        """The token and edge must follow the prefix, not appear anywhere."""
        self.assertFalse(
            _looks_like_marker(
                "<!-- Use infra:customization start before editing. -->"
            )
        )
        self.assertFalse(
            _looks_like_marker("# Keep infra:customization end in place")
        )

    def test_prose_opening_with_the_bare_token_does_not_count(self) -> None:
        """An edge is required after a bare token, as after a comment prefix.

        Without it, a sentence starting with the token was reported as a
        malformed marker and blocked the check -- a false positive on a
        document whose real markers were fine.
        """
        self.assertFalse(
            _looks_like_marker(
                "infra:customization comments delimit user values."
            )
        )

    def test_prose_naming_the_token_without_an_edge_does_not_count(self) -> None:
        self.assertFalse(
            _looks_like_marker("Keep the two `infra:customization` comments.")
        )




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
            document = (
                repository
                / ".ai-rulez/skills/infra/references/status.md"
            )
            document.parent.mkdir(parents=True)
            document.write_text(
                "Infer done from the workspace's latest HCP run being clean.",
                encoding="utf-8",
            )

            self.assertEqual(
                validate_phase_five_rule(repository),
                [
                    ".ai-rulez/skills/infra/references/status.md: phase-5 completion rule "
                    "missing 'imports: 0'",
                    ".ai-rulez/skills/infra/references/status.md: phase-5 completion rule "
                    "missing 'incomplete'",
                    ".ai-rulez/skills/infra/references/status.md: phase-5 completion rule "
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
            manifest = repository / "skills/infra/references/steps.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                'preflight:\n  - tool: infra-references\n'
                'steps:\n  - check: sh "$INFRA_REFERENCES/checks/gone.sh"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                validate_shipped_check_paths(repository),
                [
                    "skills/infra/references/steps.yaml: check references "
                    "$INFRA_REFERENCES/checks/gone.sh, which does not exist"
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
                    references = repository / "skills/infra/references"
                    (references / "checks").mkdir(parents=True)
                    (references / "steps.yaml").write_text(
                        "preflight:\n  - tool: infra-references\n"
                        f'steps:\n  - check: sh "$INFRA_REFERENCES/{payload}"\n',
                        encoding="utf-8",
                    )

                    errors = validate_shipped_check_paths(repository)

                    self.assertEqual(len(errors), 1, errors)
                    self.assertIn("resolves outside", errors[0])

    def test_shipped_check_without_a_preflight_guard_is_reported(self) -> None:
        """The export is the precondition; a check that needs it must be gated."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            references = repository / "skills/infra/references"
            (references / "checks").mkdir(parents=True)
            (references / "checks/present.sh").write_text("exit 0\n", encoding="utf-8")
            (references / "steps.yaml").write_text(
                'steps:\n  - check: sh "$INFRA_REFERENCES/checks/present.sh"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                validate_shipped_check_paths(repository),
                [
                    "skills/infra/references/steps.yaml: a check resolves a "
                    "shipped script but preflight has no infra-references guard"
                ],
            )


class LintScopeTests(unittest.TestCase):
    """The canonical sources must be linted, with width relaxed only there."""

    def test_root_config_lints_the_canonical_sources(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = (root / ".config/.markdownlint-cli2.jsonc").read_text(encoding="utf-8")
        self.assertIn(".ai-rulez/**/*.md", config)

    def test_nested_config_relaxes_only_line_width(self) -> None:
        """Deleting this file silently reintroduces 119 findings, so pin its purpose.

        `npm run lint` is the real enforcement — it fails loudly if a future
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
        self.assertIn("infra-skills:infra-import", descriptions["infra-add"])
        self.assertIn("infra-skills:infra-add", descriptions["infra-import"])
        self.assertIn("infra-skills:infra-import", descriptions["infra-setup"])
        self.assertIn("Read-only", descriptions["infra-status"])


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

    def test_repository_tool_pins_are_exact(self) -> None:
        self.assertEqual(validate_exact_pins(), [])

    def test_a_range_is_not_a_pin(self) -> None:
        for specifier in ("^5.3.0", "~5.3.0", ">=5.3.0", "5.3", "latest", "*"):
            with self.subTest(specifier=specifier):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    (repository / "package.json").write_text(
                        json.dumps({"devDependencies": {"ai-rulez": specifier}}),
                        encoding="utf-8",
                    )

                    self.assertEqual(
                        validate_exact_pins(repository),
                        [
                            f"ai-rulez: package.json pins {specifier!r}; "
                            "use an exact version, not a range"
                        ],
                    )

    def test_an_exact_version_is_a_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "package.json").write_text(
                json.dumps({"devDependencies": {"ai-rulez": "5.3.0", "skills": "1.5.23"}}),
                encoding="utf-8",
            )

            self.assertEqual(validate_exact_pins(repository), [])

    def test_missing_dev_dependencies_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            (repository / "package.json").write_text("{}", encoding="utf-8")

            self.assertEqual(
                validate_exact_pins(repository),
                ["package.json: missing a devDependencies table"],
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
        (root / "package.json").write_text(
            json.dumps({"version": version}), encoding="utf-8"
        )
        (root / "CHANGELOG.md").write_text(f"# Changelog\n\n{changelog}", encoding="utf-8")
        for relative in JSON_MANIFESTS:
            manifest = root / relative
            manifest.parent.mkdir(parents=True, exist_ok=True)
            if relative in VERSIONLESS_MANIFESTS:
                body = '{"name": "infra"}'
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

        The Codex marketplace is generated without a version and is skipped, so
        the Claude marketplace stands in for a manifest that carries one.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / ".claude-plugin/marketplace.json").write_text(
                '{"plugins": [{}]}', encoding="utf-8"
            )

            self.assertEqual(
                validate_versions(repository),
                [".claude-plugin/marketplace.json#plugins[0]: no version field found"],
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
        0.3.0-rc.1+build.5 would have failed `npm run check` on the changelog.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(
                repository,
                version="9.9.9-rc.1+build.5",
                changelog="## 9.9.9-rc.1+build.5 (unreleased)\n",
            )

            self.assertEqual(validate_versions(repository), [])

    def test_release_please_headings_are_read(self) -> None:
        """release-please links the version, and writes a patch release at `###`.

        Its `## [X.Y.Z](…) (date)` heading failed the old `## <version>` match, so
        every release PR would have failed `npm run check`.
        """
        link = "https://github.com/o/r/compare/v9.9.8...v9.9.9"
        for changelog in (
            f"## [9.9.9]({link}) (2026-09-24)\n\n### Features\n\n* x\n",
            f"### [9.9.9]({link}) (2026-09-24)\n\n### Bug Fixes\n\n## 9.9.8\n",
            f"## [9.9.9]({link}) (2026-09-24)\n\n## 9.9.9 (unreleased)\n",
        ):
            with self.subTest(changelog=changelog):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    self._version_fixture(repository, changelog=changelog)

                    self.assertEqual(validate_versions(repository), [])

    def test_section_heading_is_not_a_release(self) -> None:
        """`### Features` above a release heading must not hide drift below it."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(
                repository, changelog="### Features\n\n## [9.9.8](u) (2026-09-24)\n"
            )

            self.assertEqual(
                validate_versions(repository),
                ["CHANGELOG.md: version '9.9.8' != '9.9.9'"],
            )

    def test_newer_patch_heading_wins_over_an_older_minor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(
                repository, changelog="### [9.9.10](u) (2026-09-24)\n\n## [9.9.9](u)\n"
            )

            self.assertEqual(
                validate_versions(repository),
                ["CHANGELOG.md: version '9.9.10' != '9.9.9'"],
            )

    def test_malformed_linked_heading_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository, changelog="## [9.9](u)\n\n## 9.9.9\n")

            self.assertEqual(
                validate_versions(repository),
                ["CHANGELOG.md: newest heading '[9.9](u)' does not start with a version"],
            )

    def test_release_please_bumps_every_compared_copy(self) -> None:
        self.assertEqual(validate_release_please(), [])

    @staticmethod
    def _release_please_fixture(root: Path, extra_files: object) -> None:
        """The version fixture plus a release-please config with `extra_files`."""
        ValidateReleaseSurfacesTests._version_fixture(root)
        (root / RELEASE_PLEASE_CONFIG).write_text(
            json.dumps({"packages": {".": {"extra-files": extra_files}}}),
            encoding="utf-8",
        )

    @staticmethod
    def _real_extra_files() -> list[dict[str, str]]:
        config = json.loads(
            (Path(__file__).resolve().parents[1] / RELEASE_PLEASE_CONFIG)
            .read_text(encoding="utf-8")
        )
        return config["packages"]["."]["extra-files"]

    def test_release_please_fixture_passes_with_the_real_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._release_please_fixture(repository, self._real_extra_files())

            self.assertEqual(validate_release_please(repository), [])

    def test_release_please_missing_or_wrong_extra_file_is_reported(self) -> None:
        """A version nothing bumps would fail only on the release PR itself.

        release-please skips a jsonpath that matches nothing, or a file parsed as
        the wrong type, with only a log warning -- so both count as missing.
        """
        target = ".claude-plugin/marketplace.json"
        for change in (
            lambda entry: None,
            lambda entry: {**entry, "jsonpath": "$.plugins[0].verison"},
            lambda entry: {**entry, "type": "toml"},
        ):
            extra_files = [
                change(entry) if entry["path"] == target else entry
                for entry in self._real_extra_files()
            ]
            with self.subTest(extra_files=extra_files):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    self._release_please_fixture(
                        repository, [entry for entry in extra_files if entry]
                    )

                    self.assertEqual(
                        validate_release_please(repository),
                        [
                            "release-please-config.json: extra-files has no "
                            f"json entry for {target} at $.plugins[0].version, so the "
                            "release PR would leave that version behind and fail "
                            "validate_versions"
                        ],
                    )

    def test_release_please_malformed_config_is_reported_not_raised(self) -> None:
        for config in ('{"packages": []}', '{"packages": {".": "x"}}', "[]"):
            with self.subTest(config=config):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repository = Path(temporary_directory)
                    (repository / RELEASE_PLEASE_CONFIG).write_text(
                        config, encoding="utf-8"
                    )

                    self.assertEqual(
                        validate_release_please(repository),
                        ['release-please-config.json: no object at packages["."]'],
                    )

    def test_repository_spells_the_plugin_version_only_where_it_is_compared(
        self,
    ) -> None:
        self.assertEqual(validate_version_locations(), [])

    def test_version_outside_the_compared_files_is_reported(self) -> None:
        """A non-JSON copy was invisible: validate_versions reads known shapes (#22)."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / "docs").mkdir()
            (repository / "docs/install.md").write_text(
                "# Install\n\nnpx skills add infra-skills@9.9.9\n", encoding="utf-8"
            )
            (repository / "README.md").write_text(
                '<img src="badge/v9.9.9">\n', encoding="utf-8"
            )

            self.assertEqual(
                validate_version_locations(repository),
                [
                    f"{path}: carries the plugin version '9.9.9', which nothing "
                    "keeps in step; drop it, or teach validate_versions to compare "
                    "it and add it to VERSIONED_FILES (UNRELATED_VERSION_FILES if "
                    "the match is a coincidence)"
                    for path in ("README.md:1", "docs/install.md:3")
                ],
            )

    def test_compared_files_and_neighbouring_versions_are_not_reported(self) -> None:
        """Only the exact version counts, and only outside registered files."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / "NOTES.md").write_text(
                "19.9.9 9.9.9.1 9.9.9-rc.1 9.9.9+build v8.9.9.9\n", encoding="utf-8"
            )
            (repository / "package-lock.json").write_text(
                '{"packages": {"node_modules/x": {"version": "9.9.9"}}}',
                encoding="utf-8",
            )
            (repository / "node_modules/x").mkdir(parents=True)
            (repository / "node_modules/x/package.json").write_text(
                '{"version": "9.9.9"}', encoding="utf-8"
            )
            (repository / "logo.png").write_bytes(b"\x89PNG\xff9.9.9")

            self.assertEqual(validate_version_locations(repository), [])

    def test_only_tracked_files_are_scanned_in_a_work_tree(self) -> None:
        """A local .venv or gitignored build output must not fail `npm run check`.

        CI checks a clean clone, so scanning the whole disk made a maintainer's
        checkout fail on files that are not part of the repository.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            self._version_fixture(repository)
            (repository / ".gitignore").write_text("/ignored/\n", encoding="utf-8")
            (repository / "tracked.md").write_text("v9.9.9\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            (repository / "ignored").mkdir()
            (repository / "ignored/METADATA").write_text(
                "Version: 9.9.9\n", encoding="utf-8"
            )
            (repository / "untracked.md").write_text("9.9.9\n", encoding="utf-8")

            self.assertEqual(
                [
                    error.split(":", 1)[0]
                    for error in validate_version_locations(repository)
                ],
                ["tracked.md"],
            )

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

    def test_rejects_missing_toolchain_bootstrap_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra/references/steps.yaml"
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
                / ".ai-rulez/skills/infra/references/steps.yaml"
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

    def test_rejects_missing_shared_config_workspace_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            hcp = repository / ".ai-rulez/skills/infra/references/hcp.md"
            text = hcp.read_text(encoding="utf-8").replace(
                '"trigger-patterns":[$dir+"/**", "terraform/modules/**", "README.md", "mise.toml"]',
                '"trigger-patterns":[$dir+"/**"]',
                1,
            )
            hcp.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("workspace creation must include" in error for error in errors),
            errors,
        )

    def test_rejects_missing_shared_config_workspace_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            check = (
                repository
                / ".ai-rulez/skills/infra/references/checks/hcp-bootstrap-workspaces.sh"
            )
            text = check.read_text(encoding="utf-8").replace(
                'index("README.md") != null',
                'index("terraform.tfvars") != null',
                1,
            )
            check.write_text(text, encoding="utf-8")

            errors = validate_toolchain_contract(repository)

        self.assertTrue(
            any("every HCP workspace must watch" in error for error in errors), errors
        )

    def test_rejects_missing_shared_trigger_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            hcp = repository / ".ai-rulez/skills/infra/references/hcp.md"
            text = hcp.read_text(encoding="utf-8")
            start = text.index("  set_workspace_config () {")
            end = text.index("\n  }", start)
            reconciliation = text[start:end].replace(
                '"trigger-patterns":[$dir+"/**", "terraform/modules/**", "README.md", "mise.toml"]',
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

    def test_rejects_toolchain_step_check_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shutil.copytree(
                Path(__file__).parents[1] / ".ai-rulez",
                repository / ".ai-rulez",
            )
            steps = (
                repository
                / ".ai-rulez/skills/infra/references/steps.yaml"
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
                / ".ai-rulez/skills/infra/references/steps.yaml"
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
                / ".ai-rulez/skills/infra/references/steps.yaml"
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
            references = repository / ".ai-rulez/skills/infra/references"
            steps = references / "steps.yaml"
            hcp = references / "hcp.md"
            setup = (
                repository
                / ".ai-rulez/skills/infra/references/docs/setup.md"
            )
            import_guide = (
                repository
                / ".ai-rulez/skills/infra/references/docs/import.md"
            )
            config = (
                repository
                / ".ai-rulez/skills/infra/references/config.md"
            )
            status = references / "status.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True, exist_ok=True)
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
            references = repository / ".ai-rulez/skills/infra/references"
            steps = references / "steps.yaml"
            hcp = references / "hcp.md"
            setup = references / "docs/setup.md"
            import_guide = references / "docs/import.md"
            config = references / "config.md"
            status = references / "status.md"
            setup.parent.mkdir(parents=True)
            status.parent.mkdir(parents=True, exist_ok=True)
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
            / ".ai-rulez/skills/infra/references/steps.yaml"
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
    def test_trust_check_accepts_the_home_abbreviated_path(self) -> None:
        """mise 2026.9 prints `~/…` for a trusted path under $HOME (#88)."""
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra/references/steps.yaml"
        ).read_text(encoding="utf-8")
        match = re.search(
            r"  - tool: mise\n    check: >-\n(?P<body>(?:      [^\n]*\n)+)", steps
        )
        self.assertIsNotNone(match)
        check = " ".join(line[6:] for line in match.group("body").splitlines())
        # Only the preflight copy runs below. new-provider-toolchain is not held
        # byte-identical to it as a whole, so pin its trust match to the same text.
        trust = re.compile(r"      repo_dir=\$\(pwd -P\) &&\n(?:      .*\n)*?.*: trusted\" >/dev/null &&\n")
        segments = trust.findall(steps)
        self.assertEqual(len(segments), 3)
        self.assertEqual(len(set(segments)), 1, segments)

        fixture_mise = """#!/bin/sh
case "$1" in
  --version) exit 0 ;;
  trust) printf '%s\\n' "$TRUST_LINE" ;;
  config) sed -n '/^\\[tools\\]/,$p' ./mise.toml | sed '1d' ;;
esac
"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory).resolve()
            binaries = base / "bin"
            binaries.mkdir()
            executable = binaries / "mise"
            executable.write_text(fixture_mise, encoding="utf-8")
            executable.chmod(0o755)
            repository = base / "home/repo"
            repository.mkdir(parents=True)
            (repository / "mise.toml").write_text(
                '[tools]\nterraform = "1.15.9"\n', encoding="utf-8"
            )
            (repository / "mise.lock").write_text("# @generated\n", encoding="utf-8")
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

            def run(home: Path | str, line: str) -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {
                        "PATH": f"{binaries}:/usr/bin:/bin",
                        "HOME": str(home),
                        "TRUST_LINE": line,
                    },
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            home = base / "home"
            self.assertEqual(run(home, f"{repository}: trusted"), 0)
            self.assertEqual(run(home, "~/repo: trusted"), 0)
            # A different trusted directory must not stand in for this one.
            self.assertNotEqual(run(home, "~/repo-fork: trusted"), 0)
            self.assertNotEqual(run(home, "~/other/repo: trusted"), 0)
            # Outside $HOME there is no abbreviation, so `~` + the absolute path is
            # a different directory under the home, not this repository.
            self.assertNotEqual(run(base / "elsewhere", f"~{repository}: trusted"), 0)
            # $HOME must prefix whole path components, as it does for mise.
            self.assertNotEqual(run(base / "home/re", "~po: trusted"), 0)
            self.assertNotEqual(run("/", f"~{repository}: trusted"), 0)
            self.assertNotEqual(run("", f"~{repository}: trusted"), 0)
            # A repository at $HOME itself is shown as a bare `~`.
            self.assertEqual(run(repository, "~: trusted"), 0)
            self.assertNotEqual(run(repository, "~/: trusted"), 0)
            # mise strips a trailing-slash $HOME literally: `~repo`, not `~/repo`.
            self.assertEqual(run(f"{home}/", "~repo: trusted"), 0)
            self.assertNotEqual(run(f"{home}/", "~/repo: trusted"), 0)
            self.assertEqual(run(f"{repository}/", f"{repository}: trusted"), 0)
            self.assertNotEqual(run(f"{base}/home/re/", "~po: trusted"), 0)

    # Executed against shell fixtures, so POSIX-only for the same reason as above.
    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_lock_check_covers_every_configured_tool(self) -> None:
        """The locked dry-run must cover conditionally added tools, not a fixed set."""
        steps = (
            Path(__file__).parents[1]
            / ".ai-rulez/skills/infra/references/steps.yaml"
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
  trust) printf '%s: trusted\n' "$(pwd -P)" ;;
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
            / ".ai-rulez/skills/infra/references/steps.yaml"
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

            def run(pin: str, provider_tools: str = "[]") -> int:
                return subprocess.run(
                    ["/bin/sh", "-c", check],
                    cwd=repository,
                    env=os.environ
                    | {
                        "PATH": f"{binaries}:/usr/bin:/bin",
                        "PIN": pin,
                        "NEW_PROVIDER_MISE_TOOLS": provider_tools,
                    },
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode

            # Before the provider's HUMAN toolchain gate, its CLI is not executed.
            self.assertEqual(run("551.0.0"), 0)

            # The regression: matching pin and installed SDK must agree. Reading
            # `core.version` yielded an empty string and kept this red.
            self.assertEqual(run("551.0.0", '["gcloud"]'), 0)
            # Drift, the release date mistaken for a version, and non-exact
            # selectors all have to fail.
            for pin in ("550.0.0", "2026.01.02", "latest", ">=551", "551"):
                self.assertNotEqual(run(pin, '["gcloud"]'), 0, pin)


if __name__ == "__main__":
    unittest.main()
