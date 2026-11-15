import uuid

import pytest
from pydantic import ValidationError

from app.routes.boards import BoardUpdate
from app.services import mermaid_safety
from app.services.board_commands import BoardOperation, apply_operations

FLOW = 'flowchart LR\n  otp["OTP verification"] --> kyc["KYC"] --> goal["Reduce drop-off"]'


def test_clean_accepts_supported_types_and_strips_fences():
    assert mermaid_safety.clean(f"```mermaid\n{FLOW}\n```") == FLOW
    assert mermaid_safety.clean("%% comment first\nsequenceDiagram\n  A->>B: hi").startswith("%% comment")
    assert mermaid_safety.clean("erDiagram\n  USER ||--o{ MEETING : records")


@pytest.mark.parametrize("source, reason", [
    ("", "empty"),
    ("pie title Pets\n  \"Dogs\": 3", "supported type"),
    ("%%{init: {'securityLevel': 'loose'}}%%\nflowchart LR\n  A-->B", "settings"),
    ("flowchart LR\n  A-->B\n  click A \"https://example.com\"", "links"),
    ("flowchart LR\n  A[\"<script>alert(1)</script>\"]-->B", "HTML"),
    ("flowchart LR\n  A[\"javascript:alert(1)\"]-->B", "HTML"),
    ("flowchart LR\n" + "  A-->B\n" * 200, "too large"),
])
def test_clean_rejects_unsafe_or_unsupported_source(source, reason):
    with pytest.raises(ValueError, match=reason):
        mermaid_safety.clean(source)


def test_set_diagram_creates_then_updates_one_node_with_stable_ids():
    command = uuid.uuid4()
    nodes, edges = apply_operations([], [], [BoardOperation(op='set_diagram', node_id='new:arch', title='Onboarding', mermaid=FLOW)], command)
    assert len(nodes) == 1 and edges == []
    diagram = nodes[0]
    assert diagram['kind'] == 'diagram' and diagram['text'] == FLOW and diagram['title'] == 'Onboarding'
    assert diagram['id'] == f'voice:{uuid.uuid5(command, "0").hex}'
    updated = FLOW + ' --> done["Done"]'
    again, _ = apply_operations(nodes, [], [BoardOperation(op='set_diagram', node_id=diagram['id'], mermaid=updated)], uuid.uuid4())
    assert len(again) == 1 and again[0]['text'] == updated and again[0]['title'] == 'Onboarding'
    assert nodes[0]['text'] == FLOW  # input graph untouched


def test_set_diagram_refuses_unsafe_source_wrong_targets_and_locked_diagrams():
    with pytest.raises(ValueError, match='links'):
        apply_operations([], [], [BoardOperation(op='set_diagram', mermaid=FLOW + '\n  click otp "https://x"')], uuid.uuid4())
    card = dict(id='a', kind='idea', title='a', text='', x=0, y=0, origin='ai', locked=False, source_id=None, source_start_ms=None)
    with pytest.raises(ValueError, match='not a diagram'):
        apply_operations([card], [], [BoardOperation(op='set_diagram', node_id='a', mermaid=FLOW)], uuid.uuid4())
    with pytest.raises(ValueError, match='existing diagram'):
        apply_operations([], [], [BoardOperation(op='set_diagram', node_id='missing', mermaid=FLOW)], uuid.uuid4())
    locked = {**card, 'kind': 'diagram', 'text': FLOW, 'locked': True}
    with pytest.raises(ValueError, match='Unlock'):
        apply_operations([locked], [], [BoardOperation(op='set_diagram', node_id='a', mermaid=FLOW)], uuid.uuid4())


def test_cards_and_diagrams_cannot_be_swapped_without_validation():
    card = dict(id='a', kind='idea', title='a', text='plain', x=0, y=0, origin='ai', locked=False, source_id=None, source_start_ms=None)
    with pytest.raises(ValueError, match='set_diagram'):
        apply_operations([card], [], [BoardOperation(op='update_node', node_id='a', kind='diagram')], uuid.uuid4())
    with pytest.raises(ValueError, match='set_diagram'):
        apply_operations([], [], [BoardOperation(op='create_node', title='x', kind='diagram', text=FLOW)], uuid.uuid4())
    diagram = {**card, 'kind': 'diagram', 'text': FLOW}
    with pytest.raises(ValueError, match='HTML'):
        apply_operations([diagram], [], [BoardOperation(op='update_node', node_id='a', text='flowchart LR\n A["<img src=x>"]')], uuid.uuid4())


def test_manual_board_saves_validate_diagram_source():
    node = dict(id='d', kind='diagram', title='Arch', text=f"```mermaid\n{FLOW}\n```", x=0, y=0)
    saved = BoardUpdate(expected_version=1, title='Board', nodes=[node], edges=[])
    assert saved.nodes[0].text == FLOW
    with pytest.raises(ValidationError):
        BoardUpdate(expected_version=1, title='Board', nodes=[{**node, 'text': 'flowchart LR\n  click A "x"'}], edges=[])


from app.services import excalidraw_safety

RECT = {"id": "r1", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 40, "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False}


def test_drawings_keep_only_safe_drawing_data():
    scene = excalidraw_safety.clean_scene({"elements": [
        {**RECT, "link": "javascript:alert(1)", "customData": {"x": 1}},
        {**RECT, "id": "gone", "isDeleted": True},
        {"id": "t", "type": "text", "x": 1, "y": 1, "text": "Auth API", "originalText": "Auth API", "fontSize": 20},
    ], "appState": {"theme": "dark"}, "files": {"f": {"dataURL": "data:image/png;base64,AA"}}})
    assert [element["id"] for element in scene["elements"]] == ["r1", "t"]
    assert scene["elements"][0]["link"] is None and "customData" not in scene["elements"][0]
    assert set(scene) == {"elements"}


@pytest.mark.parametrize("scene, reason", [
    ({"elements": [{**RECT, "type": "image", "fileId": "f"}]}, "images"),
    ({"elements": [{**RECT, "type": "embeddable", "link": "https://x"}]}, "embeds"),
    ({"elements": [{**RECT, "type": "iframe"}]}, "embeds"),
    ({"elements": "nope"}, "list"),
    ({"elements": [{**RECT, "id": str(i)} for i in range(excalidraw_safety.MAX_ELEMENTS + 1)]}, "too large"),
])
def test_unsafe_or_oversized_drawings_are_refused(scene, reason):
    with pytest.raises(ValueError, match=reason):
        excalidraw_safety.clean_scene(scene)


def test_board_saves_validate_drawings_and_only_diagrams_hold_them():
    node = dict(id='d', kind='diagram', title='Arch', text=FLOW, x=0, y=0, scene={"elements": [{**RECT, "link": "https://x"}]})
    saved = BoardUpdate(expected_version=1, title='Board', nodes=[node], edges=[])
    assert saved.nodes[0].scene["elements"][0]["link"] is None
    with pytest.raises(ValidationError):
        BoardUpdate(expected_version=1, title='Board', nodes=[{**node, 'kind': 'idea'}], edges=[])
    with pytest.raises(ValidationError):
        BoardUpdate(expected_version=1, title='Board', nodes=[{**node, 'scene': {"elements": [{**RECT, "type": "image"}]}}], edges=[])


def test_voice_change_to_a_diagram_drops_its_stale_drawing():
    diagram = dict(id='d', kind='diagram', title='Arch', text=FLOW, x=0, y=0, origin='manual', locked=False,
                   source_id=None, source_start_ms=None, scene={"elements": [RECT]})
    same, _ = apply_operations([diagram], [], [BoardOperation(op='set_diagram', node_id='d', title='Renamed', mermaid=FLOW)], uuid.uuid4())
    assert same[0]['scene'] == {"elements": [RECT]}
    changed, _ = apply_operations([diagram], [], [BoardOperation(op='set_diagram', node_id='d', mermaid=FLOW + ' --> x["X"]')], uuid.uuid4())
    assert 'scene' not in changed[0]
    edited, _ = apply_operations([diagram], [], [BoardOperation(op='update_node', node_id='d', text=FLOW + ' --> y["Y"]')], uuid.uuid4())
    assert 'scene' not in edited[0]
