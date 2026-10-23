""" API for the interest survey on the Friends of Poway Seniors profile page.

GET /api/fops/profile/me                  who is signed in: id, uid, name, role, active
GET /api/fops/profile/interests           the signed-in member's answers
PUT /api/fops/profile/interests           save them, body: {"answers": {...}}
GET /api/fops/profile/interests/summary   totals across members (Admin or Volunteer, no names)

A new account waits for verification, but the member can still fill in the survey right
after signup, so the first three allow pending accounts. They only ever touch the
signed-in member's own row; role and activation are never set here.
"""
from flask import Blueprint, request, g
from flask_restful import Api, Resource
from sqlalchemy.exc import SQLAlchemyError

from api.authorize import token_required
from model.fops_interests import InterestSurvey, QUESTIONS, SUMMARY_ROLES, clean_answers

fops_interests_api = Blueprint('fops_interests_api', __name__, url_prefix='/api/fops/profile')
api = Api(fops_interests_api)


class _Me(Resource):
    @token_required(allow_pending=True)
    def get(self):
        user = g.current_user
        return {'id': user.id, 'uid': user.uid, 'name': user.name,
                'role': user.role, 'active': bool(user.active)}, 200


class _Interests(Resource):
    @token_required(allow_pending=True)
    def get(self):
        row = InterestSurvey.find(g.current_user.id)
        if row is None:
            return {'answers': None, 'questions': QUESTIONS}, 200
        return {**row.read(), 'questions': QUESTIONS}, 200

    @token_required(allow_pending=True)
    def put(self):
        body = request.get_json(silent=True)
        # Only {"answers": {...}} is accepted, so a user_id or uid in the body
        # can't point the save at someone else's row.
        if not isinstance(body, dict) or set(body) != {'answers'}:
            return {'message': 'Body must be {"answers": {...}}'}, 400
        answers, error = clean_answers(body['answers'])
        if error:
            return {'message': error}, 400
        try:
            row = InterestSurvey.save(g.current_user.id, answers)
        except SQLAlchemyError:
            return {'message': 'Could not save your answers. Please try again.'}, 500
        return row.read(), 200


class _Summary(Resource):
    @token_required(SUMMARY_ROLES)
    def get(self):
        return InterestSurvey.summary(), 200


api.add_resource(_Me, '/me')
api.add_resource(_Interests, '/interests')
api.add_resource(_Summary, '/interests/summary')
