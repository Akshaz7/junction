"""Run through scripts/heavy.sh: exercises real GLB extrusion, no models."""
import json
import pytest
from PIL import Image
from engine.taught_items import project
from server.taught_scene import build


def mark(name, box, sid):
    return {'id':sid,'name':name,'template_bbox':box,'page':1,'manual_selection':True,'matches':[{'status':'confirmed'}]}


def test_scene_rebuild_cuts_wall_and_preserves_ids_and_removal(tmp_path):
    import trimesh
    d = tmp_path/'sheet'; d.mkdir()
    Image.new('RGB',(200,100),'white').save(d/'page-1.png')
    base = {'doc_id':'sheet','page':1,'image':{'w':200,'h':100},'scale':{'m_per_px':.01,'method':'dimensions','confidence':1},
            'items':[{'item_id':'wall','kind':'wall','bbox_px':[20,40,180,60],'props':{},'conf':1,'source':'rule'}]}
    (d/'planmap-1.json').write_text(json.dumps(project(base,[],1)))
    build(d)
    native = trimesh.load_scene(d/'scene.glb')
    original_volume = native.geometry['wall:wall'].volume if 'wall:wall' in native.geometry else sum(g.volume for g in native.geometry.values())
    labels = [mark('door',[90,40,110,60],'door'),mark('TP',[50,15,60,25],'terminal')]
    (d/'planmap-1.json').write_text(json.dumps(project(base,labels,1)))
    build(d)
    manifest = json.loads((d/'scene.json').read_text())
    assert manifest['items']['taught-door']['kind'] == 'door'
    assert manifest['items']['taught-terminal']['kind'] == 'terminal'
    assert manifest['items']['taught-terminal']['method'] == 'user_label'
    scene = trimesh.load_scene(d/'scene.glb')
    # The normal extrusion code cuts the marked doorway out of its host wall.
    wall_volume = sum(g.volume for name,g in scene.geometry.items() if name.startswith('wall') and 'infill' not in name)
    assert wall_volume < original_volume
    assert manifest['taught_revision']
    (d/'planmap-1.json').write_text(json.dumps(project(base,[],1)))
    build(d)
    assert 'taught-door' not in json.loads((d/'scene.json').read_text())['items']


def test_missing_scale_does_not_guess(tmp_path):
    (tmp_path/'planmap-1.json').write_text(json.dumps(project({'items':[]},[mark('door',[1,1,3,3],'one')],1)))
    with pytest.raises(ValueError,match='drawing scale'):
        build(tmp_path)


def test_native_ifc_projection_marker_and_unknown_projection(tmp_path):
    import trimesh
    d = tmp_path/'ifc'; d.mkdir()
    scene = trimesh.Scene(); scene.add_geometry(trimesh.creation.box(),node_name='native',geom_name='native')
    (d/'scene.glb').write_bytes(scene.export(file_type='glb'))
    (d/'scene.json').write_text(json.dumps({'doc_id':'ifc','glb':'scene.glb','items':{'native':{'node':'native','kind':'wall'}}}))
    (d/'elements.json').write_text(json.dumps({'elements':[]}))
    plan = project({'items':[],'storey':{'elevation_m':3,'name':'Level'},
                    'projection':{'x0':10,'z0':20,'ppm':100,'x_px':'(X - x0)*ppm + 40','y_px':'(Z - z0)*ppm + 40'}},
                   [mark('TP',[40,40,60,60],'one')],1)
    (d/'planmap-1.json').write_text(json.dumps(plan))
    build(d)
    manifest = json.loads((d/'scene.json').read_text())
    box = manifest['items']['taught-one']['bbox_m']
    assert box[0][0] == pytest.approx(10) and box[0][2] == pytest.approx(20)
    assert manifest['items']['native']['kind'] == 'wall'
    plan.pop('projection'); (d/'planmap-1.json').write_text(json.dumps(plan))
    build(d)
    manifest = json.loads((d/'scene.json').read_text())
    assert 'taught-one' not in manifest['items']
    assert manifest['unplaced_user_items'] == ['taught-one']
