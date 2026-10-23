""" Interest survey answers for the Friends of Poway Seniors profile page.

One row per member. The answers personalize the website (which games and events
show first) and, added up across members, help volunteers plan events.
"""
import json
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from __init__ import db
from model.user import User

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

# Plain-word text for the results page, matching the wording on the profile page.
LABELS = {
    'goals': ('What would you like to do here?', {
        'games': 'Play games', 'scams': 'Stay safe from scams', 'exercise': 'Exercise',
        'events': 'Come to events', 'tech-help': 'Get tech help'}),
    'comfort': ('How comfortable are you with phones and computers?', {
        'starting': 'Just starting', 'okay': 'Okay', 'comfortable': 'Very comfortable'}),
    'scam_contact': ('Have you gotten a scam message or call this year?', {
        'yes': 'Yes', 'not-sure': 'Not sure', 'no': 'No'}),
    'events': ('Which events interest you?', {
        'bingo': 'Bingo', 'tech-help': 'Tech help', 'lunches': 'Lunches',
        'exercise': 'Exercise classes', 'trips': 'Trips'}),
    'reminders': ('How do you prefer to be reminded?', {
        'email': 'Email', 'phone': 'Phone call', 'none': 'No reminders'}),
    'volunteer': ('Would you like to volunteer?', {
        'yes': 'Yes', 'maybe': 'Maybe later', 'no': 'No'}),
}

# Who may see survey results. Totals have no names; individual answers do.
# Answering "yes" to the volunteer question never changes anyone's role.
SUMMARY_ROLES = ['Admin', 'Volunteer']
RESPONSE_ROLES = ['Admin']


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
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            raise
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

    @staticmethod
    def responses():
        """Every member's answers with their name, newest first. Admin only."""
        rows = (db.session.query(InterestSurvey, User)
                .join(User, User.id == InterestSurvey._user_id)
                .order_by(InterestSurvey._updated_at.desc())
                .all())
        return [{'name': user.name, 'uid': user.uid, 'active': user.active, **row.read()}
                for row, user in rows]


def initInterestSurveys():
    """Create the survey table if it does not exist yet. Safe to run every start."""
    InterestSurvey.__table__.create(bind=db.engine, checkfirst=True)
