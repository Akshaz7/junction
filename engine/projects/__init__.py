"""Projects: many documents of one building site answered and summarised together (contract: handoff/F-PROJECTS-CONTRACT.md).

  classify(doc, root=None)   -> {role, level, confidence}
  overview(project, root=None) -> overview dict (per-level totals, agreements, coverage, mistakes)
  answer(question, doc_ids, root, t0) -> answer object | None   (multi-document counts, areas, level comparisons)
"""
from engine.projects.overview import overview
from engine.projects.roles import classify, level_from_text, level_ordinal

__all__ = ["classify", "overview", "level_from_text", "level_ordinal"]
