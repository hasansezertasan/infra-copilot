from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.validate import validate_config_fallbacks, validate_links


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


if __name__ == "__main__":
    unittest.main()
