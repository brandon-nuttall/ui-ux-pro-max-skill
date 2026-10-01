#!/usr/bin/env python3
"""Contract tests for the FastHTML stack data.

FastHTML renders HTML from Python and drives interactivity with server
round-trips plus htmx attributes, so its guidelines must not point at a
JavaScript build step, a Node dependency, Tailwind classes, or a React
component library. These tests hold that line and pin the rows to the
version the file was verified against.
"""

import csv
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core import (AVAILABLE_STACKS, DATA_DIR, STACK_CONFIG,  # noqa: E402
                  STACK_CURRENT_APPLICABILITY, STACK_CURRENT_VERSIONS,
                  search_stack)
from validate_data import STACK_OFFICIAL_HOSTS  # noqa: E402

STACK = "fasthtml"
CSV_PATH = DATA_DIR / STACK_CONFIG[STACK]["file"]
MIN_ROWS = 40

# Columns an agent follows as instructions. The Don't and Code Bad columns are
# deliberately excluded: they exist to show the anti-pattern, so naming a
# tool there is the point of the row, not an instruction to use it.
POSITIVE_COLUMNS = ("Guideline", "Description", "Do", "Code Good")

BUILD_STEP_PATTERN = re.compile(
    r"tailwind|npm\s+(?:install|i|add|ci|run)\b|npx\s|yarn\s|pnpm\s|webpack"
    r"|vite|rollup|esbuild|postcss|babel|react|jsx|tsx|shadcn|radix"
    r"|node_modules|package\.json|components/|pages/"
    # A Tailwind utility is recognised by shape (bg-blue-500) or by the JSX
    # className attribute, because a class string is how Tailwind is used.
    # FastHTML rows legitimately carry cls="badge badge--info" style values,
    # which this does not match.
    r"|className\s*=|(?<![\w-])(?:bg|text|border|from|to|shadow|ring|rounded)"
    r"-(?:[a-z]+|white|black)-\d{2,3}\b",
    re.I,
)

# A package CDN URL is a stylesheet or script reference, not a package-manager
# command: FastHTML's own base-stylesheet constant is
# https://cdn.jsdelivr.net/npm/@anyblades/pico@latest/... so the path segment
# "npm" appears in code we are recommending. URLs are masked before the scan;
# prose and commands are still matched, as test_build_step_scan_can_fail
# demonstrates.
PACKAGE_CDN_URL = re.compile(
    r"https?://(?:cdn\.jsdelivr\.net|unpkg\.com|esm\.sh)[^\s\"']*"
)

SEARCHABLE_QUERIES = (
    "css files and inline styles",
    "form validation on the server round-trip",
    "spinner while the request is in flight",
    "colour contrast for body text",
    "page layout grid",
    "dark mode with prefers color scheme",
    "reduce motion animation",
    "accessibility focus state",
)


def _rows():
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _header():
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


class TestFastHTMLStack(unittest.TestCase):
    def test_fasthtml_stack_is_registered_and_searchable(self):
        self.assertIn(STACK, AVAILABLE_STACKS)
        self.assertEqual(STACK_CONFIG[STACK], {"file": "stacks/fasthtml.csv"})
        self.assertTrue(CSV_PATH.is_file(), f"missing {CSV_PATH}")
        self.assertEqual(STACK_CURRENT_APPLICABILITY[STACK], "fasthtml 0.14.13")
        self.assertEqual(STACK_CURRENT_VERSIONS[STACK], (0, 14))

        for query in SEARCHABLE_QUERIES:
            with self.subTest(query=query):
                result = search_stack(query, STACK, max_results=3)
                self.assertGreaterEqual(result["count"], 1)
                self.assertEqual(result["stack"], STACK)

        # Retrieval must still abstain on an unrelated query rather than
        # surfacing the best-matching row of 65.
        abstain = search_stack(
            "sourdough starter crumb fermentation", STACK, max_results=3)
        self.assertEqual(abstain["count"], 0)

    def test_fasthtml_stack_row_count_and_columns(self):
        rows = _rows()
        self.assertGreaterEqual(
            len(rows), MIN_ROWS,
            f"expected at least {MIN_ROWS} fasthtml guidelines, found {len(rows)}")

        header = _header()
        self.assertEqual(header, [
            "No", "Category", "Guideline", "Description", "Do", "Don't",
            "Code Good", "Code Bad", "Severity", "Docs URL", "Applies To",
            "Status", "Verified At"])
        self.assertEqual(len(header), 13)

        self.assertEqual([row["No"] for row in rows],
                         [str(i) for i in range(1, len(rows) + 1)])
        for row in rows:
            with self.subTest(row=row["No"]):
                self.assertIsNone(row.get(None), "row has more fields than the header")
                for column in header:
                    self.assertTrue(
                        row[column].strip(), f"column {column} is empty")
                self.assertIn(row["Severity"],
                              {"Low", "Medium", "High", "Critical"})
                self.assertIn(row["Status"], {"active", "deprecated"})

    def test_fasthtml_docs_urls_and_applicability(self):
        expected_applies = STACK_CURRENT_APPLICABILITY[STACK]
        allowed_hosts = STACK_OFFICIAL_HOSTS[STACK]
        for row in _rows():
            with self.subTest(row=row["No"]):
                parsed = urlsplit(row["Docs URL"])
                self.assertEqual(parsed.scheme, "https")
                self.assertIn(parsed.hostname, allowed_hosts)
                self.assertTrue(parsed.path.strip("/"),
                                "Docs URL must name a page, not just a host")
                self.assertEqual(row["Applies To"], expected_applies)
                self.assertEqual(row["Status"], "active")
                self.assertRegex(row["Verified At"], r"^\d{4}-\d{2}-\d{2}$")

        # A set assertion on size, so an empty or collapsed file cannot pass.
        rows = _rows()
        self.assertGreaterEqual(len(rows), MIN_ROWS)
        self.assertGreaterEqual(
            len({row["Docs URL"] for row in rows}), 20,
            "each rule needs its own citation; one URL for everything is unfalsifiable")

    def test_fasthtml_rows_have_no_build_step_dependencies(self):
        for row in _rows():
            for column in POSITIVE_COLUMNS:
                masked = PACKAGE_CDN_URL.sub("<cdn>", row[column])
                with self.subTest(row=row["No"], column=column):
                    match = BUILD_STEP_PATTERN.search(masked)
                    self.assertIsNone(
                        match,
                        f"{column} instructs a JavaScript build step or an off-stack "
                        f"UI dependency: {match.group(0)!r}" if match else None)

    def test_build_step_scan_can_fail(self):
        # The scan above is only a check if it can report a difference. These
        # strings mirror the shape of a real row, so a widened pattern or a
        # masked-URL hole shows up here instead of in the data.
        for sample in (
            "Install the design system with npm install tailwindcss",
            "Use a React component for the modal dialog",
            "Compile the stylesheet with npx postcss",
            "Copy the shadcn button into components/ui/button.tsx",
            'Button(cls="bg-blue-500 text-white", "Save")',
        ):
            with self.subTest(sample=sample):
                self.assertIsNotNone(BUILD_STEP_PATTERN.search(
                    PACKAGE_CDN_URL.sub("<cdn>", sample)))
        with_url = ('Link(rel="stylesheet", '
                    'href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css")')
        self.assertIsNone(BUILD_STEP_PATTERN.search(
            PACKAGE_CDN_URL.sub("<cdn>", with_url)))
        # Plain custom classes, the shape the file actually uses, must not match.
        for benign in (
            'Span(cls="badge badge--info", "Draft")',
            'P("Expiry must be MM/YY", cls="field-error")',
            "Button('Submit claim', type='submit', hx_post=submit.to())",
        ):
            with self.subTest(benign=benign):
                self.assertIsNone(BUILD_STEP_PATTERN.search(
                    PACKAGE_CDN_URL.sub("<cdn>", benign)))

    def test_fasthtml_guideline_names_are_distinct(self):
        rows = _rows()
        names = [row["Guideline"] for row in rows]
        folded = [name.casefold() for name in names]
        self.assertEqual(len(folded), len(set(folded)),
                         "duplicate Guideline names make two rows indistinguishable in search")

        foreign = set()
        for path in sorted((DATA_DIR / "stacks").glob("*.csv")):
            if path.name == "fasthtml.csv":
                continue
            with path.open(encoding="utf-8", newline="") as handle:
                foreign.update(row["Guideline"].casefold()
                               for row in csv.DictReader(handle))
        overlap = sorted(set(folded) & foreign)
        self.assertEqual(overlap, [],
                         f"Guideline names already used by another stack: {overlap}")


if __name__ == "__main__":
    unittest.main()
