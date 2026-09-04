"""Tests that the cf-terraforming coverage matrix keeps its two claims apart.

The matrix used to answer one question — "Supported by `generate`" — with two
different kinds of answer: what the tool can emit, and what we recommend
importing. `cloudflare_workers_route` was marked unsupported on that strength,
when upstream maps both a `list` and a `get` endpoint for it and `generate`
skips a resource only when neither exists. The recommendation was right and the
capability claim was wrong, and one column could not say so.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORT_DOC = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/docs/import.md"


class ImportDocTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = IMPORT_DOC.read_text(encoding="utf-8")
        # Collapse whitespace: asserting on single lines silently misses any phrase
        # the prose happens to wrap.
        self.doc = re.sub(r"\s+", " ", self.raw)

    def _row(self, resource: str) -> list[str]:
        """The matrix cells for one resource, as a list of stripped strings."""
        for line in self.raw.splitlines():
            if line.startswith(f"| `{resource}`"):
                return [cell.strip() for cell in line.strip("|").split("|")]
        self.fail(f"{resource} has no row in the coverage matrix")

    def test_the_matrix_separates_capability_from_recommendation(self) -> None:
        header = self._header()
        self.assertEqual(len(header), 3, f"expected three columns, got {header}")
        self.assertIn("`generate` emits it", header[1])
        self.assertIn("Import it here", header[2])

    def _header(self) -> list[str]:
        for line in self.raw.splitlines():
            if line.startswith("| Resource |"):
                return [cell.strip() for cell in line.strip("|").split("|")]
        self.fail("the coverage matrix has no header row")

    def test_route_is_emitted_but_not_recommended(self) -> None:
        """The row the conflation got wrong. Both halves are load-bearing."""
        _, emits, importable = self._row("cloudflare_workers_route")
        self.assertTrue(emits.startswith("yes"), emits)
        self.assertIn("**no**", importable)
        # Without this, "no" reads as a tool limitation again.
        self.assertIn("not because the tool cannot", importable)

    def test_script_is_unsupported_for_the_stated_upstream_reason(self) -> None:
        """`generate`'s actual gate is an absent endpoint mapping, not bundle content."""
        _, emits, importable = self._row("cloudflare_workers_script")
        self.assertIn("**no**", emits)
        self.assertIn("Unsupported terraform v5 provider resource", emits)
        self.assertEqual("no", importable)

    def test_names_the_upstream_file_that_settles_a_row(self) -> None:
        """A future audit must not re-derive coverage from the README.

        The README's v5 tables omit resources the mapping file covers -- that
        omission is what made the wrong route row look correct.
        """
        self.assertIn("resource_to_endpoint_mapping.go", self.doc)
        self.assertIn("not the README", self.doc)

    def test_every_row_answers_both_columns(self) -> None:
        rows = [
            line for line in self.raw.splitlines()
            if line.startswith("| `cloudflare") or line.startswith("| Zone settings")
        ]
        self.assertGreater(len(rows), 5)
        for line in rows:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            with self.subTest(row=cells[0]):
                self.assertEqual(len(cells), 3, cells)
                self.assertTrue(all(cells), f"empty cell in {cells}")


if __name__ == "__main__":
    unittest.main()
