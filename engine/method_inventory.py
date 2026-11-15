"""Source inventory for the EVMETHOD audit, including delegated scan/PDF routes."""
import ast
from pathlib import Path

SPECS = {
    'answer': ('_chat_answer _reader _answer_core _recount_ladder', ['all'], 'Router, no-data/feature/chat branches and recount ladder'),
    'tasks/__init__': ('run_task', ['all'], 'Claim/meeting/phase/contract tasks: gather cited evidence, write, then reject unsupported figures or state evidence gaps'),
    'assistant': ('chat', ['conversation'], 'No-document conversation; no construction quantities can be verified'),
    'solvers/solve': ('solve _solve_multi _apartments _apt_area', ['IFC', 'DXF', 'raster'], 'Kind, confidence, hidden-item, storey, externality and room filters; counts or quantity-field priority'),
    'analytics': ('filtered_question arithmetic_question multi_doc_total storey_compare total_and_storey storey_pair storey_table building_safety kind_compare exact_size cond_count named_rooms where_rooms wet_rooms count_where room_list baseboard piping wet_room_takeoff takeoff compliance superlative_room plan_total plain_limits exists_or_perroom slab_by_type plan_slab_pipe', ['IFC', 'DXF', 'raster'], 'Structured quantities, distinct/grouped counts, comparisons, ratios, perimeters, allowances and rule findings'),
    'complex_q': ('answer h_*', ['IFC', 'DXF', 'raster'], 'Explicit condition handlers; applied and unresolved conditions retained'),
    'mep': ('answer *_answer no_services', ['IFC'], 'IFC service/structure classification; counts, types, sizes, systems, lengths and material-weighted volumes'),
    'props': ('answer _model_answer _drawing_answer', ['IFC', 'DXF', 'PDF', 'raster'], 'Recorded properties and explicit filters; matched schedule text fallback'),
    'order': ('answer_order', ['IFC', 'DXF', 'raster'], 'Measured floor/net wall coverage, associated-door skirting or indexed counts; stated waste and upward rounding'),
    'wallarea': ('answer estimate_planmaps', ['IFC', 'DXF', 'raster'], 'IFC side faces and actual void cuts; plan-map outline/height approximation when native geometry is absent'),
    'quantity_takeoff': ('quantity_takeoff', ['IFC', 'DXF', 'raster'], 'Independent room areas, baseboard, opening counts, slab groups and piping sections'),
    'takeoff': ('takeoff_answer', ['IFC', 'DXF', 'raster'], 'Room-class sum; declared material allowance or explicitly assumed paint coverage/coats'),
    'projects/multidoc': ('answer _compare_all', ['IFC', 'DXF', 'raster'], 'Building/level grouping; choose model then largest item population; totals, differences or ranking'),
    'projects/overview': ('build', ['all'], 'Same project combiner; API overview rather than a chat answer'),
    'project_answer': ('project_answer passage_answer document_list_answer', ['all'], 'Catalogue search, source passages, supported-number/citation gate or template fallback'),
    'revision_compare': ('comparison_answer compare_ifc compare_planmaps', ['IFC', 'DXF', 'raster'], 'Stable IFC item identities or scale/translation-aligned item overlaps; event counts'),
    'changes': ('compare compare_images', ['planmap', 'raster'], 'Geometry/pixel change API; matched items and connected regions'),
    'design_versions': ('compare', ['IFC', 'planmap'], 'Diff of saved edit snapshots; generated from edits'),
    'scene_cmds': ('scene_answer', ['IFC', 'planmap'], 'Resolve requested tags/kinds, apply per-chat visibility and return scene operations'),
    'locate': ('locate_answer fixture_locate', ['IFC', 'DXF', 'raster'], 'Indexed position and declared storey; detected fixtures on plan-map pages'),
    'exits': ('exit_answer', ['IFC'], 'Exterior-door test from room footprints, not a fire-compliance certification'),
    'textqa': ('text_answer facts_for', ['IFC', 'DXF', 'raster'], 'Structured facts with optional number-constrained wording'),
    'schedules': ('answer_schedule solve_table', ['PDF', 'raster'], 'Ruled-cell schedule extraction and explicit units'),
    'titleblock': ('answer_text extract', ['PDF', 'raster'], 'Source label proximity, revision row or title-block field'),
    'sheetqa': ('answer scale_answer tag_count room_area schedule_rows area_by_type takeoff_sheet area_total share_of_total note_sum size_of room_count overall_width rebar_of cross_sheet sheet_identity pipe_sizes dorm_sheet', ['PDF', 'raster'], 'Printed tags, dimensions, tables and source-text operands'),
    'textfile': ('answer _count_rows _room_table _takeoff _notes', ['PDF', 'text'], 'Printed text-only schedule/room/note lookup'),
    'library': ('sheet_count_answer library_answer library_search_answer drawing_selection_answer app_feature_answer', ['catalogue'], 'Catalogue metadata, visible document selection or app capabilities'),
    'app_help': ('app_help_answer', ['application guide'], 'Guide passages with optional model wording; no construction measurement'),
    'mistakes': ('answer', ['IFC', 'DXF', 'raster'], 'Source consistency, missing data, duplicate, clash and cross-document checks'),
    'readdraw': ('read_drawing', ['raster', 'PDF'], 'Model drawing read with region checks'),
    'reader/agent': ('read_answer', ['all'], 'Tool-using reader; model output is a labelled input'),
    'symbols': ('answer_symbols', ['raster', 'PDF'], 'Legend template matching, deduplication and second look'),
    'forced': ('forced_answer', ['all'], 'Best-effort model fallback with explicit source limits'),
    'units': ('convert', ['numeric answer'], 'Explicit physical-unit conversion or price multiplication after solving'),
}


def inventory():
    import fnmatch
    out = []
    base = Path(__file__).parent
    for module, (patterns, inputs, method) in SPECS.items():
        file = base / (module + '.py')
        tree = ast.parse(file.read_text())
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
            if not any(fnmatch.fnmatchcase(node.name, p) for p in patterns.split()): continue
            body = ast.get_source_segment(file.read_text(), node) or ''
            seed = any(marker in body for marker in ('engine.calc', '_calc', 'calc_routes', 'calc_inventory'))
            owner = ('F-EVINT' if module in ('readdraw', 'reader/agent', 'symbols', 'forced') or module == 'answer' and node.name in ('_reader', '_recount_ladder') else
                     'Awais' if module in ('schedules', 'titleblock', 'sheetqa', 'textfile') else 'F-EVMETHOD')
            api = module in ('changes', 'design_versions', 'projects/overview') or node.name in ('compare_ifc', 'compare_planmaps')
            out.append({'route': 'engine.' + module.replace('/', '.') + ':' + node.name,
                        'source': f'engine/{module}.py:{node.lineno}', 'input_types': inputs,
                        'methods': [method, ast.get_docstring(node) or node.name.replace('_', ' ')],
                        'calc_emitted_before': 'comparison API, not chat envelope' if api else 'dedicated seed + numeric finalizer' if seed else 'numeric finalizer only; text had no calc',
                        'calc_emitted_today': 'API native comparison/overview schema' if api else 'delegated worker' if owner != 'F-EVMETHOD' else 'method/source trace plus numeric finalizer',
                        'owner': owner, 'gaps': ['Runtime variants not exercised by the real-file audit remain unmeasured.']})
    # The shared solver's distinct computational branches are methods, not
    # separate Python entrypoints. Keep them visible in the inventory.
    solver = next(r for r in out if r['route'] == 'engine.solvers.solve:solve')
    solver['submethods'] = ['count indexed kind', 'multiple-kind counts', 'declared IFC storeys', 'floor-plan layout count',
                            'matched room names/types', 'apartment outline selection', 'IFC Qto field priority',
                            'GLB room floor area fallback', 'opening width × height', 'polygon shoelace × scale²',
                            'wall typed length', 'net/gross volume field priority', 'hidden element exclusion',
                            'IFC stair assembly excludes flights', 'fixture property/name classification']
    router = next(r for r in out if r['route'] == 'engine.answer:_answer_core')
    router['submethods'] = ['app help/features', 'document/sheet catalogue', 'starter tasks', 'project search',
                             'missing/unselected document', 'mistake checks', 'wall surfaces', 'material orders',
                             'property filters', 'complex conditions', 'schedules', 'title blocks', 'text files',
                             'multi-document totals', 'engineering sheet lookup', 'legend symbols', 'locate',
                             'what-if advice', 'scene edits', 'analytics', 'numeric solvers', 'model reader fallback']
    return out
