"""Tests for the coherence half of the upstream check.

The freshness half is deliberately untested here: it reads the network, and a
test that depends on today's upstream release would fail on the day someone
cuts one. Its behaviour is pinned by keeping it separate from coherence — an
unreadable source cannot be reported as drift. The API path comparison is
tested against a hand-written spec instead, for the same reason.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_upstream import (
    check_api_path_coherence,
    check_api_paths,
    check_coherence,
    check_linkage,
    cited_api_paths,
    cited_strings,
    load_api_paths,
    load_entries,
    occurrences,
    path_shape,
    shape_matches,
)


class ManifestTests(unittest.TestCase):
    def test_real_manifest_is_coherent_with_the_shipped_docs(self) -> None:
        self.assertEqual(check_coherence(load_entries()), [])

    def test_every_entry_declares_what_it_is_for(self) -> None:
        """`why_it_matters` is what tells a maintainer whether drift needs action."""
        for entry in load_entries():
            with self.subTest(entry=entry["name"]):
                for field in ("source", "audited", "cited_in", "why_it_matters"):
                    self.assertIn(field, entry)
                self.assertTrue(entry["cited_in"], "cited_in must not be empty")

    def test_unsearchable_versions_declare_cited_as(self) -> None:
        """A bare major is not searchable, so it must declare a distinctive string.

        `audited: "5"` matches a numbered step or `Terraform 1.5+`, so guidance
        could move from v5 to v6 with coherence still passing.
        """
        for entry in load_entries():
            with self.subTest(entry=entry["name"]):
                if entry.get("compare") == "major":
                    self.assertIn(
                        "cited_as", entry, "a major-only version needs a searchable string"
                    )
                for needle, _count in cited_strings(entry):
                    self.assertGreater(
                        len(needle), 2, f"{needle!r} is too short to be distinctive"
                    )

    def test_citations_encode_the_audited_version(self) -> None:
        self.assertEqual(check_linkage(load_entries()), [])

    def test_pinned_sha_entries_declare_a_resolvable_tag(self) -> None:
        """`audited_sha` needs a github_release source to resolve its tag against."""
        for entry in load_entries():
            if "audited_sha" not in entry:
                continue
            with self.subTest(entry=entry["name"]):
                self.assertEqual(entry["source"]["type"], "github_release")
                self.assertRegex(str(entry["audited_sha"]), r"^[0-9a-f]{40}$")

    def test_sources_are_machine_readable_kinds(self) -> None:
        for entry in load_entries():
            with self.subTest(entry=entry["name"]):
                self.assertIn(
                    entry["source"]["type"], {"github_release", "terraform_provider"}
                )


class CoherenceTests(unittest.TestCase):
    @staticmethod
    def _manifest(directory: Path, audited: str, cited_in: list[str]) -> Path:
        manifest = directory / "upstream.json"
        manifest.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "name": "widget",
                            "source": {"type": "github_release", "repo": "a/b"},
                            "audited": audited,
                            "cited_in": cited_in,
                            "why_it_matters": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_document_that_stopped_citing_the_audited_version_is_reported(self) -> None:
        """The manifest drifting away from the prose is the failure this catches."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("pin widget 9.9.9\n", encoding="utf-8")
            entries = load_entries(self._manifest(root, "1.2.3", ["guide.md"]))

            errors = check_coherence(entries, root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("no longer contains '1.2.3'", errors[0])

    def test_missing_document_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = load_entries(self._manifest(root, "1.2.3", ["gone.md"]))

            errors = check_coherence(entries, root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("does not exist", errors[0])

    def test_cited_as_defaults_to_the_audited_version(self) -> None:
        self.assertEqual(cited_strings({"audited": "1.2.3"}), [("1.2.3", 0)])
        self.assertEqual(
            cited_strings({"audited": "5", "cited_as": ["v5 provider"]}),
            [("v5 provider", 0)],
        )
        self.assertEqual(
            cited_strings({"audited": "1", "cited_as": [{"text": "x", "count": 3}]}),
            [("x", 3)],
        )

    def test_every_cited_string_must_be_present(self) -> None:
        """Where a doc carries an executed value and a comment, both must move."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("uses: a/b@newsha # v1.2.3\n", encoding="utf-8")
            manifest = root / "upstream.json"
            manifest.write_text(
                json.dumps({"entries": [{
                    "name": "widget",
                    "source": {"type": "github_release", "repo": "a/b"},
                    "audited": "1.2.3",
                    "cited_as": ["a/b@oldsha", "1.2.3"],
                    "cited_in": ["guide.md"],
                    "why_it_matters": "test",
                }]}),
                encoding="utf-8",
            )

            errors = check_coherence(load_entries(manifest), root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("a/b@oldsha", errors[0])

    def test_a_longer_version_does_not_satisfy_a_prefix(self) -> None:
        """`1.2.3` is a substring of `1.2.30`, so a plain membership test lies."""
        self.assertEqual(occurrences("1.2.3", "pin 1.2.30"), 0)
        self.assertEqual(occurrences("1.2.3", "pin 1.2.3"), 1)

    def test_boundary_applies_only_to_numeric_edges(self) -> None:
        """A needle ending in text may legitimately be followed by a period."""
        self.assertEqual(occurrences("v5 provider", "the v5 provider. State"), 1)

    def test_partial_update_of_several_mentions_is_reported(self) -> None:
        """One of four mentions updated must fail, not pass."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("1.2.3 and 1.2.3 and 9.9.9\n", encoding="utf-8")
            manifest = root / "upstream.json"
            manifest.write_text(
                json.dumps({"entries": [{
                    "name": "widget",
                    "source": {"type": "github_release", "repo": "a/b"},
                    "audited": "1.2.3",
                    "cited_as": [{"text": "1.2.3", "count": 3}],
                    "cited_in": ["guide.md"],
                    "why_it_matters": "test",
                }]}),
                encoding="utf-8",
            )

            errors = check_coherence(load_entries(manifest), root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("2 time(s), expected 3", errors[0])

    def test_a_prerelease_does_not_satisfy_the_base_version(self) -> None:
        """`-` and `+` continue a version, so a pin can change to a prerelease."""
        self.assertEqual(occurrences("0.27.0", "0.27.0-rc.1"), 0)
        self.assertEqual(occurrences("0.27.0", "0.27.0+build.2"), 0)
        self.assertEqual(occurrences("0.27.0", "at 0.27.0 exactly"), 1)

    def test_audited_bumped_without_the_citation_is_reported(self) -> None:
        """Otherwise freshness and coherence go green independently.

        Bump `audited` to the new upstream version, forget the documents and
        `cited_as`, and both checks pass while the guidance is stale.
        """
        errors = check_linkage([{
            "name": "widget",
            "audited": "6",
            "cited_as": ["v5 provider"],
        }])

        self.assertEqual(len(errors), 1, errors)
        self.assertIn("no cited_as string contains the audited version '6'", errors[0])

    def test_linkage_rejects_a_prefix_match(self) -> None:
        """`1.2.3` is a substring of `v1.2.30`, so linkage must be bounded too."""
        errors = check_linkage([{
            "name": "widget", "audited": "1.2.3", "cited_as": ["pin v1.2.30"],
        }])

        self.assertEqual(len(errors), 1, errors)
        self.assertIn("no cited_as string contains", errors[0])

    def test_present_version_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("pin widget 1.2.3\n", encoding="utf-8")
            entries = load_entries(self._manifest(root, "1.2.3", ["guide.md"]))

            self.assertEqual(check_coherence(entries, root), [])


class ApiPathTests(unittest.TestCase):
    def test_real_manifest_api_paths_are_coherent(self) -> None:
        self.assertEqual(check_api_path_coherence(load_api_paths()), [])

    def test_shipped_guidance_cites_the_paths_the_steps_call(self) -> None:
        """A scan that silently matched nothing would make the nightly vacuous."""
        cited = cited_api_paths(list(load_api_paths()["scan"]))
        for shape in ("/organizations/{}", "/workspaces/{}/vars", "/runs/{}/actions/apply"):
            with self.subTest(shape=shape):
                self.assertIn(shape, cited)

    def test_findings_cite_the_editable_source_not_the_generated_copy(self) -> None:
        """Generated trees are overwritten by `make generate` (AGENTS.md rule 1)."""
        cited = cited_api_paths(list(load_api_paths()["scan"]))
        locations = [location for places in cited.values() for location in places]
        self.assertTrue(any(location.startswith(".ai-rulez/") for location in locations))
        for location in locations:
            with self.subTest(location=location):
                self.assertFalse(location.startswith(("skills/", "commands/")))

    def test_every_parameter_spelling_normalises_to_the_same_shape(self) -> None:
        """Shell, placeholder and OpenAPI templates must compare equal mechanically."""
        for path in (
            "/organizations/$ORG/workspaces/$WS",
            "/organizations/${ORG}/workspaces/$1",
            "/organizations/<org>/workspaces/<name>",
            "/organizations/{organization_name}/workspaces/{workspace_name}",
        ):
            with self.subTest(path=path):
                self.assertEqual(path_shape(path), "/organizations/{}/workspaces/{}")

    def test_extraction_cuts_the_query_string_and_surrounding_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text(
                'curl "$hcp_api/workspaces/$WS_ID/vars?page%5Bsize%5D=100" | jq\n'
                "curl https://app.terraform.io/api/v2/runs/$RUN_ID/actions/apply \\\n"
                "Call `api/v2/plans/<id>/json-output-redacted`.\n"
                "hcp_api: https://app.terraform.io/api/v2\n"
                '[ "$hcp_api" = "https://app.terraform.io/api/v2" ]\n',
                encoding="utf-8",
            )

            cited = cited_api_paths(["guide.md"], root)

            self.assertEqual(
                sorted(cited),
                ["/plans/{}/json-output-redacted", "/runs/{}/actions/apply", "/workspaces/{}/vars"],
            )
            self.assertEqual(cited["/runs/{}/actions/apply"], ["guide.md:2"])

    def test_a_literal_fills_a_parameter_but_a_parameter_never_fills_a_literal(self) -> None:
        self.assertTrue(
            shape_matches("/organizations/{}/workspaces/cloudflare", "/organizations/{}/workspaces/{}")
        )
        self.assertFalse(shape_matches("/runs/{}/{}", "/runs/{}/actions"))
        self.assertFalse(shape_matches("/runs/{}/actions/discard", "/runs/{}/actions/apply"))
        self.assertFalse(shape_matches("/runs/{}", "/runs/{}/actions/apply"))

    def test_a_path_missing_from_the_spec_is_reported_with_where_it_is_cited(self) -> None:
        findings = check_api_paths(
            {"/runs/{}/actions/discard": ["docs/hcp-api.md:97"], "/runs": ["x.md:1"]},
            ["/runs", "/runs/{run_id}/actions/apply"],
            [],
            "spec",
        )

        self.assertEqual(len(findings), 1, findings)
        self.assertIn("/runs/{}/actions/discard is not in spec", findings[0])
        self.assertIn("docs/hcp-api.md:97", findings[0])
        self.assertIn("not exhaustive", findings[0])

    def test_an_unlisted_path_is_excused_until_the_spec_lists_it(self) -> None:
        cited = {"/runs/{}/actions/discard": ["docs/hcp-api.md:97"]}

        self.assertEqual(check_api_paths(cited, ["/runs"], ["/runs/{}/actions/discard"], "spec"), [])

        findings = check_api_paths(
            cited, ["/runs/{run_id}/actions/discard"], ["/runs/{}/actions/discard"], "spec"
        )
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("is now in spec", findings[0])

    def test_an_unlisted_path_no_longer_cited_is_reported(self) -> None:
        """Otherwise a stale exemption would excuse the path if it came back."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("curl $hcp_api/runs\n", encoding="utf-8")
            config = {
                "scan": ["guide.md"],
                "unlisted": [
                    {"path": "/runs/{}/actions/discard", "evidence": "https://example.com/"},
                    {"path": "/runs/$RUN_ID", "evidence": "docs"},
                ],
            }

            errors = check_api_path_coherence(config, root)

            self.assertEqual(len(errors), 4, errors)
            self.assertIn("'/runs/{}/actions/discard' is no longer cited", errors[0])
            self.assertIn("is not a shape; write '/runs/{}'", errors[1])
            self.assertIn("needs an https:// `evidence` link", errors[2])

    def test_a_scan_that_finds_nothing_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("no paths here\n", encoding="utf-8")

            errors = check_api_path_coherence({"scan": ["guide.md"]}, root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("no HCP API path found", errors[0])


if __name__ == "__main__":
    unittest.main()
