""" Club Jeopardy API for the Unified Social Club website.

GET    /api/usc/jeopardy/boards                 every board (no clues), for the board picker
GET    /api/usc/jeopardy/boards/<id>            one board with its categories and clues
POST   /api/usc/jeopardy/boards                 volunteers: add a board
PUT    /api/usc/jeopardy/boards/<id>            volunteers: change a board
DELETE /api/usc/jeopardy/boards/<id>            volunteers: remove a board (never the last one)
POST   /api/usc/jeopardy/boards/<id>/results    save a finished game, body: {"teams": [{"name", "score"}]}
GET    /api/usc/jeopardy/boards/<id>/results    the 10 most recent games on a board

Playing needs no account, so the board GETs are open. Saving a game needs a
signed-in member (pending accounts too), and only volunteers and staff can
write boards.
"""
from flask import Blueprint, request, g
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.usc_jeopardy import JeopardyBoard, JeopardyResult, check_scores, clean_board

usc_jeopardy_api = Blueprint('usc_jeopardy_api', __name__, url_prefix='/api/usc/jeopardy')
api = Api(usc_jeopardy_api)

EDITOR_ROLES = ['Admin', 'Teacher', 'Volunteer']  # same staff roles as direct messages
RECENT = 10


def _find(board_id):
    return JeopardyBoard.query.get(board_id)


class _Boards(Resource):
    def get(self):
        boards = JeopardyBoard.query.order_by(JeopardyBoard.id).all()
        return [board.read(full=False) for board in boards], 200

    @token_required(EDITOR_ROLES)
    def post(self):
        try:
            board = JeopardyBoard(clean_board(request.get_json(silent=True)), created_by=g.current_user.id)
        except ValueError as e:
            return {'message': str(e)}, 400
        db.session.add(board)
        db.session.commit()
        return board.read(), 201


class _Board(Resource):
    def get(self, board_id):
        board = _find(board_id)
        if board is None:
            return {'message': 'That board is gone. Please pick another one.'}, 404
        return board.read(), 200

    @token_required(EDITOR_ROLES)
    def put(self, board_id):
        board = _find(board_id)
        if board is None:
            return {'message': 'That board is gone. Please pick another one.'}, 404
        try:
            board.update(clean_board(request.get_json(silent=True)))
        except ValueError as e:
            return {'message': str(e)}, 400
        db.session.commit()
        return board.read(), 200

    @token_required(EDITOR_ROLES)
    def delete(self, board_id):
        board = _find(board_id)
        if board is None:
            return {'message': 'That board is gone.'}, 404
        if JeopardyBoard.query.count() <= 1:
            return {'message': 'Keep at least one board so members can always play.'}, 400
        db.session.delete(board)
        db.session.commit()
        return {'message': 'Board removed.'}, 200


class _Results(Resource):
    def get(self, board_id):
        if _find(board_id) is None:
            return {'message': 'That board is gone.'}, 404
        rows = (JeopardyResult.query.filter_by(_board_id=board_id)
                .order_by(JeopardyResult.id.desc()).limit(RECENT).all())
        return [row.read() for row in rows], 200

    @token_required(allow_pending=True)
    def post(self, board_id):
        board = _find(board_id)
        if board is None:
            return {'message': 'That board is gone.'}, 404
        body = request.get_json(silent=True) or {}
        try:
            teams = check_scores(body.get('teams'), board.categories)
        except ValueError as e:
            return {'message': str(e)}, 400
        row = JeopardyResult(board.id, g.current_user.id, teams)
        db.session.add(row)
        db.session.commit()
        return row.read(), 201


api.add_resource(_Boards, '/boards')
api.add_resource(_Board, '/boards/<int:board_id>')
api.add_resource(_Results, '/boards/<int:board_id>/results')
