""" Club Jeopardy boards and game results for the Unified Social Club website.

A board is a list of categories, each with clues worth 100 to 500 points. Every
clue has 2 to 4 picture answers and `answer` is the index of the right one, the
same shape the website uses (usc-pages assets/js/usc/jeopardy-data.js).
Volunteers write boards; anyone can play them. When a game ends, the website
saves each team's score, and the server checks the scores are possible on
that board before keeping them.
"""
import json
import os
from datetime import datetime

from __init__ import db

LEVELS = ('easy', 'harder')
VALUES = (100, 200, 300, 400, 500)
MAX_CATEGORIES = 6
MAX_CLUES = 5
MIN_CHOICES, MAX_CHOICES = 2, 4
MAX_TEAMS = 4
DEFAULT_BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'usc_jeopardy_default.json')


# ---------- Checking what volunteers and players send ----------

def _text(value, label, limit):
    text = str(value or '').strip()
    if not text:
        raise ValueError(f'{label} is empty.')
    if len(text) > limit:
        raise ValueError(f'{label} is too long (at most {limit} letters).')
    return text


def clean_board(body):
    """Return a safe copy of a board, or raise ValueError with a plain-words reason."""
    if not isinstance(body, dict):
        raise ValueError('Send the board as {"name": ..., "level": ..., "categories": [...]}.')
    name = _text(body.get('name'), 'Board name', 60)
    level = body.get('level', 'easy')
    if level not in LEVELS:
        raise ValueError(f'Level must be one of {", ".join(LEVELS)}.')

    categories = body.get('categories')
    if not isinstance(categories, list) or not 1 <= len(categories) <= MAX_CATEGORIES:
        raise ValueError(f'A board needs 1 to {MAX_CATEGORIES} categories.')

    cleaned = []
    for c, category in enumerate(categories, start=1):
        if not isinstance(category, dict):
            raise ValueError(f'Category {c} is not filled in.')
        clues = category.get('clues')
        if not isinstance(clues, list) or not 1 <= len(clues) <= MAX_CLUES:
            raise ValueError(f'Category {c} needs 1 to {MAX_CLUES} clues.')
        out = {
            'name': _text(category.get('name'), f'Category {c} name', 40),
            'icon': str(category.get('icon') or '⭐').strip()[:8],
            'clues': [],
        }
        for q, clue in enumerate(clues, start=1):
            where = f'Category {c}, clue {q}'
            if not isinstance(clue, dict):
                raise ValueError(f'{where} is not filled in.')
            if clue.get('value') not in VALUES:
                raise ValueError(f'{where}: points must be one of {", ".join(map(str, VALUES))}.')
            choices = clue.get('choices')
            if not isinstance(choices, list) or not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
                raise ValueError(f'{where} needs {MIN_CHOICES} to {MAX_CHOICES} answers.')
            answer = clue.get('answer')
            if not isinstance(answer, int) or isinstance(answer, bool) or not 0 <= answer < len(choices):
                raise ValueError(f'{where}: pick which answer is right.')
            out['clues'].append({
                'value': clue['value'],
                'clue': _text(clue.get('clue'), f'{where} question', 200),
                'choices': [{
                    'emoji': str((choice or {}).get('emoji') or '').strip()[:8],
                    'label': _text((choice or {}).get('label'), f'{where}, answer {a}', 40),
                } for a, choice in enumerate(choices, start=1)],
                'answer': answer,
            })
        cleaned.append(out)
    return {'name': name, 'level': level, 'categories': cleaned}


def board_points(categories):
    return sum(clue['value'] for category in categories for clue in category['clues'])


def check_scores(teams, categories):
    """Return a clean team list, or raise ValueError if the scores can't happen on this board.

    Every right answer adds that clue's points to one team, and a wrong answer adds
    nothing, so each score is a multiple of 100 and all the scores together are at
    most the points on the whole board.
    """
    if not isinstance(teams, list) or not 2 <= len(teams) <= MAX_TEAMS:
        raise ValueError(f'A game has 2 to {MAX_TEAMS} teams.')
    total = board_points(categories)
    clean = []
    for t, team in enumerate(teams, start=1):
        score = (team or {}).get('score')
        if not isinstance(score, int) or isinstance(score, bool) or score < 0 or score % 100:
            raise ValueError(f'Team {t} has a score that is not possible.')
        clean.append({'name': _text((team or {}).get('name'), f'Team {t} name', 30), 'score': score})
    if sum(team['score'] for team in clean) > total:
        raise ValueError(f'These scores add up to more than the {total} points on the board.')
    return clean


def winners(teams):
    """Names of the team or teams with the most points (more than one means a tie)."""
    top = max(team['score'] for team in teams)
    return [team['name'] for team in teams if team['score'] == top]


# ---------- Database models ----------

class JeopardyBoard(db.Model):
    __tablename__ = 'usc_jeopardy_boards'

    id = db.Column(db.Integer, primary_key=True)
    _name = db.Column(db.String(60), nullable=False)
    _level = db.Column(db.String(10), nullable=False, default='easy')
    _categories = db.Column(db.Text, nullable=False)
    _created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    _updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    results = db.relationship('JeopardyResult', backref='board', cascade='all, delete-orphan', lazy=True)

    def __init__(self, board, created_by=None):
        self.update(board)
        self._created_by = created_by

    @property
    def categories(self):
        return json.loads(self._categories)

    def update(self, board):
        """board must already be cleaned by clean_board."""
        self._name = board['name']
        self._level = board['level']
        self._categories = json.dumps(board['categories'])

    def read(self, full=True):
        categories = self.categories
        out = {
            'id': self.id,
            'name': self._name,
            'level': self._level,
            'category_count': len(categories),
            'clue_count': sum(len(c['clues']) for c in categories),
            'points': board_points(categories),
            'plays': len(self.results),
            'updated_at': self._updated_at.isoformat() if self._updated_at else None,
        }
        if full:
            out['categories'] = categories
        return out


class JeopardyResult(db.Model):
    __tablename__ = 'usc_jeopardy_results'

    id = db.Column(db.Integer, primary_key=True)
    _board_id = db.Column(db.Integer, db.ForeignKey('usc_jeopardy_boards.id'), nullable=False)
    _user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    _teams = db.Column(db.Text, nullable=False)
    _played_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, board_id, user_id, teams):
        self._board_id = board_id
        self._user_id = user_id
        self._teams = json.dumps(teams)

    def read(self):
        teams = json.loads(self._teams)
        return {
            'id': self.id,
            'board_id': self._board_id,
            'teams': teams,
            'winners': winners(teams),
            'played_at': self._played_at.isoformat() if self._played_at else None,
        }


def initJeopardy():
    """Create the Jeopardy tables, and the Club Life board if there are no boards yet.
    Safe to run every start."""
    JeopardyBoard.__table__.create(bind=db.engine, checkfirst=True)
    JeopardyResult.__table__.create(bind=db.engine, checkfirst=True)
    if JeopardyBoard.query.first() is None:
        with open(DEFAULT_BOARD, encoding='utf-8') as f:
            db.session.add(JeopardyBoard(clean_board(json.load(f))))
        db.session.commit()
