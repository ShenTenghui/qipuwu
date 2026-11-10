"""Transactional personal recording and immutable user-selected publications."""
from copy import deepcopy
import json
import uuid

from app import repertoire_graph as graph
from xq_notation import FEN0

SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS repertoire_drafts(
       id TEXT PRIMARY KEY,title TEXT NOT NULL,revision INTEGER NOT NULL,
       goal_plies INTEGER NOT NULL,document TEXT NOT NULL,published_version INTEGER NOT NULL DEFAULT 0,
       created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS repertoire_publications(
       line_id TEXT NOT NULL,version INTEGER NOT NULL,draft_id TEXT NOT NULL,
       snapshot TEXT NOT NULL,content_hash TEXT NOT NULL,created_at TEXT NOT NULL,
       PRIMARY KEY(line_id,version))''',
    '''CREATE TABLE IF NOT EXISTS repertoire_manual_runs(
       run_id TEXT PRIMARY KEY,state TEXT NOT NULL)''',
)
GET_OPERATIONS = {'editor_catalog', 'editor'}
POST_FIELDS = {
    'editor_create': {'title', 'goal_plies', 'request_id'},
    'editor_update': {'id', 'revision', 'title', 'goal_plies', 'request_id'},
    'editor_record': {'id', 'revision', 'node_id', 'move', 'enabled', 'request_id'},
    'editor_toggle': {'id', 'revision', 'node_id', 'move', 'enabled', 'request_id'},
    'editor_terminal': {'id', 'revision', 'node_id', 'terminal', 'request_id'},
    'editor_publish': {'id', 'revision', 'request_id'},
}


class Editor:
    def __init__(self, host):
        self.host = host

    @staticmethod
    def _error(code, message, status=400):
        from app.repertoire_training import RepertoireError
        raise RepertoireError(code, message, status)

    @staticmethod
    def _ready(db):
        return db is not None and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='repertoire_drafts'").fetchone() is not None

    def _row(self, db, draft_id):
        from app.repertoire_training import _safe
        _safe(draft_id, '录谱标识')
        if not self._ready(db):
            self._error('draft_not_found', '未找到这份个人录谱。', 404)
        row = db.execute('SELECT * FROM repertoire_drafts WHERE id=?', (draft_id,)).fetchone()
        if row is None:
            self._error('draft_not_found', '未找到这份个人录谱。', 404)
        return dict(row)

    def _node(self, doc, node_id):
        if not isinstance(node_id, str) or node_id not in doc['nodes']:
            self._error('node_not_found', '未找到这个录谱局面，请重新读取。', 404)
        return doc['nodes'][node_id]

    def _goal(self, value):
        if type(value) is not int or not 2 <= value <= graph.MAX_PLIES or value % 2:
            self._error('invalid_goal', '默认目标请填写1至50个完整回合。')
        return value

    def _title(self, value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200 or any(ord(c) < 32 for c in value):
            self._error('invalid_title', '请填写不超过200字的开局名称。')
        return value.strip()

    def view(self, row, node_id=graph.ROOT_ID):
        doc = json.loads(row['document'])
        node = self._node(doc, node_id)
        items = []
        # Serialized node ids are hashes; their lexical order is not a tree.
        # A prefix sorts before its descendants, keeping the visible tree usable.
        for value in sorted(doc['nodes'].values(), key=lambda item: item['history']):
            parent = doc['nodes'].get(value['parent_id'])
            enabled = bool(parent and parent['children'][value['move']]['enabled'])
            items.append(dict(id=value['id'], ply=len(value['history']), parent_id=value['parent_id'],
                move=value['move'], name=value['name'], enabled=enabled, fen=value['fen'], terminal=value['terminal']))
        edges = []
        for move, edge in node['children'].items():
            child = doc['nodes'][edge['child_id']]
            edges.append(dict(move=move, name=child['name'], enabled=bool(edge['enabled']),
                child_id=child['id'], terminal=bool(child['terminal']), ply=len(child['history'])))
        same = [v['id'] for v in doc['nodes'].values()
                if v['id'] != node_id and graph.position(v['fen']) == graph.position(node['fen'])]
        return dict(id=row['id'], line_id='manual-' + row['id'], title=row['title'], revision=row['revision'], goal_plies=row['goal_plies'],
            published_version=row['published_version'], root_id=doc['root_id'],
            current=graph.editor_position(doc, node_id, row['goal_plies']), edges=edges, nodes=items,
            transpositions=same, created_at=row['created_at'], updated_at=row['updated_at'])

    def context(self, draft_id, node_id=graph.ROOT_ID):
        with self.host._database() as db:
            row = self._row(db, draft_id)
            doc = json.loads(row['document'])
            self._node(doc, node_id)
            current = graph.editor_position(doc, node_id, row['goal_plies'])
            return dict(draft_id=draft_id, revision=row['revision'], node_id=node_id,
                start_fen=doc.get('start_fen', FEN0), history=current['history'], fen=current['fen'],
                legal_moves=current['legal_moves'], recorded_moves=list(doc['nodes'][node_id]['children']))

    def get(self, operation, query):
        permitted = set() if operation == 'editor_catalog' else {'id', 'node_id'}
        if set(query) - permitted or any(isinstance(v, list) and len(v) != 1 for v in query.values()):
            self._error('invalid_request', '录谱查询参数缺失、重复或不受支持。')
        with self.host._database() as db:
            if operation == 'editor_catalog':
                if not self._ready(db):
                    return {'drafts': []}
                rows = db.execute('SELECT id,title,revision,goal_plies,published_version,created_at,updated_at '
                                  'FROM repertoire_drafts ORDER BY updated_at DESC,id').fetchall()
                return {'drafts': [dict(row, line_id='manual-' + row['id']) for row in rows]}
            draft_id = self.host._query(query, 'id')
            node_id = self.host._query(query, 'node_id') if 'node_id' in query else graph.ROOT_ID
            return self.view(self._row(db, draft_id), node_id)

    def mutate(self, db, operation, body, now):
        if operation == 'editor_create':
            draft_id = str(uuid.uuid4())
            title, goal = self._title(body.get('title')), self._goal(body.get('goal_plies', 20))
            db.execute('INSERT INTO repertoire_drafts VALUES(?,?,?,?,?,?,?,?)',
                (draft_id, title, 1, goal, graph.canonical(graph.document()), 0, now, now))
            return self.view(self._row(db, draft_id))
        row = self._row(db, body.get('id'))
        if type(body.get('revision')) is not int or body['revision'] != row['revision']:
            self._error('draft_changed', '录谱已在别处修改，请重新读取后再操作。', 409)
        doc = json.loads(row['document'])
        current_id = body.get('node_id', graph.ROOT_ID)
        current = self._node(doc, current_id)
        published = None
        if operation == 'editor_update':
            if 'title' in body:
                row['title'] = self._title(body['title'])
            if 'goal_plies' in body:
                row['goal_plies'] = self._goal(body['goal_plies'])
        elif operation == 'editor_record':
            move = body.get('move')
            if 'enabled' in body and type(body['enabled']) is not bool:
                self._error('invalid_request', '纳入训练标记必须是是或否。')
            try:
                current_id, _ = graph.add_node(doc, current_id, move, body.get('enabled', False))
            except ValueError as exc:
                if str(exc) == 'illegal_move':
                    self._error('illegal_move', '这步不符合走子规则，未记入棋谱。')
                self._error('repertoire_limit', '单份录谱最多2000个局面、每条路线最多100半步。')
            if 'enabled' in body:
                current['children'][move]['enabled'] = body['enabled']
        elif operation == 'editor_toggle':
            if type(body.get('enabled')) is not bool:
                self._error('invalid_request', '纳入训练标记必须是是或否。')
            move = body.get('move')
            if not isinstance(move, str) or move not in current['children']:
                self._error('edge_not_found', '请先在棋盘记录这一步，再选择是否纳入训练。', 404)
            current['children'][move]['enabled'] = body['enabled']
        elif operation == 'editor_terminal':
            if type(body.get('terminal')) is not bool:
                self._error('invalid_request', '终点标记必须是是或否。')
            if body['terminal'] and len(current['history']) < 2:
                self._error('terminal_too_early', '终点至少需要包含双方各一手。')
            current['terminal'] = body['terminal']
        elif operation == 'editor_publish':
            try:
                compiled = graph.compile_document(doc, row['goal_plies'])
            except ValueError as exc:
                code, _, ply = str(exc).partition(':')
                if code == 'terminal_has_moves':
                    self._error(code, f'第{ply}半步已是终点，仍有纳入的后继；请取消终点或取消后继纳入。')
                self._error('incomplete_repertoire', f'第{ply or "当前"}半步尚无完整训练后继；请补录并纳入，或明确设为终点。')
            line_id = 'manual-' + row['id']
            version = row['published_version'] + 1
            total = max(len(compiled['nodes'][n]['history']) for n in compiled['terminal_ids'])
            line = dict(id=line_id, version=version, mode=graph.MODE, title=row['title'], family='本人录谱',
                variation=row['title'], total_plies=total, red_moves=(total + 1) // 2, black_moves=total // 2,
                goal_plies=row['goal_plies'], route_count=compiled['route_count'], start_side='red',
                source=dict(title='本人录制并选择纳入', url='', locator='个人录谱发布版本'))
            saved = dict(schema_version=2, mode=graph.MODE, line=line, start_fen=doc.get('start_fen', FEN0), graph=compiled)
            content_hash = graph.digest(saved)
            saved['line']['content_hash'] = content_hash
            db.execute('INSERT INTO repertoire_publications VALUES(?,?,?,?,?,?)',
                (line_id, version, row['id'], graph.canonical(saved), content_hash, now))
            row['published_version'] = version
            published = dict(line_id=line_id, version=version, content_hash=content_hash)
        else:
            self._error('not_found', '未找到这个录谱操作。', 404)
        row['revision'] += 1
        db.execute('UPDATE repertoire_drafts SET title=?,revision=?,goal_plies=?,document=?,published_version=?,updated_at=? WHERE id=?',
            (row['title'], row['revision'], row['goal_plies'], graph.canonical(doc), row['published_version'], now, row['id']))
        result = self.view(self._row(db, row['id']), current_id)
        if published is not None:
            result['published'] = published
        return result

    @staticmethod
    def publications(db):
        if db is None or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='repertoire_publications'").fetchone() is None:
            return []
        return [json.loads(row['snapshot']) for row in db.execute(
            'SELECT p.snapshot FROM repertoire_publications p JOIN (SELECT line_id,MAX(version) version '
            'FROM repertoire_publications GROUP BY line_id) current USING(line_id,version) ORDER BY p.created_at DESC,p.line_id')]

    @staticmethod
    def publication(db, line_id, version=None):
        if db is None or db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='repertoire_publications'").fetchone() is None:
            return None
        if version is None:
            row = db.execute('SELECT snapshot FROM repertoire_publications WHERE line_id=? ORDER BY version DESC LIMIT 1', (line_id,)).fetchone()
        else:
            row = db.execute('SELECT snapshot FROM repertoire_publications WHERE line_id=? AND version=?', (line_id, str(version))).fetchone()
        return json.loads(row['snapshot']) if row else None

    @staticmethod
    def preview(saved, state=None, side='red'):
        compiled = saved['graph']
        current = state['node_id'] if state else compiled['root_id']
        endpoint = graph.continuation(compiled, current, state['opponent_choices'] if state else None, side)
        result = dict(line=deepcopy(saved['line']), start_fen=saved['start_fen'], mode=graph.MODE,
            moves=graph.path(compiled, endpoint),
            routes=[dict(id=node_id, title='路线 ' + str(i + 1), moves=graph.path(compiled, node_id))
                    for i, node_id in enumerate(compiled['terminal_ids'])])
        if state:
            result['played_plies'] = len(compiled['nodes'][current]['history'])
        return result
