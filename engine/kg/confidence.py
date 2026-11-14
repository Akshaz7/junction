"""Measured same-as confidence; unsupported methods stay explicitly uncalibrated.

The table is fit only on non-heldout data by scripts/kg_eval.py. Probabilities
are Laplace-smoothed candidate precision, conditional on the evaluated matcher
and data provenance. They are not guarantees on independently authored scans.
"""
from __future__ import annotations

import math

# BEGIN MEASURED TABLE (updated by scripts/kg_eval.py --write-calibration)
CALIBRATION = {'guid': [{'max_residual_m': None, 'n': 3824, 'correct': 3824, 'probability': 0.9997386304234187}],
 'tag_text': [{'max_residual_m': None,
               'n': 2663,
               'correct': 2663,
               'probability': 0.999624765478424}],
 'position': [{'max_residual_m': 0.01,
               'n': 3382,
               'correct': 3349,
               'probability': 0.9899527186761229},
              {'max_residual_m': 0.05, 'n': 9, 'correct': 6, 'probability': 0.6363636363636364},
              {'max_residual_m': 0.2, 'n': 4, 'correct': 0, 'probability': 0.3333333333333333},
              {'max_residual_m': 0.5, 'n': 1, 'correct': 1, 'probability': 0.3333333333333333},
              {'max_residual_m': 1.0, 'n': 0, 'correct': 0, 'probability': None},
              {'max_residual_m': None, 'n': 0, 'correct': 0, 'probability': None}],
 'label_text': [{'max_residual_m': None,
                 'n': 3376,
                 'correct': 3376,
                 'probability': 0.9997039668442865}]}
# END MEASURED TABLE


def confidence(method: str, residual_m=None, evidence=None, **kwargs) -> float:
    """Return a probability in [0, 1]; missing/invalid positional evidence <= .5.

    `alignment` may be supplied inside evidence or as a keyword. If supplied,
    it must contain >=3 matches and a finite, nonnegative residual. Unseen
    residual bins and methods return .5 (uncalibrated estimate).
    """
    evidence = evidence if isinstance(evidence, dict) else {}
    residual_m = residual_m if residual_m is not None else evidence.get("residual_m")
    entries = CALIBRATION.get(method, [])
    if method == "position":
        if not _finite(residual_m) or residual_m < 0:
            return 0.0 if residual_m is not None else 0.5
        alignment = kwargs.get("alignment", evidence.get("alignment"))
        if alignment is not None:
            if not isinstance(alignment, dict):
                return 0.0
            matches = alignment.get("matches", 0)
            error = alignment.get("residual_m", alignment.get("residual"))
            if not _finite(matches) or matches < 3 or not _finite(error) or error < 0:
                return 0.0
            residual_m = max(residual_m, error)
        for entry in entries:
            limit = entry["max_residual_m"]
            if limit is None or residual_m <= limit:
                return _probability(entry)
        return 0.5
    return _probability(entries[0]) if entries else 0.5


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _probability(entry):
    value = entry.get("probability")
    return min(1.0, max(0.0, value)) if _finite(value) and entry.get("n", 0) > 0 else 0.5


link_confidence = confidence
