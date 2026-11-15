"""Record actual floor-outline operands, never the legacy room rectangle rule."""
from engine.calc import Row, input_value, record, step, step_source, summed
from dataclasses import asdict


def attach(res, doc, details, source_file):
    rows, steps = [], []
    for n,d in enumerate(details):
        sid=f'baseboard-room-{n}'
        snapshot={'kind':'measurement','doc_id':doc.doc_id,'item_id':d['item_id'],
                  'record':{'item_id':d['item_id'],'source_ifc':str(source_file) if source_file else None,
                            'perimeter_m':d['perimeter_m'],'footprint_rings_m':d['footprint_rings_m'],
                            'method':d['perimeter_source'],'boundary_method':d['boundary_method']},
                  'text':'True room floor outline in native IFC world coordinates, converted to metres; '+d['perimeter_source']}
        steps.append(step(sid+'-perimeter','Room floor perimeter','length of the union of lowest floor faces',d['perimeter_m'],'m',
                          [input_value('measured floor perimeter',d['perimeter_m'],'m',snapshot)],operation='source'))
        widths=[]
        for gid,width in d['door_widths_m'].items():
            ref={'kind':'measurement','doc_id':doc.doc_id,'item_id':gid,
                 'record':{'item_id':gid,'width_m':width,'source_ifc':str(source_file) if source_file else None,'association':d['boundary_method']},
                 'text':'Recorded door width converted from its declared IFC length unit to metres; '+d['boundary_method']}
            widths.append(input_value('door opening width',width,'m',ref))
        steps.append(step(sid+'-openings','Sum boundary door widths','sum of deduplicated door widths',d['door_width_m'],'m',widths,operation='sum'))
        steps.append(step(sid+'-net','Subtract door openings','floor perimeter − boundary door widths',d['value'],'m',
                          [input_value('floor perimeter',d['perimeter_m'],'m',step_source(sid+'-perimeter')),
                           input_value('door widths',d['door_width_m'],'m',step_source(sid+'-openings'))],operation='subtract'))
        rows.append(asdict(Row(d['item_id'],d['label'],{'length_m':d['value'],'perimeter_m':d['perimeter_m'],'door_width_m':d['door_width_m']},step_source(sid+'-net'))))
    return record(res,summed(res,rows,formula='baseboard = Σ(room floor perimeter − deduplicated boundary door widths)',steps=steps,
                             note='Missing space boundaries use derived door proximity and remain an Estimate. Actual finish specifications and other openings need checking.'))
