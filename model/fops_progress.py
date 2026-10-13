""" Saved game progress for the Friends of Poway Seniors website.

One row per (user, game). The data column holds the game's own JSON, such as
the Spot the Scam practice schedule or Bingo and movement-game records, so a
signed-in player picks up where they left off on any computer.
"""
import json
from datetime import datetime

from __init__ import db

# Games the website is allowed to save. Anything else is rejected.
FOPS_GAMES = ('scam-trainer', 'bingo', 'movement', 'geography')
MAX_DATA_BYTES = 20_000


class GameProgress(db.Model):
    __tablename__ = 'fops_game_progress'
    __table_args__ = (db.UniqueConstraint('_user_id', '_game', name='uq_fops_user_game'),)

    id = db.Column(db.Integer, primary_key=True)
    _user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    _game = db.Column(db.String(40), nullable=False)
    _data = db.Column(db.Text, nullable=False, default='{}')
    _updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, user_id, game, data=None):
        self._user_id = user_id
        self._game = game
        self._data = json.dumps(data or {})

    @property
    def data(self):
        return json.loads(self._data)

    @data.setter
    def data(self, value):
        self._data = json.dumps(value)

    def read(self):
        return {
            'game': self._game,
            'data': self.data,
            'updated_at': self._updated_at.isoformat() if self._updated_at else None,
        }

    @staticmethod
    def find(user_id, game):
        return GameProgress.query.filter_by(_user_id=user_id, _game=game).first()

    @staticmethod
    def save(user_id, game, data):
        row = GameProgress.find(user_id, game)
        if row is None:
            row = GameProgress(user_id, game, data)
            db.session.add(row)
        else:
            row.data = data
        db.session.commit()
        return row


def initGameProgress():
    """Create the progress table if it does not exist yet. Safe to run every start."""
    GameProgress.__table__.create(bind=db.engine, checkfirst=True)
