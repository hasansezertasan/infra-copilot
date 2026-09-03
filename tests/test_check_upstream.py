"""Tests for the coherence half of the upstream check.

The freshness half is deliberately untested here: it reads the network, and a
test that depends on today's upstream release would fail on the day someone
cuts one. Its behaviour is pinned by keeping it separate from coherence — an
unreadable source cannot be reported as drift.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_upstream import check_coherence, cited_strings, load_entries


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
                for needle in cited_strings(entry):
                    self.assertGreater(
                        len(needle), 2, f"{needle!r} is too short to be distinctive"
                    )

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
        self.assertEqual(
            cited_strings({"audited": "1.2.3"}), ["1.2.3"]
        )
        self.assertEqual(
            cited_strings({"audited": "5", "cited_as": ["v5 provider"]}), ["v5 provider"]
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

    def test_present_version_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("pin widget 1.2.3\n", encoding="utf-8")
            entries = load_entries(self._manifest(root, "1.2.3", ["guide.md"]))

            self.assertEqual(check_coherence(entries, root), [])


if __name__ == "__main__":
    unittest.main()
