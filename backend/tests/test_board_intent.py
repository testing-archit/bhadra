import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bot'))
from board_intent import board_intent
sys.path.pop(0)


@pytest.mark.parametrize('question,active,task,expected', [
    ('open a whiteboard', False, False, 'open'),
    ('Open Fig Jam', False, False, 'open'),
    ('Please just open up FigJam', False, False, 'open'),
    ('I need you to open Jam boards', False, False, 'open'),
    ('Launch FigJam', False, False, 'open'),
    ('can you please open and present the whiteboard', False, False, 'open_present'),
    ('present the board', False, False, 'present'),
    ('stop presenting', True, False, 'stop'),
    ('add signup and verification', True, False, 'edit'),
    ('move verification before payment on the board', False, False, 'edit'),
    ('undo that', True, False, 'edit'),
    ('add task: Ravi to send the report', True, True, None),
    ('add task: Ravi to review the board', True, True, None),
    ("don't delete the board", True, False, None),
    ('we should open a whiteboard later', True, False, None),
    ('share the file', False, False, None),
    ('share the file', True, False, None),
    ('present it', True, False, 'present'),
    ('undo that', False, False, None),
])
def test_routes_only_explicit_board_requests(question, active, task, expected):
    assert board_intent(question, active, task) == expected


@pytest.mark.parametrize('question,expected', [
    ('draw a signup, verification and payment flow', 'edit'),
    ('sketch the architecture', 'edit'),
    ('map out the payment flow', 'edit'),
    ('create a signup flow', 'open'),
    ('make sure the flow works', None),
    ('add a task to draw the flow', None),
])
def test_drawing_requests_route_to_the_board_before_one_is_open(question, expected):
    assert board_intent(question, False) == expected
