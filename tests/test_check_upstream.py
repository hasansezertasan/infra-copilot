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

from scripts.check_upstream import check_coherence, load_entries, MANIFEST


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
            self.assertIn("no longer mentions the audited version 1.2.3", errors[0])

    def test_missing_document_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = load_entries(self._manifest(root, "1.2.3", ["gone.md"]))

            errors = check_coherence(entries, root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("does not exist", errors[0])

    def test_present_version_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text("pin widget 1.2.3\n", encoding="utf-8")
            entries = load_entries(self._manifest(root, "1.2.3", ["guide.md"]))

            self.assertEqual(check_coherence(entries, root), [])


if __name__ == "__main__":
    unittest.main()
