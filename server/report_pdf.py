"""Dependency-free PDF export of an automation report (E-18). Renders the report Markdown as plain paged text.

Uses the built-in Helvetica fonts (WinAnsi), so no library or licence is involved. Characters outside cp1252
become '?'. Text stays extractable (pdfminer / pdfium read it back).
"""
import re
import textwrap

PAGE_W, PAGE_H, MARGIN = 595, 842, 56
SIZES = {"h1": 18, "h2": 14, "p": 10.5}
LEADING = 1.4


def _esc(s: str) -> str:
    s = s.encode("cp1252", "replace").decode("cp1252")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _plain(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"\1", s)
    return re.sub(r"`([^`]*)`", r"\1", s)


def _lines(markdown: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append(("p", ""))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        style, text = ("h1" if len(m.group(1)) == 1 else "h2", m.group(2)) if m else ("p", line)
        text = _plain(text)
        if re.match(r"^[-*]\s+", text):
            text = "- " + re.sub(r"^[-*]\s+", "", text)
        width = int((PAGE_W - 2 * MARGIN) / (SIZES[style] * 0.5))
        for w in textwrap.wrap(text, width, subsequent_indent="  " if text.startswith("- ") else "") or [""]:
            out.append((style, w))
    return out


def markdown_to_pdf(markdown: str, title: str = "Report") -> bytes:
    pages: list[list[tuple[str, str, float]]] = [[]]
    y = PAGE_H - MARGIN
    for style, text in _lines(markdown):
        step = SIZES[style] * LEADING + (6 if style != "p" else 0)
        if y - step < MARGIN:
            pages.append([])
            y = PAGE_H - MARGIN
        y -= step
        pages[-1].append((style, text, y))
    objs: list[bytes] = []  # 1 catalog, 2 pages, 3 helv, 4 bold, then page/content pairs

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)
    add(b"")  # catalog placeholder
    add(b"")  # pages placeholder
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for pg in pages:
        ops = []
        for style, text, yy in pg:
            if text:
                font = "F2" if style != "p" else "F1"
                ops.append(f"BT /{font} {SIZES[style]} Tf {MARGIN} {yy:.1f} Td ({_esc(text)}) Tj ET")
        stream = "\n".join(ops).encode("cp1252")
        cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        pid = add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                  f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {cid} 0 R >>".encode())
        kids.append(pid)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = f"<< /Type /Pages /Count {len(kids)} /Kids [{' '.join(f'{k} 0 R' for k in kids)}] >>".encode()
    info = add(f"<< /Title ({_esc(title)}) /Producer (Hologram) >>".encode())
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
