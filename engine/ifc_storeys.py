"""Canonical IFC levels for answers; source records remain available for proof.

Elevation fields in elements.json are already metres. One millimetre (10^-3
metres) is a small physical coincidence tolerance, independent of whether the
original author used millimetres, metres or feet. Unknown elevations never merge.
"""
from __future__ import annotations

import math
import re
import unicodedata

ELEVATION_TOLERANCE_M = 1e-3


def name_key(name):
    return " ".join(unicodedata.normalize("NFKC", name or "").casefold().split())


def elevation(storey):
    value = storey.get("elevation_m")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def sort_key(storey):
    value = elevation(storey)
    return value is None, value if value is not None else 0


def canonical_storeys(storeys):
    """Merge coincident names, allowing numbered/un-numbered export aliases.

    A numeric prefix is ignored only when its unprefixed label also exists at
    the same elevation. Distinct numbered names alone never collapse. If building
    identity is available, records belonging to different buildings stay separate.
    Compare every candidate to the group's anchor so tolerance cannot chain.
    """
    groups = []
    for index, raw in enumerate(storeys):
        key, z = name_key(raw.get("name")), elevation(raw)
        building = raw.get("building_id")
        bare = re.sub(r"^[+-]?\d+[.)]\s+", "", key)
        if bare != key and z is not None and any(
            name_key(s.get("name")) == bare and s.get("building_id") == building
            and elevation(s) is not None and abs(elevation(s) - z) <= ELEVATION_TOLERANCE_M
            for s in storeys
        ):
            key = bare
        group = next((g for g in groups if key and g["key"] == key and g["building"] == building
                      and z is not None and g["z"] is not None
                      and abs(g["z"] - z) <= ELEVATION_TOLERANCE_M), None)
        if group is None:
            group = {"key": key, "building": building, "z": z, "record": dict(raw), "indices": [], "sources": []}
            groups.append(group)
        group["indices"].append(index)
        group["sources"].append(dict(raw))
    result = [{**g["record"], "aliases": list(dict.fromkeys(s.get("name") or "" for s in g["sources"])),
               "source_indices": g["indices"], "source_storeys": g["sources"]} for g in groups]
    # Repeated names at different heights are distinct levels. Give downstream
    # name-based grouping an unambiguous label, retaining the original as an alias.
    for s in result:
        same_name = [g for g in result if name_key(g["source_storeys"][0].get("name"))
                     == name_key(s["source_storeys"][0].get("name"))]
        if len(same_name) > 1 and elevation(s) is not None:
            s["name"] = f"{s['source_storeys'][0]['name']} ({elevation(s):+g} m)"
    return result


def canonical_name(name, z, storeys):
    matches = [s for s in storeys if name_key(name) in {name_key(n) for n in s.get("aliases", [s["name"]])}]
    if z is not None:
        matches = [s for s in matches if elevation(s) is not None and abs(elevation(s) - z) <= ELEVATION_TOLERANCE_M]
    return matches[0]["name"] if len(matches) == 1 else name


def dedup_trace(doc):
    duplicates = [s for s in doc.storeys if len(s.get("source_indices", [])) > 1]
    if not duplicates:
        return []
    groups = [{"name": s["name"], "elevation_m": elevation(s), "source_indices": s["source_indices"],
               "sources": s["source_storeys"]} for s in duplicates]
    removed = sum(len(s["source_indices"]) - 1 for s in duplicates)
    return [{"step": "dedupe_storeys", "detail": f"Excluded {removed} duplicate storey records by name and elevation (tolerance {ELEVATION_TOLERANCE_M:g} m). "
             + "; ".join(f"{s['name']}: {', '.join(s['aliases'])} ({len(s['source_indices'])} records)" for s in duplicates),
             "groups": groups, "ms": 0, "model": None, "cost_usd": 0}]
