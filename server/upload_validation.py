"""Fast byte-level upload checks. Full parsing stays in the isolated ingest job."""
import re

UPLOAD_EXT = {".ifc": "ifc", ".dxf": "dxf", ".pdf": "pdf",
              ".png": "raster", ".jpg": "raster", ".jpeg": "raster"}
SUPPORTED = "pdf, png, jpg (jpeg), dxf, ifc"


def extension_error(ext: str) -> str | None:
    if ext in UPLOAD_EXT:
        return None
    if ext == ".dwg":
        return "This server cannot convert DWG files. Export the drawing as DXF or IFC and upload it again."
    if ext == ".zip":
        return f"ZIP archives are not supported. Extract the files and upload them individually. Supported types: {SUPPORTED}."
    if ext in {".csv", ".xlsx", ".xls", ".txt"}:
        return "Standalone text and spreadsheet schedules are not supported by this upload path. Export the schedule as PDF and upload it again."
    return f"Unsupported file type {ext or '(none)'}. Supported types: {SUPPORTED}."


def validate_header(ext: str, header: bytes):
    """Reject obvious extension/content mismatches without importing a CAD parser."""
    if ext == ".pdf":
        return  # PDF validation/ingestion is owned by the PDF pipeline.
    known = None
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        known = ".png"
    elif header.startswith(b"\xff\xd8\xff"):
        known = ".jpg"
    elif header.lstrip().upper().startswith(b"ISO-10303-21;"):
        known = ".ifc"
    elif header.startswith(b"AutoCAD Binary DXF") or re.search(rb"(?:^|\n)\s*0\s*\r?\nSECTION\s*\r?\n", header, re.I):
        known = ".dxf"
    elif header.startswith(b"AC10"):
        known = ".dwg"
    expected = ".jpg" if ext == ".jpeg" else ext
    if known != expected:
        if known:
            raise ValueError(f"The file contents are {known[1:].upper()}, but the filename ends in {ext}. Upload it with the correct extension.")
        raise ValueError(f"This file could not be recognised as {ext[1:].upper()}. It may be corrupt or have the wrong extension. Export it again and retry.")
