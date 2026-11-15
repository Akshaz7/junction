"""IFC level aliases and basement scope, independent of exporter names."""
import re

from engine.solvers.filters import fold

BASEMENT = re.compile(r'\b(?:basement|cellar|underground|keller\w*|untergeschoss|ug|kellari\w*|kallare\w*|karvaning)\b', re.I)
FOUNDATION = re.compile(r'\b(?:foundation|footing|fundament\w*|fundering\w*|perustus\w*|grundlagg\w*)\b', re.I)
ORDINALS = dict(first=1, second=2, third=3, fourth=4, fifth=5, sixth=6, seventh=7, eighth=8, ninth=9, tenth=10)


def unique_levels(storeys):
    """Merge exporter aliases, retaining distinct names at the same elevation."""
    seen, levels = {}, []
    for s in storeys:
        name = str(s.get('name') or '')
        stem = fold(re.sub(r'^\d+\s*[.:_-]\s*', '', name))
        key = (stem, s.get('elevation_m'))
        if key not in seen:
            row = {**s, 'aliases': [name]}
            seen[key] = row
            levels.append(row)
        elif name not in seen[key]['aliases']:
            seen[key]['aliases'].append(name)
    return sorted(levels, key=lambda s: (s.get('elevation_m') is None, float(s.get('elevation_m') or 0)))


def basement_scope(question, storeys):
    """Return (requested, matched name). Basement 1 is nearest the ground."""
    q = fold(question)
    m = re.search(r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)?)\s+(?:basement|cellar)\b|\b(?:basement|cellar)\s+(\d+)\b|\bb(\d+)\b', q)
    if not m:
        return False, None
    token = next(g for g in m.groups() if g)
    ordinal = ORDINALS.get(token) or int(re.match(r'\d+', token)[0])
    levels = unique_levels(storeys)
    basements = [s for s in levels if BASEMENT.search(fold(s['name'])) and not FOUNDATION.search(fold(s['name']))]
    if not basements:
        basements = [s for s in levels if float(s.get('elevation_m') or 0) < -.5 and not FOUNDATION.search(fold(s['name']))]
    # Named basement numbers win over relative elevation ordering (missing B2
    # must never cause B3 to be relabelled as the second basement).
    numbered = {}
    for s in basements:
        name = fold(s['name'])
        n = re.search(r'\bb\s*(\d+)\b|\b(?:basement|cellar|ug|untergeschoss)\s*(\d+)\b|\b(\d+)\s*\.?\s*(?:ug|untergeschoss)\b', name)
        if n:
            numbered[int(next(g for g in n.groups() if g))] = s['name']
    if numbered:
        return True, numbered.get(ordinal)
    if any(s.get('elevation_m') is None for s in basements):
        return True, None  # unnamed basement order cannot be inferred without elevations
    basements.sort(key=lambda s: float(s['elevation_m']), reverse=True)
    return True, basements[ordinal - 1]['name'] if 1 <= ordinal <= len(basements) else None


def level_label(s):
    elevation = s.get('elevation_m')
    return f"{s['name']} ({float(elevation):g} m)" if elevation is not None else f"{s['name']} (elevation not recorded)"


def available_levels(storeys):
    levels = unique_levels(storeys)
    return 'Recorded levels: ' + '; '.join(level_label(s) for s in levels) + '.' if levels else 'No levels are recorded in this model.'
