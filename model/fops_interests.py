""" Interest survey answers for the Friends of Poway Seniors profile page.

One row per member. The answers personalize the website (which games and events
show first) and, added up across members, help volunteers plan events.
"""
import json
from datetime import datetime

from __init__ import db

# Every question the survey can ask, and the answers it accepts.
# "many" questions take a list of answers; the others take one.
QUESTIONS = {
    'goals': {'many': True, 'options': ['games', 'scams', 'exercise', 'events', 'tech-help']},
    'comfort': {'many': False, 'options': ['starting', 'okay', 'comfortable']},
    'scam_contact': {'many': False, 'options': ['yes', 'not-sure', 'no']},
    'events': {'many': True, 'options': ['bingo', 'tech-help', 'lunches', 'exercise', 'trips']},
    'reminders': {'many': False, 'options': ['email', 'phone', 'none']},
    'volunteer': {'many': False, 'options': ['yes', 'maybe', 'no']},
}


def clean_answers(raw):
    """Keep only known questions and allowed answers. Returns (answers, error)."""
    if not isinstance(raw, dict):
        return None, 'Answers must be an object'
    answers = {}
    for key, value in raw.items():
        question = QUESTIONS.get(key)
        if question is None:
            return None, f'Unknown question: {key}'
        allowed = question['options']
        if question['many']:
            if not isinstance(value, list) or any(v not in allowed for v in value):
                return None, f'{key} must be a list of: {", ".join(allowed)}'
            answers[key] = list(dict.fromkeys(value))  # drop repeats, keep order
        else:
            if value not in allowed:
                return None, f'{key} must be one of: {", ".join(allowed)}'
            answers[key] = value
    return answers, None


class InterestSurvey(db.Model):
    __tablename__ = 'fops_interest_surveys'

    id = db.Column(db.Integer, primary_key=True)
    _user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    _answers = db.Column(db.Text, nullable=False, default='{}')
    _updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, user_id, answers=None):
        self._user_id = user_id
        self._answers = json.dumps(answers or {})

    @property
    def answers(self):
        return json.loads(self._answers)

    def read(self):
        return {
            'answers': self.answers,
            'updated_at': self._updated_at.isoformat() if self._updated_at else None,
        }

    @staticmethod
    def find(user_id):
        return InterestSurvey.query.filter_by(_user_id=user_id).first()

    @staticmethod
    def save(user_id, answers):
        row = InterestSurvey.find(user_id)
        if row is None:
            row = InterestSurvey(user_id, answers)
            db.session.add(row)
        else:
            row._answers = json.dumps(answers)
        db.session.commit()
        return row

    @staticmethod
    def summary():
        """How many members picked each answer. Counts only, no names."""
        counts = {key: {option: 0 for option in q['options']} for key, q in QUESTIONS.items()}
        rows = InterestSurvey.query.all()
        for row in rows:
            for key, value in row.answers.items():
                if key not in counts:
                    continue
                for option in (value if isinstance(value, list) else [value]):
                    if option in counts[key]:
                        counts[key][option] += 1
        return {'responses': len(rows), 'counts': counts}


def initInterestSurveys():
    """Create the survey table if it does not exist yet. Safe to run every start."""
    InterestSurvey.__table__.create(bind=db.engine, checkfirst=True)
