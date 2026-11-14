"""Label validation shared by scene.highlight and scene.edit."""


def clean_labels(raw, item_ids: list[str]) -> dict[str, str]:
    """Keep only labels for highlighted items: item_id -> 1-8 char string, at most len(item_ids) entries."""
    if not isinstance(raw, dict):
        return {}
    ids, out = set(item_ids), {}
    for k, v in raw.items():
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            continue
        v = str(v).strip()
        if k in ids and 1 <= len(v) <= 8:
            out[str(k)] = v
        if len(out) >= len(item_ids):
            break
    return out
