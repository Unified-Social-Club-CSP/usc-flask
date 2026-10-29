#!/usr/bin/env python3
"""Verify the direct-messages API (api/fops_dm.py) through the real request stack.

Creates three throwaway accounts (a member, a second member, a volunteer), runs the
checks below, then deletes those accounts and their chats again.

Usage:  python scripts/verify_dm.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import os
import secrets
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)

from main import app  # noqa: E402
from __init__ import db  # noqa: E402
from model.user import User  # noqa: E402
from model.fops_dm import DMConversation, DMMessage, DMParticipant  # noqa: E402

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


def cleanup(ids):
    with app.app_context():
        convs = {p._conversation_id for p in DMParticipant.query.filter(DMParticipant._user_id.in_(ids)).all()}
        DMMessage.query.filter(DMMessage._conversation_id.in_(convs)).delete(synchronize_session=False)
        DMParticipant.query.filter(DMParticipant._conversation_id.in_(convs)).delete(synchronize_session=False)
        DMConversation.query.filter(DMConversation.id.in_(convs)).delete(synchronize_session=False)
        for user_id in ids:
            user = User.query.get(user_id)
            if user:
                db.session.delete(user)
        db.session.commit()


def main():
    tag = secrets.token_hex(3)
    senior, senior_id = make(f'dmsenior{tag}', 'User')
    other, other_id = make(f'dmother{tag}', 'User')
    volunteer, volunteer_id = make(f'dmvol{tag}', 'Volunteer')
    try:
        found = [p['uid'] for p in senior.get('/api/people/search?query=dm').get_json()]
        check('member search shows volunteers, not other members',
              f'dmvol{tag}' in found and f'dmother{tag}' not in found)
        check('member cannot start a chat with another member (403)',
              senior.post('/api/dm/conversations', json={'otherPersonIds': [other_id]}).status_code == 403)
        r = senior.post('/api/dm/conversations', json={'otherPersonIds': [volunteer_id]})
        conv = r.get_json()
        check('member can start a chat with a volunteer', r.status_code == 200 and conv.get('id'))
        again = senior.post('/api/dm/conversations', json={'otherPersonIds': [volunteer_id]}).get_json()
        check('starting the same chat again reuses it', again['id'] == conv['id'])
        check('member can send a message', senior.post(
            f"/api/dm/conversations/{conv['id']}/messages", json={'body': 'How do I sign up for Bingo?'}).status_code == 200)
        unread = volunteer.get('/api/dm/unread').get_json()
        check('volunteer bell shows 1 unread person',
              unread['count'] == 1 and unread['conversations'].get(str(conv['id'])) == 1)
        msgs = volunteer.get(f"/api/dm/conversations/{conv['id']}/messages").get_json()
        check('volunteer can read it, with the sender', msgs and msgs[0]['senderUid'] == f'dmsenior{tag}')
        volunteer.post(f"/api/dm/conversations/{conv['id']}/read")
        check('marking read clears the bell', volunteer.get('/api/dm/unread').get_json()['count'] == 0)
        volunteer.post(f"/api/dm/conversations/{conv['id']}/messages", json={'body': 'Tuesdays at 11:30!'})
        newer = senior.get(f"/api/dm/conversations/{conv['id']}/messages?after={msgs[0]['id']}").get_json()
        check('?after returns only newer messages', len(newer) == 1)
        check('someone outside the chat gets 404',
              other.get(f"/api/dm/conversations/{conv['id']}/messages").status_code == 404)
        check('volunteer can start a chat with a member',
              volunteer.post('/api/dm/conversations', json={'otherPersonIds': [other_id]}).status_code == 200)
        check('empty message is rejected (400)', senior.post(
            f"/api/dm/conversations/{conv['id']}/messages", json={'body': '  '}).status_code == 400)
        check('signed out gets 401', app.test_client().get('/api/dm/conversations').status_code == 401)
    finally:
        cleanup([senior_id, other_id, volunteer_id])
    print(f'{sum(_results)} / {len(_results)} checks passed')
    return 0 if all(_results) else 1


if __name__ == '__main__':
    sys.exit(main())
