"""Room assignment and summaries for individually marked items."""
from collections import Counter


def room_for(box, rooms):
    """Use an enclosing room polygon, never guess the nearest text label."""
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    for room in rooms:
        poly = room.get('polygon_px') or []
        inside = False
        if len(poly) < 3:
            continue
        j = len(poly) - 1
        for i, (xi, yi) in enumerate(poly):
            xj, yj = poly[j]
            if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:
                inside = not inside
            j = i
        if inside:
            return room.get('label') or room.get('item_id') or 'Unnamed room'
    return None


def summary(matches):
    active = [m for m in matches if m['status'] != 'rejected']
    return {'found': len(active), 'confirmed': sum(m['status'] == 'confirmed' for m in active),
            'pending': sum(m['status'] == 'pending' for m in active),
            'rejected': len(matches) - len(active),
            'rooms': dict(Counter(m.get('room') or 'Room unknown' for m in active))}
