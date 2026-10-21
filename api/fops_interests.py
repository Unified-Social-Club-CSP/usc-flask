""" API for the interest survey on the Friends of Poway Seniors profile page.

GET /api/fops/profile/interests           the signed-in member's answers
PUT /api/fops/profile/interests           save them, body: {"answers": {...}}
GET /api/fops/profile/interests/summary   totals across members (Admin only, no names)
"""
from flask import Blueprint, request, g
from flask_restful import Api, Resource

from api.authorize import token_required
from model.fops_interests import InterestSurvey, QUESTIONS, clean_answers

fops_interests_api = Blueprint('fops_interests_api', __name__, url_prefix='/api/fops/profile')
api = Api(fops_interests_api)


class _Interests(Resource):
    @token_required()
    def get(self):
        row = InterestSurvey.find(g.current_user.id)
        if row is None:
            return {'answers': None, 'questions': QUESTIONS}, 200
        return {**row.read(), 'questions': QUESTIONS}, 200

    @token_required()
    def put(self):
        body = request.get_json(silent=True) or {}
        answers, error = clean_answers(body.get('answers'))
        if error:
            return {'message': error}, 400
        row = InterestSurvey.save(g.current_user.id, answers)
        return row.read(), 200


class _Summary(Resource):
    @token_required(['Admin'])
    def get(self):
        return InterestSurvey.summary(), 200


api.add_resource(_Interests, '/interests')
api.add_resource(_Summary, '/interests/summary')
