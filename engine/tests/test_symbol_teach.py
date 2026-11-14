from engine.symbol_teach import room_for, summary


def test_rooms_require_polygons():
    assert room_for([2, 2, 4, 4], [dict(label='Nearby text', bbox_px=[0, 0, 20, 20])]) is None
    assert room_for([2, 2, 4, 4], [dict(label='Office', polygon_px=[[0,0],[10,0],[10,10],[0,10]])]) == 'Office'
    assert room_for([20, 20, 24, 24], [dict(label='Office', polygon_px=[[0,0],[10,0],[10,10],[0,10]])]) is None


def test_single_manual_summary():
    assert summary([{'status': 'confirmed', 'room': 'Office'}]) == dict(found=1, confirmed=1, pending=0, rejected=0, rooms={'Office': 1})
    assert summary([{'status': 'rejected', 'room': None}])['found'] == 0
