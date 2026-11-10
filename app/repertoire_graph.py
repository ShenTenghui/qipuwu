"""Pure personal repertoire tree: full histories stay distinct after transposition.

Only explicitly enabled edges enter a publication. There is no engine or
move-quality decision here; a wrong training answer means outside that selection.
"""
from copy import deepcopy
import hashlib
import json

from app.training_terminal import _starting_board, legal_moves
from opening_classifier import _in_check
from xq_notation import FEN0, apply_move, notation_one

MODE = 'manual-repertoire-v2'
MAX_NODES = 2000
MAX_PLIES = 100
ROOT_ID = 'root'
LETTERS = {'车':'R','马':'N','相':'B','仕':'A','帅':'K','炮':'C','兵':'P',
           '車':'r','馬':'n','象':'b','士':'a','將':'k','卒':'p'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def position(fen):
    return ' '.join(fen.split()[:2])


def board_fen(board, ply):
    ranks = []
    for row in board:
        rank, count = '', 0
        for piece in row:
            if piece is None:
                count += 1
            else:
                if count:
                    rank += str(count)
                    count = 0
                letter = LETTERS[piece[1]]
                rank += letter.upper() if piece[0] == 'R' else letter.lower()
        ranks.append(rank + (str(count) if count else ''))
    return '/'.join(ranks) + (' w' if ply % 2 == 0 else ' b') + f' - - 0 {ply // 2 + 1}'


def document():
    # New recordings choose the same exact standard-root input as the normal
    # captured games. Missing metadata in an older draft must keep its old FEN0.
    return {'start_fen': position(FEN0), 'root_id': ROOT_ID, 'nodes': {ROOT_ID: dict(id=ROOT_ID, parent_id=None,
        move=None, name='', fen=FEN0, history=[], terminal=False, children={})}}


def add_node(doc, parent_id, move, enabled=False):
    parent = doc['nodes'][parent_id]
    board, color = _starting_board(parent['fen'])
    if move not in legal_moves(board, color):
        raise ValueError('illegal_move')
    if move in parent['children']:
        edge = parent['children'][move]
        # Recording an existing move never silently removes its selection.
        return edge['child_id'], False
    if len(doc['nodes']) >= MAX_NODES or len(parent['history']) >= MAX_PLIES:
        raise ValueError('repertoire_limit')
    history = parent['history'] + [move]
    node_id = 'n-' + digest(history)[:24]
    name = notation_one([row[:] for row in board], move, black_arabic=True)
    captured = apply_move(board, move)[5]
    node = dict(id=node_id, parent_id=parent_id, move=move, name=name,
        fen=board_fen(board, len(history)), history=history, terminal=False,
        captured=captured[1] if captured else None, children={})
    parent['children'][move] = dict(child_id=node_id, enabled=enabled)
    doc['nodes'][node_id] = node
    return node_id, True


def path(doc, node_id):
    result = []
    node = doc['nodes'][node_id]
    while node['parent_id'] is not None:
        result.append(dict(ply=len(node['history']), move=node['move'], name=node['name'], fen_after=node['fen']))
        node = doc['nodes'][node['parent_id']]
    return list(reversed(result))


def compile_document(doc, goal_plies):
    """Prune draft edges, rejecting every enabled branch without an endpoint."""
    nodes, terminals = {}, []

    def visit(node_id):
        node = doc['nodes'][node_id]
        ply = len(node['history'])
        selected = {move: deepcopy(edge) for move, edge in node['children'].items() if edge['enabled']}
        terminal = bool(node['terminal']) or ply == goal_plies
        if terminal and ply < 2:
            raise ValueError('terminal_too_early')
        if terminal and selected:
            raise ValueError('terminal_has_moves:' + str(ply))
        if not terminal and not selected:
            raise ValueError('incomplete_repertoire:' + str(ply))
        if ply > goal_plies:
            raise ValueError('beyond_goal')
        saved = deepcopy(node)
        saved['children'], saved['terminal'] = selected, terminal
        nodes[node_id] = saved
        if terminal:
            terminals.append(node_id)
        else:
            for edge in selected.values():
                visit(edge['child_id'])

    visit(doc['root_id'])
    return dict(root_id=doc['root_id'], nodes=nodes, terminal_ids=terminals,
                goal_plies=goal_plies, route_count=len(terminals))


def choices(graph, run_id):
    # Persist this plan in each run, so later policy changes do not change it.
    result = {}
    for node_id, node in graph['nodes'].items():
        moves = list(node['children'])
        if moves:
            at = int(hashlib.sha256((run_id + ':' + node_id).encode()).hexdigest()[:8], 16) % len(moves)
            result[node_id] = moves[at]
    return result


def advance(graph, state, side):
    node = graph['nodes'][state['node_id']]
    own_turn = (len(node['history']) % 2 == 0) == (side == 'red')
    if not node['terminal'] and not own_turn:
        move = state['opponent_choices'][node['id']]
        state['node_id'] = node['children'][move]['child_id']
    return state


def continuation(graph, node_id, opponent_choices=None, side='red'):
    node = graph['nodes'][node_id]
    while not node['terminal']:
        own_turn = (len(node['history']) % 2 == 0) == (side == 'red')
        move = (opponent_choices or {}).get(node['id']) if not own_turn else None
        move = move if move in node['children'] else next(iter(node['children']))
        node = graph['nodes'][node['children'][move]['child_id']]
    return node['id']


def editor_position(doc, node_id, goal_plies):
    node = doc['nodes'][node_id]
    board, color = _starting_board(node['fen'])
    return dict(id=node_id, ply=len(node['history']), fen=node['fen'], history=list(node['history']),
        parent_id=node['parent_id'],
        moves=path(doc, node_id), legal_moves=legal_moves(board, color), in_check=_in_check(board, color),
        terminal=bool(node['terminal']), terminal_effective=bool(node['terminal']) or len(node['history']) == goal_plies)


def run_view(row, saved, state):
    graph = saved['graph']
    node = graph['nodes'][state['node_id']]
    history = node['history']
    ply = len(history)
    endpoint = continuation(graph, node['id'], state['opponent_choices'], row['side'])
    total = len(graph['nodes'][endpoint]['history'])
    own_completed = (ply + (1 if row['side'] == 'red' else 0)) // 2
    own_total = (total + (1 if row['side'] == 'red' else 0)) // 2
    previous = None if not history else dict(move=node['move'], name=node['name'], captured=node.get('captured'))
    board, color = _starting_board(node['fen'])
    line = saved['line']
    return dict(id=row['id'], mode=MODE, line_id=row['line_id'], line_version=line['version'],
        content_hash=line['content_hash'], title=line['title'], family=line['family'], variation=line['variation'],
        side=row['side'], status=row['status'], revision=state['revision'], ply=ply, total_plies=total,
        target_plies=graph['goal_plies'], own_completed=own_completed, own_total=own_total, fen=node['fen'],
        legal_moves=legal_moves(board, color) if row['status'] == 'active' else [],
        last_move=history[-1] if history else None, previous_move=previous, in_check=_in_check(board, color),
        feedback=json.loads(row['feedback']) if row['feedback'] else None,
        board_state='before_error' if row['status'] == 'failed' else 'line_position',
        source=line['source'], cross_sources=[], quality_review=None,
        created_at=row['created_at'], updated_at=row['updated_at'], completed_at=row['completed_at'])
