""" Direct messages API, same routes and JSON as the Open Coding Society DM system.

GET  /api/dm/conversations                      the signed-in user's chats, newest first
POST /api/dm/conversations                      start (or reuse) a chat, body: {"otherPersonIds": [..]}
GET  /api/dm/conversations/<id>/messages        message history (?after=<message id> for only newer ones)
POST /api/dm/conversations/<id>/messages        send, body: {"body": "..."}
POST /api/dm/conversations/<id>/read            mark the chat read
GET  /api/dm/unread                             {count, people, conversations} for the navbar bell
GET  /api/people/search?query=                  people you are allowed to message

Approved accounts only. Members can only start chats with staff (model/fops_dm.py),
and every chat route checks the signed-in user is in that chat.
"""
from datetime import datetime

from flask import Blueprint, request, g
from flask_restful import Api, Resource
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from __init__ import db
from api.authorize import token_required
from model.user import User
from model.fops_dm import (DMConversation, DMMessage, STAFF_ROLES, MAX_PARTICIPANTS, MAX_BODY,
                           is_staff, person)

fops_dm_api = Blueprint('fops_dm_api', __name__, url_prefix='/api')
api = Api(fops_dm_api)


def my_conversation(conversation_id):
    """The chat if the signed-in user is in it, else None (so others' chats look like 404s)."""
    conversation = DMConversation.query.get(conversation_id)
    if conversation and conversation.participant(g.current_user.id):
        return conversation
    return None


class _Conversations(Resource):
    @token_required()
    def get(self):
        me = g.current_user.id
        return [c.read(me) for c in DMConversation.for_user(me)], 200

    @token_required()
    def post(self):
        body = request.get_json(silent=True) or {}
        ids = body.get('otherPersonIds')
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) for i in ids):
            return {'message': 'otherPersonIds must be a list of user ids'}, 400
        me = g.current_user
        others = User.query.filter(User.id.in_(set(ids) - {me.id})).all()
        if len(others) != len(set(ids) - {me.id}) or not others:
            return {'message': 'Someone in that list does not exist'}, 404
        if len(others) + 1 > MAX_PARTICIPANTS:
            return {'message': f'A chat can have at most {MAX_PARTICIPANTS} people'}, 400
        if not is_staff(me) and not all(is_staff(o) for o in others):
            return {'message': 'Members can message volunteers and staff only'}, 403
        try:
            conversation = DMConversation.start([me.id] + [o.id for o in others])
        except SQLAlchemyError:
            db.session.rollback()
            return {'message': 'Could not start the chat. Please try again.'}, 500
        return conversation.read(me.id), 200


class _Messages(Resource):
    @token_required()
    def get(self, conversation_id):
        conversation = my_conversation(conversation_id)
        if not conversation:
            return {'message': 'Chat not found'}, 404
        query = DMMessage.query.filter_by(_conversation_id=conversation.id)
        after = request.args.get('after', type=int)
        if after:
            query = query.filter(DMMessage.id > after)
        return [m.read() for m in query.order_by(DMMessage.id).limit(500).all()], 200

    @token_required()
    def post(self, conversation_id):
        conversation = my_conversation(conversation_id)
        if not conversation:
            return {'message': 'Chat not found'}, 404
        text = ((request.get_json(silent=True) or {}).get('body') or '').strip()
        if not text:
            return {'message': 'Message is empty'}, 400
        if len(text) > MAX_BODY:
            return {'message': f'Messages can be at most {MAX_BODY} characters'}, 400
        now = datetime.utcnow()
        try:
            message = DMMessage(_conversation_id=conversation.id, _sender_id=g.current_user.id, _body=text, _sent_at=now)
            conversation._last_message_at = now
            # Your own message counts as read.
            conversation.participant(g.current_user.id)._last_read_at = now
            db.session.add(message)
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            return {'message': 'Could not send. Please try again.'}, 500
        return message.read(), 200


class _Read(Resource):
    @token_required()
    def post(self, conversation_id):
        conversation = my_conversation(conversation_id)
        if not conversation:
            return {'message': 'Chat not found'}, 404
        conversation.participant(g.current_user.id)._last_read_at = datetime.utcnow()
        db.session.commit()
        return {'id': conversation.id, 'unreadCount': 0}, 200


class _Unread(Resource):
    @token_required()
    def get(self):
        me = g.current_user.id
        counts, senders = {}, {}
        for conversation in DMConversation.for_user(me):
            unread = conversation.unread_for(me)
            if not unread:
                continue
            counts[str(conversation.id)] = unread
            mine = conversation.participant(me)
            query = DMMessage.query.filter(DMMessage._conversation_id == conversation.id, DMMessage._sender_id != me)
            if mine._last_read_at:
                query = query.filter(DMMessage._sent_at > mine._last_read_at)
            for message in query.all():
                senders[message._sender_id] = True
        people = [person(u) for u in User.query.filter(User.id.in_(senders.keys())).all()] if senders else []
        return {'count': len(people), 'people': people, 'conversations': counts}, 200


class _PeopleSearch(Resource):
    @token_required()
    def get(self):
        text = (request.args.get('query') or '').strip()
        me = g.current_user
        query = User.query.filter(User.id != me.id, User.active.is_(True))
        if not is_staff(me):
            query = query.filter(User._role.in_(STAFF_ROLES))
        if text:
            like = f'%{text}%'
            query = query.filter(or_(User._name.ilike(like), User._uid.ilike(like)))
        return [person(u) for u in query.order_by(User._name).limit(20).all()], 200


api.add_resource(_Conversations, '/dm/conversations')
api.add_resource(_Messages, '/dm/conversations/<int:conversation_id>/messages')
api.add_resource(_Read, '/dm/conversations/<int:conversation_id>/read')
api.add_resource(_Unread, '/dm/unread')
api.add_resource(_PeopleSearch, '/people/search')
