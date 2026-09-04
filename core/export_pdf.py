"""
export_pdf.py - .pdf usage export (ROADMAP.md item 5, the PDF half;
core/export_xlsx.py is the Excel half).

Same shape as core/export_xlsx.py: a plain function of its arguments in,
bytes out, no I/O, no UI, testable by reading the output back. Where
export_xlsx.py delegates the file format to openpyxl, this one does not
delegate at all — it writes the PDF bytes itself, object by object. See
"Why hand-rolled" below for why that is the deliberate choice here, rather
than the library route the Excel export took.

## Why hand-rolled, not a library

Two real PDF libraries were checked before writing this — the same licence
+ packaging-fit question AUDIT BL-05 already asks before adding a runtime
dependency, and the same one core/export_xlsx.py answered for openpyxl:

- `fpdf2` is licensed LGPL-3.0-only. Statically bundling an LGPL library
  into a one-file PyInstaller build of a proprietary product is exactly
  the problem AUDIT BL-05 found and fixed once already, for pystray.
  Reintroducing that class of problem for a report-export feature would
  undo the fix.
- `reportlab` is BSD (fine on its own) but *requires* Pillow. Pillow's own
  licence is fine too — AUDIT BL-05 says so explicitly, the LGPL problem
  was pystray, not Pillow — but core/qrcode.py already made the call, for
  the same underlying reason, to write a standard-library implementation
  rather than depend on anything that pulls Pillow back in after it was
  deliberately dropped from the runtime. Same call here, for the same
  reason: not because Pillow is unsafe, but because avoiding it entirely
  is the standing decision and nothing here needs it badly enough to
  reopen that.

A basic multi-page text-and-table report — the only thing this needs to
produce — is well within what PDF's actual object format supports without
a library: a handful of indirect objects (a catalog, a page tree, one of
the 14 standard fonts every PDF reader already has built in, and one
content stream per page), a cross-reference table recording each object's
exact byte offset, and a trailer. No image embedding, no custom font
embedding, no compression — a real PDF reader treats all of those as
optional, and none of them are needed here.

Verified against real, independent tools — `qpdf --check` (structural
validity: xref table, object graph, stream lengths) and `pdftotext`
(the actual text content reads back correctly) — the same "verify against
something that isn't this code" standard core/qrcode.py was held to,
reading generated symbols back with a real decoder. Neither tool is a
runtime dependency; both are dev-time verification only, the same role
pytest and ruff already have.
"""

from datetime import datetime

from core.export_xlsx import _fmt_hm

_PAGE_WIDTH = 612.0   # US Letter, points (72 pt/inch)
_PAGE_HEIGHT = 792.0
_MARGIN = 50.0
_ROW_HEIGHT = 14.0
_FONT_SIZE = 10
_TITLE_SIZE = 16

# Left edge of each column, in points from the page's left margin origin.
_COLUMNS = [
    ("App Name", _MARGIN),
    ("Category", _MARGIN + 190),
    ("Date", _MARGIN + 300),
    ("Duration", _MARGIN + 400),
]
_COL_CHAR_LIMITS = [26, 16, 12, 12]   # truncation width per column, in characters


def _escape(text: str) -> str:
    """Escape the three characters a PDF literal string (...) treats as
    special. Anything else passes through — see _encode below for what
    happens to characters outside Latin-1."""
    text = str(text or "")
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _encode(text: str) -> bytes:
    """
    PDF's standard 14 fonts (Helvetica included) use WinAnsiEncoding, which
    Latin-1 approximates closely enough for the Western text this report
    actually contains — app names, categories, ISO dates. A character
    outside that range (CJK, Cyrillic, emoji) has no glyph in a standard,
    unembedded font regardless of encoding, so it is replaced with '?'
    rather than raising: a slightly wrong character in one cell is a far
    smaller problem than an export that crashes on one oddly-named app.
    Embedding a Unicode font to render everything exactly is real scope,
    not a one-line fix — out of scope for a v1 report export.
    """
    return text.encode("latin-1", errors="replace")


def _truncate(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _flatten_rows(apps, history_by_app_id: dict) -> list:
    """Same shape and same rule as export_xlsx.build_workbook: one row per
    (app, date) usage record, in whatever order `apps` is given in. A
    missing or empty history for an app is skipped, not an error."""
    history_by_app_id = history_by_app_id or {}
    rows = []
    for app in apps or ():
        history = history_by_app_id.get(app.get("id")) or []
        for entry in history:
            seconds = int(entry.get("total_sec", 0) or 0)
            rows.append((
                app.get("name", "") or "",
                app.get("category", "") or "",
                entry.get("date", "") or "",
                _fmt_hm(seconds),
            ))
    return rows


def _paginate(rows: list) -> list:
    """
    Split rows into pages. The first page has less room than the rest —
    it also carries the title and generated-on line — so it is computed
    separately rather than padding every page's budget down to match it.
    """
    first_page_budget = int((_PAGE_HEIGHT - _MARGIN - 90) // _ROW_HEIGHT)
    later_page_budget = int((_PAGE_HEIGHT - _MARGIN - 40) // _ROW_HEIGHT)
    first_page_budget = max(1, first_page_budget)
    later_page_budget = max(1, later_page_budget)

    if not rows:
        return [[]]

    pages = [rows[:first_page_budget]]
    rest = rows[first_page_budget:]
    for i in range(0, len(rest), later_page_budget):
        pages.append(rest[i:i + later_page_budget])
    return pages


def _text_op(x: float, y: float, size: int, font: str, text: str) -> str:
    return "BT /%s %d Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj ET\n" % (
        font, size, x, y, _escape(text))


def _page_content(rows: list, page_num: int, total_pages: int,
                   title: str, generated_line: str) -> str:
    """The content-stream text for one page: BT/ET text-showing operators,
    nothing else — no images, no vector graphics, no compression."""
    ops = []
    y = _PAGE_HEIGHT - _MARGIN

    if page_num == 1:
        ops.append(_text_op(_MARGIN, y, _TITLE_SIZE, "F2", title))
        y -= _TITLE_SIZE + 6
        ops.append(_text_op(_MARGIN, y, 9, "F1", generated_line))
        y -= 22
    else:
        y -= 4

    for label, x in _COLUMNS:
        ops.append(_text_op(x, y, _FONT_SIZE, "F2", label))
    y -= _ROW_HEIGHT

    for row in rows:
        for value, limit, (_label, x) in zip(row, _COL_CHAR_LIMITS, _COLUMNS, strict=True):
            ops.append(_text_op(x, y, _FONT_SIZE, "F1", _truncate(value, limit)))
        y -= _ROW_HEIGHT

    footer = "Page %d of %d" % (page_num, total_pages)
    ops.append(_text_op(_MARGIN, _MARGIN - 20, 8, "F1", footer))
    return "".join(ops)


def build_pdf(apps, history_by_app_id: dict, generated_at=None) -> bytes:
    """
    A multi-page PDF usage report: the same 30-day per-app history
    core/export_xlsx.py and ui/processes_page.py's CSV export already send,
    laid out as a table with a title page header and page numbers.

    `apps` / `history_by_app_id` are exactly export_xlsx.build_workbook's
    shapes. `generated_at` overrides the "Generated on" line for
    deterministic tests; defaults to now.

    Returns the complete PDF file as bytes — no filesystem access here,
    same separation as build_workbook. write_export() below is the
    file-writing sibling.
    """
    moment = generated_at if isinstance(generated_at, datetime) else datetime.now()
    title = "ProtBot Usage Report"
    generated_line = "Generated %s" % moment.strftime("%Y-%m-%d %H:%M")

    rows = _flatten_rows(apps, history_by_app_id)
    pages = _paginate(rows)
    total_pages = len(pages)

    buf = bytearray()
    buf += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"   # binary marker, conventional

    offsets = {}   # obj_id -> byte offset of "N 0 obj"

    def _add_object(obj_id: int, body: bytes) -> None:
        offsets[obj_id] = len(buf)
        buf.extend(b"%d 0 obj\n" % obj_id)
        buf.extend(body)
        buf.extend(b"\nendobj\n")

    n_pages = total_pages
    page_obj_ids = [5 + 2 * i for i in range(n_pages)]
    content_obj_ids = [6 + 2 * i for i in range(n_pages)]

    _add_object(1, b"<< /Type /Catalog /Pages 2 0 R >>")

    kids = " ".join("%d 0 R" % pid for pid in page_obj_ids)
    _add_object(2, ("<< /Type /Pages /Kids [%s] /Count %d >>"
                     % (kids, n_pages)).encode("ascii"))

    _add_object(3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    _add_object(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for i, page_rows in enumerate(pages):
        page_num = i + 1
        page_id = page_obj_ids[i]
        content_id = content_obj_ids[i]

        content = _page_content(page_rows, page_num, total_pages, title, generated_line)
        content_bytes = _encode(content)
        stream_body = (b"<< /Length %d >>\nstream\n" % len(content_bytes)
                        + content_bytes + b"\nendstream")
        _add_object(content_id, stream_body)

        page_body = (
            "<< /Type /Page /Parent 2 0 R "
            "/MediaBox [0 0 %g %g] "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            "/Contents %d 0 R >>"
            % (_PAGE_WIDTH, _PAGE_HEIGHT, content_id)
        ).encode("ascii")
        _add_object(page_id, page_body)

    max_obj_id = max(offsets)
    xref_offset = len(buf)
    buf += b"xref\n"
    buf += b"0 %d\n" % (max_obj_id + 1)
    buf += b"0000000000 65535 f \n"
    for obj_id in range(1, max_obj_id + 1):
        buf += b"%010d 00000 n \n" % offsets[obj_id]

    buf += b"trailer\n"
    buf += b"<< /Size %d /Root 1 0 R >>\n" % (max_obj_id + 1)
    buf += b"startxref\n%d\n" % xref_offset
    buf += b"%%EOF\n"

    return bytes(buf)


def write_export(apps, history_by_app_id: dict, path: str) -> str:
    """Build the PDF and save it to `path`. Returns `path`, the same
    contract as export_xlsx.write_export and ui/processes_page.py's
    existing export_csv."""
    with open(path, "wb") as fh:
        fh.write(build_pdf(apps, history_by_app_id))
    return path


def default_filename(now=None) -> str:
    """`ProtBot_export_<timestamp>.pdf` — the same naming scheme
    export_xlsx.default_filename and export_csv already use."""
    moment = now if isinstance(now, datetime) else datetime.now()
    return "ProtBot_export_%s.pdf" % moment.strftime("%Y%m%d_%H%M%S")
