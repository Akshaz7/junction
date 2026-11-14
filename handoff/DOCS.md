# DOCS (Codex) — current row

ROW: X-20 pitch deck script + architecture diagram
1. docs/PITCH.md: a 3-minute pitch script (≈420 words) for Ash, built on CLAUDE.md's pitch line "We rebuilt Stoa's product in two days. Then we built the part that does not exist yet." Beats: problem (questions about drawings take hours) → live demo cue points (match docs/DEMO.md) → how it stays accurate and cheap (read once into a plan map, code answers, models only where needed; numbers from results/ with links) → the part that doesn't exist yet (same numbered items in 2D → 3D → AR on the table, voice, Finnish rule checks after edits) → close. Mark exactly where each demo action happens.
2. docs/ARCHITECTURE.md: one Mermaid diagram (upload → ingest (IFC/DXF/raster) → plan map → engine ladder (code → small model → large model) → answer object (boxes, citations, item ids) → web 2D/3D + live socket → iOS AR), plus a 10-line legend naming the real files (engine/answer.py, engine/models/models.yaml, server/live.py, pipeline/ifc_scene.py, ios/Hologram/AR/…). Check each path exists.
Done test: every results number in PITCH.md linked (reuse docs/scratch checker) PASS; a script listing every file path in ARCHITECTURE.md and asserting it exists PASS.
Edit only: docs/, this file. Never commit.
Write one line at the end: RESULT: ...
