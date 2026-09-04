"""
core/export_pdf.py — the hand-rolled half of ROADMAP.md item 5 (see that
module's own docstring for why it is hand-rolled rather than a library).

Same lesson as tests/test_qrcode.py: a hand-rolled binary format is a bad
thing to test only by reading its own source back — the failure mode is a
file that looks plausible to code that shares its own author's blind spots
and is rejected, or silently mis-rendered, by a real reader. The structural
tests below don't need anything beyond the standard library; the read-back
tests round-trip through `qpdf` and `pdftotext` (poppler), tools this repo
does not ship and does not depend on — dev-time verification only, the same
role OpenCV/segno play for tests/test_qrcode.py. Skipped when absent.
"""

import shutil
import subprocess

import pytest

from core import export_pdf


_APPS = [
    {"id": 1, "name": "Discord", "category": "Social"},
    {"id": 2, "name": "Code", "category": "Development"},
]
_HISTORY = {
    1: [
        {"date": "2026-09-01", "total_sec": 3661},   # 1h 1m
        {"date": "2026-09-02", "total_sec": 59},      # 0m
    ],
    2: [
        {"date": "2026-09-01", "total_sec": 7200},   # 2h 0m
    ],
}

needs_qpdf = pytest.mark.skipif(
    shutil.which("qpdf") is None, reason="qpdf is not installed; dev-only verification tool",
)
needs_pdftotext = pytest.mark.skipif(
    shutil.which("pdftotext") is None, reason="poppler-utils is not installed; dev-only verification tool",
)


# ── Structural — no external tool needed ────────────────────────────────────

class TestFlattenRows:

    def test_one_row_per_history_entry(self):
        rows = export_pdf._flatten_rows(_APPS, _HISTORY)
        assert rows == [
            ("Discord", "Social", "2026-09-01", "1h 1m"),
            ("Discord", "Social", "2026-09-02", "0m"),
            ("Code", "Development", "2026-09-01", "2h 0m"),
        ]

    def test_an_app_with_no_history_is_skipped(self):
        apps = [{"id": 1, "name": "Idle", "category": "Custom"}]
        assert export_pdf._flatten_rows(apps, {}) == []

    def test_none_inputs_do_not_raise(self):
        assert export_pdf._flatten_rows(None, None) == []


class TestPaginate:

    def test_empty_rows_still_yields_one_page(self):
        assert export_pdf._paginate([]) == [[]]

    def test_rows_that_fit_on_one_page_stay_on_one_page(self):
        rows = [("a", "b", "c", "d")] * 10
        pages = export_pdf._paginate(rows)
        assert len(pages) == 1
        assert len(pages[0]) == 10

    def test_more_rows_than_fit_spill_to_a_second_page(self):
        rows = [("a", "b", "c", "d")] * 200
        pages = export_pdf._paginate(rows)
        assert len(pages) > 1
        assert sum(len(p) for p in pages) == 200
        # No row lost or duplicated across the split.

    def test_every_page_after_the_first_is_full_except_possibly_the_last(self):
        rows = [("a", "b", "c", "d")] * 200
        pages = export_pdf._paginate(rows)
        for page in pages[1:-1]:
            assert len(page) == len(pages[1])


class TestEscape:

    def test_parens_and_backslash_are_escaped(self):
        assert export_pdf._escape("a(b)c\\d") == r"a\(b\)c\\d"

    def test_plain_text_is_unchanged(self):
        assert export_pdf._escape("Discord") == "Discord"

    def test_none_becomes_empty_string(self):
        assert export_pdf._escape(None) == ""


class TestTruncate:

    def test_short_text_is_unchanged(self):
        assert export_pdf._truncate("Discord", 26) == "Discord"

    def test_long_text_is_cut_with_an_ellipsis(self):
        result = export_pdf._truncate("a very very very long app name", 10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_none_becomes_empty_string(self):
        assert export_pdf._truncate(None, 10) == ""


class TestBuildPdf:

    def test_starts_with_the_pdf_header(self):
        pdf = export_pdf.build_pdf(_APPS, _HISTORY)
        assert pdf.startswith(b"%PDF-1.4")

    def test_ends_with_eof(self):
        pdf = export_pdf.build_pdf(_APPS, _HISTORY)
        assert pdf.rstrip(b"\n").endswith(b"%%EOF")

    def test_empty_apps_and_history_still_produce_a_valid_looking_file(self):
        pdf = export_pdf.build_pdf([], {})
        assert pdf.startswith(b"%PDF-1.4")
        assert b"trailer" in pdf

    def test_none_inputs_do_not_raise(self):
        pdf = export_pdf.build_pdf(None, None)
        assert pdf.startswith(b"%PDF-1.4")

    def test_xref_object_count_matches_objects_written(self):
        # 4 fixed objects (catalog, pages, 2 fonts) + 2 per page (page,
        # content). One page for this little data set.
        pdf = export_pdf.build_pdf(_APPS, _HISTORY)
        assert pdf.count(b" 0 obj\n") == 6
        assert b"0 7\n" in pdf   # xref: "0 N" where N = object count + 1

    def test_a_generated_at_override_is_used_verbatim(self):
        from datetime import datetime
        pdf = export_pdf.build_pdf(_APPS, _HISTORY, generated_at=datetime(2026, 1, 2, 3, 4))
        assert b"2026-01-02 03:04" in pdf

    def test_odd_characters_in_app_names_do_not_break_the_stream_structure(self):
        apps = [{"id": 1, "name": "App (with) \\parens\\", "category": "Odd"}]
        history = {1: [{"date": "2026-09-01", "total_sec": 60}]}
        pdf = export_pdf.build_pdf(apps, history)
        assert pdf.startswith(b"%PDF-1.4")
        assert b"trailer" in pdf
        # Every stream's declared /Length must match its actual byte count,
        # or a reader will truncate or overrun the content — the exact bug
        # class unescaped parens in the source text would cause.
        import re
        for length_str, stream in re.findall(rb"/Length (\d+) >>\nstream\n(.*?)\nendstream", pdf, re.S):
            assert int(length_str) == len(stream)


class TestWriteExport:

    def test_writes_a_file_and_returns_the_path(self, tmp_path):
        path = str(tmp_path / "out.pdf")
        result = export_pdf.write_export(_APPS, _HISTORY, path)
        assert result == path
        with open(path, "rb") as fh:
            assert fh.read(8) == b"%PDF-1.4"


class TestDefaultFilename:

    def test_format(self):
        from datetime import datetime
        name = export_pdf.default_filename(datetime(2026, 9, 4, 13, 5, 9))
        assert name == "ProtBot_export_20260904_130509.pdf"

    def test_ends_in_pdf(self):
        assert export_pdf.default_filename().endswith(".pdf")


# ── Read-back — verified against real, independent tools ───────────────────

def _run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


@needs_qpdf
class TestQpdfStructuralCheck:

    def test_a_normal_export_passes_qpdf_check(self, tmp_path):
        # returncode is qpdf's actual pass/fail signal (0 == no problems
        # found) — its own reassuring boilerplate on a clean file literally
        # contains the substring "errors" ("no ... errors found"), so that
        # is not a safe thing to grep for.
        path = str(tmp_path / "out.pdf")
        export_pdf.write_export(_APPS, _HISTORY, path)
        result = _run(["qpdf", "--check", path])
        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_many_page_export_passes_qpdf_check(self, tmp_path):
        apps = [{"id": 1, "name": "Discord", "category": "Social"}]
        history = {1: [{"date": "2026-01-%02d" % ((i % 28) + 1), "total_sec": 100 + i}
                        for i in range(150)]}
        path = str(tmp_path / "many.pdf")
        export_pdf.write_export(apps, history, path)
        result = _run(["qpdf", "--check", path])
        assert result.returncode == 0, result.stdout + result.stderr

    def test_odd_characters_still_pass_qpdf_check(self, tmp_path):
        apps = [{"id": 1, "name": "App (with) \\parens\\ (matched?)", "category": "Odd/Slash"}]
        history = {1: [{"date": "2026-09-01", "total_sec": 60}]}
        path = str(tmp_path / "odd.pdf")
        export_pdf.write_export(apps, history, path)
        result = _run(["qpdf", "--check", path])
        assert result.returncode == 0, result.stdout + result.stderr


@needs_pdftotext
class TestPdftotextReadback:

    def test_the_actual_numbers_read_back_correctly(self, tmp_path):
        path = str(tmp_path / "out.pdf")
        export_pdf.write_export(_APPS, _HISTORY, path)
        result = _run(["pdftotext", "-layout", path, "-"])
        text = result.stdout
        assert "Discord" in text
        assert "1h 1m" in text
        assert "2h 0m" in text
        assert "Code" in text

    def test_every_row_survives_pagination_exactly_once(self, tmp_path):
        apps = [{"id": 1, "name": "Discord", "category": "Social"}]
        history = {1: [{"date": "2026-01-%02d" % ((i % 28) + 1), "total_sec": 100 + i}
                        for i in range(150)]}
        path = str(tmp_path / "many.pdf")
        export_pdf.write_export(apps, history, path)
        result = _run(["pdftotext", "-layout", path, "-"])
        assert result.stdout.count("Discord") == 150

    def test_page_footers_are_numbered_correctly(self, tmp_path):
        apps = [{"id": 1, "name": "Discord", "category": "Social"}]
        history = {1: [{"date": "2026-01-%02d" % ((i % 28) + 1), "total_sec": 100 + i}
                        for i in range(150)]}
        path = str(tmp_path / "many.pdf")
        export_pdf.write_export(apps, history, path)
        result = _run(["pdftotext", "-layout", path, "-"])
        footers = [line for line in result.stdout.splitlines() if line.startswith("Page ")]
        assert footers == [f"Page {n} of {len(footers)}" for n in range(1, len(footers) + 1)]
