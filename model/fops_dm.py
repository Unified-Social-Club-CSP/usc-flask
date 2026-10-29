""" Direct messages between Friends of Poway Seniors members and the volunteers who help them.

Same shape as the Open Coding Society DM system (Open-Coding-Society/spring /api/dm), so
OCS's DM chat and navbar bell work against this backend.

Safety rule for a seniors' site: a regular member can only start a chat with staff
(Admin, Teacher, or Volunteer), never with another member, so strangers can't
message seniors privately. Staff can message anyone.
"""
from datetime import datetime

from __init__ import db
from model.user import User

STAFF_ROLES = ['Admin', 'Teacher', 'Volunteer']
MAX_PARTICIPANTS = 8
MAX_BODY = 2000


def is_staff(user):
    return user is not None and user.role in STAFF_ROLES


def person(user):
    """The public view of a user in DMs: never email, password, or other private fields."""
    return {'id': user.id, 'uid': user.uid, 'name': user.name, 'role': user.role}


class DMConversation(db.Model):
    __tablename__ = 'fops_dm_conversations'

    id = db.Column(db.Integer, primary_key=True)
    _created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    _last_message_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    participants = db.relationship('DMParticipant', backref='conversation', cascade='all, delete-orphan', lazy=True)

    def user_ids(self):
        return sorted(p._user_id for p in self.participants)

    def participant(self, user_id):
        return next((p for p in self.participants if p._user_id == user_id), None)

    def unread_for(self, user_id):
        """Messages from other people sent after this user last read the conversation."""
        me = self.participant(user_id)
        query = DMMessage.query.filter(DMMessage._conversation_id == self.id, DMMessage._sender_id != user_id)
        if me and me._last_read_at:
            query = query.filter(DMMessage._sent_at > me._last_read_at)
        return query.count()

    def read(self, user_id):
        users = User.query.filter(User.id.in_(self.user_ids())).all()
        return {
            'id': self.id,
            'participants': [person(u) for u in users],
            'unreadCount': self.unread_for(user_id),
            'lastMessageAt': self._last_message_at.isoformat() + 'Z',
        }

    @staticmethod
    def for_user(user_id):
        return (DMConversation.query.join(DMParticipant)
                .filter(DMParticipant._user_id == user_id)
                .order_by(DMConversation._last_message_at.desc()).all())

    @staticmethod
    def find_exact(user_ids):
        """The existing conversation with exactly these people, so starting a chat twice reuses it."""
        wanted = sorted(set(user_ids))
        for conversation in DMConversation.for_user(wanted[0]):
            if conversation.user_ids() == wanted:
                return conversation
        return None

    @staticmethod
    def start(user_ids):
        conversation = DMConversation.find_exact(user_ids)
        if conversation:
            return conversation
        conversation = DMConversation()
        for user_id in sorted(set(user_ids)):
            conversation.participants.append(DMParticipant(_user_id=user_id))
        db.session.add(conversation)
        db.session.commit()
        return conversation


class DMParticipant(db.Model):
    __tablename__ = 'fops_dm_participants'

    id = db.Column(db.Integer, primary_key=True)
    _conversation_id = db.Column(db.Integer, db.ForeignKey('fops_dm_conversations.id'), nullable=False)
    _user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    _last_read_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('_conversation_id', '_user_id'),)


class DMMessage(db.Model):
    __tablename__ = 'fops_dm_messages'

    id = db.Column(db.Integer, primary_key=True)
    _conversation_id = db.Column(db.Integer, db.ForeignKey('fops_dm_conversations.id'), nullable=False)
    _sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    _body = db.Column(db.Text, nullable=False)
    _sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def read(self):
        sender = User.query.get(self._sender_id)
        return {
            'id': self.id,
            'conversationId': self._conversation_id,
            'senderUid': sender.uid if sender else None,
            'senderName': sender.name if sender else 'Former member',
            'body': self._body,
            'sentAt': self._sent_at.isoformat() + 'Z',
        }


def initDirectMessages():
    """Create the DM tables if they do not exist yet. Safe to run every start."""
    db.create_all()
