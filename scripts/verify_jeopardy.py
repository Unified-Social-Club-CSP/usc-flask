#!/usr/bin/env python3
"""Verify the Club Jeopardy API (api/usc_jeopardy.py) through the real request stack.

Creates two throwaway accounts (a member and a volunteer), runs the checks below,
then deletes those accounts and the board and games they made.

Usage:  python scripts/verify_jeopardy.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import copy
import os
import secrets
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

from main import app  # noqa: E402
from __init__ import db  # noqa: E402
from model.user import User  # noqa: E402
from model.usc_jeopardy import JeopardyBoard, JeopardyResult  # noqa: E402

PASSWORD = secrets.token_urlsafe(12)
_results = []


def check(label, cond):
    print(('PASS  ' if cond else 'FAIL  ') + label)
    _results.append(bool(cond))


def make(uid, role):
    client = app.test_client()
    client.post('/api/user', json={'name': uid.title(), 'uid': uid, 'password': PASSWORD})
    with app.app_context():
        user = User.query.filter_by(_uid=uid).first()
        user._role = role
        user.active = True
        db.session.commit()
        user_id = user.id
    assert client.post('/api/authenticate', json={'uid': uid, 'password': PASSWORD}).status_code == 200
    return client, user_id


def cleanup(user_ids, board_ids):
    with app.app_context():
        JeopardyResult.query.filter(JeopardyResult._user_id.in_(user_ids)).delete(synchronize_session=False)
        for board_id in board_ids:
            board = JeopardyBoard.query.get(board_id)
            if board:
                db.session.delete(board)
        for user_id in user_ids:
            user = User.query.get(user_id)
            if user:
                db.session.delete(user)
        db.session.commit()


SMALL_BOARD = {
    'name': 'Test Board',
    'level': 'easy',
    'categories': [{
        'name': 'Sports', 'icon': '⚽',
        'clues': [
            {'value': 100, 'clue': 'What do you kick in soccer?', 'answer': 0,
             'choices': [{'emoji': '⚽', 'label': 'A ball'}, {'emoji': '🍎', 'label': 'An apple'}]},
            {'value': 200, 'clue': 'How many players are on a basketball team on the court?', 'answer': 1,
             'choices': [{'emoji': '2️⃣', 'label': '2'}, {'emoji': '5️⃣', 'label': '5'}, {'emoji': '🔟', 'label': '10'}]},
        ],
    }],
}


def main():
    tag = secrets.token_hex(3)
    member, member_id = make(f'jpmember{tag}', 'User')
    volunteer, volunteer_id = make(f'jpvol{tag}', 'Volunteer')
    guest = app.test_client()
    made = []
    try:
        boards = guest.get('/api/usc/jeopardy/boards').get_json()
        check('anyone can list boards, and the Club Life board is there',
              any(b['name'] == 'Club Life' and b['clue_count'] == 18 for b in boards))
        check('the board list leaves out the clues', all('categories' not in b for b in boards))
        club = guest.get(f"/api/usc/jeopardy/boards/{boards[0]['id']}").get_json()
        check('one board comes with its categories and clues', len(club['categories']) >= 1)

        check('a member cannot add a board (403)',
              member.post('/api/usc/jeopardy/boards', json=SMALL_BOARD).status_code == 403)
        r = volunteer.post('/api/usc/jeopardy/boards', json=SMALL_BOARD)
        board = r.get_json()
        made.append(board.get('id'))
        check('a volunteer can add a board', r.status_code == 201 and board['points'] == 300)

        bad = copy.deepcopy(SMALL_BOARD)
        bad['categories'][0]['clues'][0]['answer'] = 5
        r = volunteer.post('/api/usc/jeopardy/boards', json=bad)
        check('a right answer that is not one of the choices is refused (400)',
              r.status_code == 400 and 'pick which answer' in r.get_json()['message'])
        bad = copy.deepcopy(SMALL_BOARD)
        bad['categories'][0]['clues'][0]['value'] = 150
        check('points that are not 100 to 500 are refused (400)',
              volunteer.post('/api/usc/jeopardy/boards', json=bad).status_code == 400)

        changed = copy.deepcopy(SMALL_BOARD)
        changed['name'] = 'Test Board, Harder'
        changed['level'] = 'harder'
        r = volunteer.put(f"/api/usc/jeopardy/boards/{board['id']}", json=changed)
        check('a volunteer can change a board', r.status_code == 200 and r.get_json()['level'] == 'harder')

        url = f"/api/usc/jeopardy/boards/{board['id']}/results"
        check('saving a game needs an account (401)',
              guest.post(url, json={'teams': [{'name': 'Team 1', 'score': 100}, {'name': 'Team 2', 'score': 0}]}).status_code == 401)
        r = member.post(url, json={'teams': [{'name': 'Team 1', 'score': 100}, {'name': 'Team 2', 'score': 200}]})
        check('a member can save a finished game, and the winner is worked out',
              r.status_code == 201 and r.get_json()['winners'] == ['Team 2'])
        r = member.post(url, json={'teams': [{'name': 'Team 1', 'score': 300}, {'name': 'Team 2', 'score': 100}]})
        check('scores adding up to more than the board are refused (400)', r.status_code == 400)
        r = member.post(url, json={'teams': [{'name': 'Team 1', 'score': 150}, {'name': 'Team 2', 'score': 0}]})
        check('a score that is not a multiple of 100 is refused (400)', r.status_code == 400)
        r = member.post(url, json={'teams': [{'name': 'Team 1', 'score': 100}, {'name': 'Team 2', 'score': 100}]})
        check('a tie lists both teams as winners', r.get_json()['winners'] == ['Team 1', 'Team 2'])
        recent = guest.get(url).get_json()
        check('recent games come back newest first', len(recent) == 2 and recent[0]['winners'] == ['Team 1', 'Team 2'])
        check('the board counts its plays', guest.get(f"/api/usc/jeopardy/boards/{board['id']}").get_json()['plays'] == 2)

        check('a member cannot remove a board (403)',
              member.delete(f"/api/usc/jeopardy/boards/{board['id']}").status_code == 403)
        check('a volunteer can remove a board',
              volunteer.delete(f"/api/usc/jeopardy/boards/{board['id']}").status_code == 200)
        check('a removed board is gone (404)',
              guest.get(f"/api/usc/jeopardy/boards/{board['id']}").status_code == 404)
    finally:
        cleanup([member_id, volunteer_id], [b for b in made if b])
    print(f'{sum(_results)} / {len(_results)} checks passed')
    return 0 if all(_results) else 1


if __name__ == '__main__':
    sys.exit(main())
