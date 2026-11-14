"""Export the calculation already delivered with an answer; no recomputation."""
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from engine import calc_export

router = APIRouter()


@router.post("/api/calculations/export/{format}")
def export_calculation(format: str, answer: dict = Body(...)):
    exporters = {"csv": (calc_export.to_csv, "text/csv"), "md": (calc_export.to_markdown, "text/markdown"),
                 "html": (calc_export.to_html, "text/html")}
    if format not in exporters:
        raise HTTPException(400, "Choose csv, md or html.")
    if not isinstance((answer.get("reasoning") or {}).get("calc"), dict):
        raise HTTPException(422, "This answer has no recorded calculation.")
    export, media = exporters[format]
    return Response(export(answer), media_type=media, headers={"Content-Disposition": f'attachment; filename="calculation-report.{format}"'})
