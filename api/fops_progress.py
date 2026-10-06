""" API for saved game progress on the Friends of Poway Seniors website.

GET /api/fops/progress/<game>   the signed-in player's saved progress
PUT /api/fops/progress/<game>   save it, body: {"data": {...}}
GET /api/fops/progress          all of the signed-in player's games
"""
import json

from flask import Blueprint, request, g
from flask_restful import Api, Resource

from api.authorize import token_required
from model.fops_progress import GameProgress, FOPS_GAMES, MAX_DATA_BYTES

fops_progress_api = Blueprint('fops_progress_api', __name__, url_prefix='/api/fops')
api = Api(fops_progress_api)


class _GameProgress(Resource):
    @token_required()
    def get(self, game):
        if game not in FOPS_GAMES:
            return {'message': f'Unknown game: {game}'}, 404
        row = GameProgress.find(g.current_user.id, game)
        if row is None:
            return {'game': game, 'data': None}, 200
        return row.read(), 200

    @token_required()
    def put(self, game):
        if game not in FOPS_GAMES:
            return {'message': f'Unknown game: {game}'}, 404
        body = request.get_json(silent=True) or {}
        data = body.get('data')
        if not isinstance(data, dict):
            return {'message': 'Body must be {"data": {...}}'}, 400
        if len(json.dumps(data)) > MAX_DATA_BYTES:
            return {'message': 'Progress data is too large'}, 413
        row = GameProgress.save(g.current_user.id, game, data)
        return row.read(), 200


class _AllProgress(Resource):
    @token_required()
    def get(self):
        rows = GameProgress.query.filter_by(_user_id=g.current_user.id).all()
        return [row.read() for row in rows], 200


api.add_resource(_GameProgress, '/progress/<string:game>')
api.add_resource(_AllProgress, '/progress')
