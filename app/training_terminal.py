"""Pure consistency checks for a saved engine mate and its board continuation.

Pikafish also uses the UCI mate range for repetition/check/chase rule results.
This module never searches or replaces an engine evaluation: it only checks
whether that *saved PV* legally reaches a board with no legal reply at the
claimed distance. A valid PV is not a proof of all branches or fastest mate.
No I/O, engine, storage, experiment access or background work is performed.
"""
import re
import json
from functools import lru_cache

from opening_classifier import _geometry, _in_check, _PIECE
from xq_notation import apply_move, parse_fen

VERSION = 'training-board-terminal-v1'
_MOVE = re.compile(r'^[a-i][0-9][a-i][0-9]$')
_MAX_PLIES = 512


def scoped(certificate):
    return isinstance(certificate, dict) and any(name in certificate for name in
        ('training_full_history', 'training_reference_repair', 'precision'))


@lru_cache(maxsize=512)
def _assess_saved(raw_text, ply, value_text):
    return assess(json.loads(raw_text), ply, json.loads(value_text))


def first_issue(raw, ply, values):
    """Check mate PVs only; exact immutable inputs make memoization safe."""
    for value in values:
        if isinstance(value, dict) and value.get('type') == 'mate':
            finding = _assess_saved(json.dumps(raw, sort_keys=True), ply, json.dumps(value, sort_keys=True))
            if finding['status'] != 'valid':
                return dict(finding)
    return None


def require(raw, ply, values):
    issue = first_issue(raw, ply, values)
    if issue:
        raise ValueError('保存的杀棋变化未通过棋盘终局核对，不能用规则胜负代替绝杀；本题暂停出题。')


def legal_moves(board, color):
    """Piece geometry plus king safety; no repetition/outcome adjudication."""
    if color not in ('R', 'B'):
        raise ValueError('Invalid moving side.')
    out = []
    for fr in range(10):
        for fc in range(9):
            piece = board[fr][fc]
            if not piece or piece[0] != color:
                continue
            for tr in range(10):
                for tc in range(9):
                    target = board[tr][tc]
                    if target and (target[0] == color or _PIECE[target[1]] == 'K'):
                        continue
                    if not _geometry(board, fr, fc, tr, tc):
                        continue
                    after = [row[:] for row in board]
                    after[tr][tc], after[fr][fc] = piece, None
                    if not _in_check(after, color):
                        out.append(f'{chr(fc + 97)}{9-fr}{chr(tc + 97)}{9-tr}')
    return out


def _play(board, move, side):
    if not isinstance(move, str) or not _MOVE.fullmatch(move):
        raise ValueError('Invalid move syntax.')
    fc, fr = ord(move[0])-97, 9-int(move[1])
    tc, tr = ord(move[2])-97, 9-int(move[3])
    piece, target = board[fr][fc], board[tr][tc]
    if (not piece or piece[0] != side
            or target and (target[0] == side or _PIECE[target[1]] == 'K')
            or not _geometry(board, fr, fc, tr, tc)):
        raise ValueError('Illegal saved move geometry.')
    after = [row[:] for row in board]
    apply_move(after, move)
    if _in_check(after, side):
        raise ValueError('Saved move leaves its king attacked.')
    return after


def _key(board, side):
    return tuple(tuple(row) for row in board), side


def _starting_board(fen):
    if not isinstance(fen, str):
        raise ValueError('Missing starting FEN.')
    fields = fen.split()
    if len(fields) < 2 or fields[1] not in ('w','b'):
        raise ValueError('Invalid starting turn.')
    ranks = fields[0].split('/')
    if len(ranks) != 10:
        raise ValueError('Invalid board height.')
    for rank in ranks:
        width = 0
        for char in rank:
            if char in '123456789':
                width += int(char)
            elif char in 'rnbakcpRNBAKCP':
                width += 1
            else:
                raise ValueError('Invalid FEN piece.')
        if width != 9:
            raise ValueError('Invalid board width.')
    if fields[0].count('k') != 1 or fields[0].count('K') != 1:
        raise ValueError('Missing or duplicated king.')
    return parse_fen(fen), 'R' if fields[1] == 'w' else 'B'


def assess(raw, ply, evaluation, root_move=None):
    """Return typed ``valid | unconfirmed | not_board_mate`` consistency.

    ``ply`` is the zero-based original game index; PV starts with the searched
    root move. UCI +N means 2*N-1 halfmoves to the other side's terminal board;
    -N means 2*abs(N) halfmoves to our own terminal board. Mate 0 is the already
    terminal root. These are root-mover values, never post-move/Red-POV values.
    Repeated boards are reported as a boundary, not automatically rejected when
    the full legal PV still reaches a terminal board at the expected distance.
    """
    result = dict(version=VERSION, status='unconfirmed', reason='invalid_evaluation',
        applies=True, proof_scope='saved_principal_variation_geometry_only',
        proves_forced_mate=False)

    def done(status, reason, **fields):
        return dict(result, status=status, reason=reason, **fields)

    if not isinstance(evaluation, dict):
        return result
    if evaluation.get('type') == 'cp':
        if type(evaluation.get('cp')) is int and evaluation.get('mate_distance') is None:
            return done('valid', 'not_mate_evaluation', applies=False)
        return result
    distance = evaluation.get('mate_distance')
    if (evaluation.get('type') != 'mate' or type(distance) is not int
            or evaluation.get('cp') is not None):
        return result
    expected = 2*distance-1 if distance > 0 else -2*distance
    if not 0 <= expected <= _MAX_PLIES:
        return done('unconfirmed', 'unsupported_distance')
    result['expected_plies'] = expected
    pv = evaluation.get('pv')
    if not isinstance(pv, list) or len(pv) > _MAX_PLIES:
        return done('unconfirmed', 'missing_or_oversized_pv')
    if root_move is not None and (not isinstance(root_move,str) or not _MOVE.fullmatch(root_move)):
        return done('unconfirmed', 'invalid_root_move')
    if expected and (not pv or not isinstance(evaluation.get('move'),str)
            or evaluation['move'] != pv[0] or root_move is not None and root_move != pv[0]):
        return done('unconfirmed', 'root_move_mismatch_or_missing_pv')
    try:
        if (not isinstance(raw,dict) or type(ply) is not int or ply < 0 or ply > _MAX_PLIES
                or not isinstance(raw.get('moves'),list) or ply > len(raw['moves'])):
            return done('unconfirmed', 'invalid_source_history')
        board, side = _starting_board(raw.get('fen'))
        history = {_key(board,side): [0]}
        for index, move in enumerate(raw['moves'][:ply]):
            board = _play(board,move,side)
            side = 'B' if side == 'R' else 'R'
            history.setdefault(_key(board,side),[]).append(index+1)
        repeated = []
        if expected == 0:
            replies = legal_moves(board,side)
            count = len(replies)
            return done('valid' if count == 0 and not pv else 'not_board_mate',
                'already_terminal_root' if count == 0 and not pv else 'mate_zero_not_terminal',
                played_plies=0,terminal_legal_count=count,terminal_in_check=_in_check(board,side),
                terminal_reply=replies[0] if replies else None)
        for index, move in enumerate(pv):
            # A PV extending beyond its claimed terminal cannot justify that distance.
            if index >= expected:
                return done('unconfirmed','pv_exceeds_claimed_distance',played_plies=index)
            board = _play(board,move,side)
            side = 'B' if side == 'R' else 'R'
            previous = list(history.get(_key(board,side),[]))
            if previous:
                repeated.append(dict(pv_ply=index+1,previous_plies=previous))
            history.setdefault(_key(board,side),[]).append(ply+index+1)
            replies = legal_moves(board,side)
            count = len(replies)
            if count == 0:
                if index+1 != expected or len(pv) != expected:
                    return done('unconfirmed','terminal_distance_mismatch',played_plies=index+1,
                        terminal_legal_count=0,terminal_in_check=_in_check(board,side),
                        repeated_positions=repeated)
                return done('valid','pv_reaches_board_terminal',played_plies=index+1,
                    terminal_legal_count=0,terminal_in_check=_in_check(board,side),
                    repeated_positions=repeated)
        details = dict(played_plies=len(pv),terminal_legal_count=count,
            terminal_in_check=_in_check(board,side),repeated_positions=repeated,
            terminal_reply=replies[0] if replies else None)
        if len(pv) < expected:
            return done('unconfirmed','truncated_pv_before_claimed_distance',**details)
        return done('not_board_mate',
            'repetition_endpoint_has_legal_replies' if repeated and repeated[-1]['pv_ply']==expected
            else 'distance_endpoint_has_legal_replies',**details)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError):
        return done('unconfirmed','invalid_source_or_pv_geometry')
