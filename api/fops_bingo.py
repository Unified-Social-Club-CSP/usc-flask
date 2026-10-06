""" Multiplayer Bingo API for the Friends of Poway Seniors website.

POST /api/fops/bingo/rooms               create a room, body: {"interval_seconds": 8}
POST /api/fops/bingo/rooms/<code>/join   join a room with its 4-digit code
GET  /api/fops/bingo/rooms/<code>        room state (players, start time, winner)
POST /api/fops/bingo/rooms/<code>/start  host starts the caller
POST /api/fops/bingo/rooms/<code>/claim  claim BINGO; the server checks it

The server never sends a list of called balls. Browsers compute the calls from
the room seed and start time, and the server uses the same math to check claims.
"""
import random

from flask import Blueprint, request, g
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.fops_bingo import (
    BingoRoom, BingoPlayer, START_DELAY_MS,
    balls_called_at, call_order, card_seed_for, make_card, now_ms, winning_lines,
)

fops_bingo_api = Blueprint('fops_bingo_api', __name__, url_prefix='/api/fops/bingo')
api = Api(fops_bingo_api)

INTERVALS = {6, 8, 10, 12}  # seconds between calls the host can choose


def _join(room, user):
    player = room.player_for(user.id)
    if player is None:
        player = BingoPlayer(
            room_id=room.id,
            user_id=user.id,
            name=user.name,
            card_seed=card_seed_for(room.seed, user.id),
        )
        db.session.add(player)
        db.session.commit()
    return player


def _find(code):
    return BingoRoom.query.filter_by(code=str(code)).first()


class _Rooms(Resource):
    @token_required()
    def post(self):
        body = request.get_json(silent=True) or {}
        interval = body.get('interval_seconds', 8)
        if interval not in INTERVALS:
            return {'message': f'interval_seconds must be one of {sorted(INTERVALS)}'}, 400
        BingoRoom.remove_expired()
        room = BingoRoom(
            code=BingoRoom.new_code(),
            seed=random.getrandbits(32),
            interval_ms=interval * 1000,
            host_user_id=g.current_user.id,
        )
        db.session.add(room)
        db.session.commit()
        _join(room, g.current_user)
        return room.read(g.current_user.id), 201


class _Room(Resource):
    @token_required()
    def get(self, code):
        room = _find(code)
        if room is None:
            return {'message': 'No game with that code. Please check the number.'}, 404
        return room.read(g.current_user.id), 200


class _Join(Resource):
    @token_required()
    def post(self, code):
        room = _find(code)
        if room is None:
            return {'message': 'No game with that code. Please check the number.'}, 404
        _join(room, g.current_user)
        return room.read(g.current_user.id), 200


class _Start(Resource):
    @token_required()
    def post(self, code):
        room = _find(code)
        if room is None:
            return {'message': 'No game with that code.'}, 404
        if room.host_user_id != g.current_user.id:
            return {'message': 'Only the person who made the game can start it.'}, 403
        if room.started_at_ms is None:
            room.started_at_ms = now_ms() + START_DELAY_MS
            db.session.commit()
        return room.read(g.current_user.id), 200


class _Claim(Resource):
    @token_required()
    def post(self, code):
        room = _find(code)
        if room is None:
            return {'message': 'No game with that code.'}, 404
        player = room.player_for(g.current_user.id)
        if player is None:
            return {'message': 'You are not in this game.'}, 403
        if room.winner_name:
            return {'valid': False, 'message': f'{room.winner_name} already won this game.', 'room': room.read(g.current_user.id)}, 200

        count = balls_called_at(room.started_at_ms, now_ms(), room.interval_ms)
        called = set(call_order(room.seed)[:count])
        lines = winning_lines(make_card(player.card_seed), called)
        if not lines:
            return {'valid': False, 'message': 'Not a Bingo yet. Keep playing!', 'room': room.read(g.current_user.id)}, 200

        room.winner_user_id = g.current_user.id
        room.winner_name = player.name
        room.winner_ball = count
        db.session.commit()
        return {'valid': True, 'message': 'BINGO!', 'room': room.read(g.current_user.id)}, 200


api.add_resource(_Rooms, '/rooms')
api.add_resource(_Room, '/rooms/<string:code>')
api.add_resource(_Join, '/rooms/<string:code>/join')
api.add_resource(_Start, '/rooms/<string:code>/start')
api.add_resource(_Claim, '/rooms/<string:code>/claim')
