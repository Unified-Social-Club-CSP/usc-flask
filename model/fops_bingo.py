""" Multiplayer Bingo rooms for the Friends of Poway Seniors website.

The rules engine here is a line-for-line port of fops-pages
assets/js/fops/bingo/engine.js. Both sides use the same seeded generator
(mulberry32), so for a given seed they produce the same cards and the same
calling order. A room only stores its seed and start time; every player's
browser works out the calls from those, and the server checks BINGO claims
with the same math instead of trusting the browser.
"""
import math
import random
import time
from datetime import datetime, timedelta

from __init__ import db

FREE = 0
MASK = 0xFFFFFFFF
ROOM_TTL = timedelta(hours=6)
START_DELAY_MS = 3000


# ---------- Rules engine (must match engine.js exactly) ----------

def mulberry32(seed):
    state = [seed & MASK]

    def next_value():
        state[0] = (state[0] + 0x6D2B79F5) & MASK
        t = state[0]
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t = t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK)
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return next_value


def shuffle(items, rng):
    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = math.floor(rng() * (i + 1))
        out[i], out[j] = out[j], out[i]
    return out


def call_order(seed):
    return shuffle(range(1, 76), mulberry32(seed))


def make_card(seed):
    rng = mulberry32(seed)
    card = []
    for col in range(5):
        low = col * 15 + 1
        card.append(shuffle(range(low, low + 15), rng)[:5])
    card[2][2] = FREE
    return card


def _lines():
    lines = []
    for i in range(5):
        lines.append([(i, r) for r in range(5)])
        lines.append([(c, i) for c in range(5)])
    lines.append([(i, i) for i in range(5)])
    lines.append([(i, 4 - i) for i in range(5)])
    return lines


LINES = _lines()


def winning_lines(card, called):
    def has(col, row):
        return card[col][row] == FREE or card[col][row] in called
    return [line for line in LINES if all(has(c, r) for c, r in line)]


def balls_called_at(started_at_ms, now_ms, interval_ms):
    if started_at_ms is None or now_ms < started_at_ms:
        return 0
    return min(75, (now_ms - started_at_ms) // interval_ms + 1)


def card_seed_for(room_seed, user_id):
    """Each player's card comes from the room seed and their user id."""
    return (room_seed * 31 + user_id * 2654435761) & MASK


def now_ms():
    return int(time.time() * 1000)


# ---------- Database models ----------

class BingoRoom(db.Model):
    __tablename__ = 'fops_bingo_rooms'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(8), unique=True, nullable=False)
    seed = db.Column(db.BigInteger, nullable=False)
    interval_ms = db.Column(db.Integer, nullable=False)
    host_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    started_at_ms = db.Column(db.BigInteger, nullable=True)
    winner_user_id = db.Column(db.Integer, nullable=True)
    winner_name = db.Column(db.String(255), nullable=True)
    winner_ball = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    players = db.relationship('BingoPlayer', backref='room', cascade='all, delete-orphan', lazy=True)

    @staticmethod
    def new_code():
        """Four digits: easy to read aloud and type on any phone."""
        for _ in range(50):
            code = f'{random.randint(0, 9999):04d}'
            if not BingoRoom.query.filter_by(code=code).first():
                return code
        raise RuntimeError('No room codes available')

    @staticmethod
    def remove_expired():
        cutoff = datetime.utcnow() - ROOM_TTL
        for room in BingoRoom.query.filter(BingoRoom.created_at < cutoff).all():
            db.session.delete(room)
        db.session.commit()

    def player_for(self, user_id):
        return next((p for p in self.players if p.user_id == user_id), None)

    def read(self, user_id):
        me = self.player_for(user_id)
        return {
            'code': self.code,
            'seed': self.seed,
            'interval_ms': self.interval_ms,
            'started_at_ms': self.started_at_ms,
            'server_now_ms': now_ms(),
            'is_host': self.host_user_id == user_id,
            'players': [p.name for p in sorted(self.players, key=lambda p: p.id)],
            'winner': {'name': self.winner_name, 'ball': self.winner_ball} if self.winner_name else None,
            'me': {'name': me.name, 'card_seed': me.card_seed} if me else None,
        }


class BingoPlayer(db.Model):
    __tablename__ = 'fops_bingo_players'
    __table_args__ = (db.UniqueConstraint('room_id', 'user_id', name='uq_fops_bingo_room_user'),)

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('fops_bingo_rooms.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    card_seed = db.Column(db.BigInteger, nullable=False)


def initBingoRooms():
    """Create the Bingo tables if they do not exist yet. Safe to run every start."""
    BingoRoom.__table__.create(bind=db.engine, checkfirst=True)
    BingoPlayer.__table__.create(bind=db.engine, checkfirst=True)
