"""Skirting calculation operands captured at the point the route measures them."""
import math

from engine.calc import input_value, row, source, step, step_source, summed


def skirting(doc, measurements, stub):
    rows, steps = [], []
    for n, m in enumerate(measurements):
        room = m['room']
        ref = source(doc, room)
        sid = f'skirting-{n}'
        if m['basis'] == 'recorded net length':
            net_source = {**ref, 'field': 'net_skirting_length_m'}
        else:
            perimeter_source = {**ref, 'field': 'perimeter_m'}
            if m.get('polygon'):
                polygon, scale = m['polygon'], m['scale']
                units = 'm' if doc.mode == 'ifc' else 'px'
                operands = [input_value(f'vertex {i + 1} {axis}', p[j], units, {**ref, 'field': ('bbox_m rectangle' if m['basis'] == 'bounding rectangle' else 'polygon_px') + f'[{i}][{j}]'})
                            for i, p in enumerate(polygon) for j, axis in enumerate(('x', 'z' if doc.mode == 'ifc' else 'y'))]
                px_perimeter = sum(math.dist(a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1]))
                steps.append(step(sid + '-outline', 'Closed room perimeter', 'Σ(hypot(next x − x, next y − y)), including closing edge', px_perimeter, units,
                                  operands, m['basis'], 'polygon_perimeter'))
                scale_ref = ({'kind': 'conversion', 'text': 'IFC geometry is already in metres; multiply once by 1'} if doc.mode == 'ifc' else
                             {'kind': 'measurement', 'doc_id': doc.doc_id, 'page': room.page, 'record': {'scale': scale}, 'text': 'Selected page scale used by the order route'})
                steps.append(step(sid + '-perimeter', 'Convert room perimeter to metres', 'closed perimeter × page scale', m['perimeter'], 'm',
                                  [input_value('closed perimeter', px_perimeter, units, step_source(sid + '-outline')),
                                   input_value('scale', scale, 'm/' + units, scale_ref)], operation='multiply'))
                perimeter_source = step_source(sid + '-perimeter')
            steps.append(step(sid + '-doors', 'Associated doorway widths', 'sum(widths of the doors actually associated with this room)', sum(w for _, w in m['doors']), 'm',
                              [input_value('door width', width, 'm', source(doc, door, 'width_m')) for door, width in m['doors']],
                              ('Association: door centre within ' + str(m['association_band_m']) + ' m of the room edge; widths are not capped.' if 'association_band_m' in m else 'Explicit room.props.door_ids association.'), 'sum'))
            steps.append(step(sid + '-net', 'Subtract room openings', 'room perimeter − associated doorway widths', m['net'], 'm',
                              [input_value('room perimeter', m['perimeter'], 'm', perimeter_source),
                               input_value('doorway widths', sum(w for _, w in m['doors']), 'm', step_source(sid + '-doors'))], operation='subtract'))
            net_source = step_source(sid + '-net')
        r = row(doc, room, m['net'], 'm', basis=m['basis'], door_ids=[d.item_id for d, _ in m['doors']])
        r['source'] = net_source
        rows.append(r)
    return summed(stub, rows, 'm', 'net skirting = Σ(room perimeters − associated door widths)', steps)
