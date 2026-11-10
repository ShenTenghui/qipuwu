"""Fixed-line repertoire rehearsal, with no engine or import-time storage work.

The source file is the rehearsal answer, not a move-quality certificate. Runs
keep an immutable, rule-checked source snapshot and never alter other training
tables. Reading this service does not create a database or initialize schema.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlsplit
import uuid

from app.training_terminal import _starting_board, legal_moves
from opening_classifier import _in_check
from xq_notation import apply_move, notation_one
from app import repertoire_graph as graph
from app.repertoire_editor import Editor, SCHEMA as EDITOR_SCHEMA, GET_OPERATIONS as EDITOR_GET, POST_FIELDS as EDITOR_POST

VERSION = 'fixed-line-repertoire-v1'
_SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_MOVE = re.compile(r'[a-i][0-9][a-i][0-9]\Z')
_PIECES = dict(zip('车马相仕帅炮兵車馬象士將卒', 'RNBAKCPrnbakp'))
_SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS repertoire_runs (
       id TEXT PRIMARY KEY, line_id TEXT NOT NULL, line_version TEXT NOT NULL,
       snapshot TEXT NOT NULL, side TEXT NOT NULL, status TEXT NOT NULL,
       ply INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
       completed_at TEXT, feedback TEXT)''',
    '''CREATE TABLE IF NOT EXISTS repertoire_requests (
       request_id TEXT PRIMARY KEY, operation TEXT NOT NULL, payload_hash TEXT NOT NULL,
       response TEXT NOT NULL, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS repertoire_events (
       id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
       kind TEXT NOT NULL, ply INTEGER NOT NULL, move TEXT,
       request_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS repertoire_run_status ON repertoire_runs(status, updated_at)',
)


class RepertoireError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _text(value, name, maximum=300):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum or any(ord(c) < 32 for c in value)):
        raise ValueError(f'{name}缺失或格式不正确。')
    return value


def _safe(value, name):
    if not isinstance(value, str) or not _SAFE.fullmatch(value):
        raise RepertoireError('invalid_request', f'{name}格式不正确。')
    return value


def _source(value):
    if not isinstance(value, dict):
        raise ValueError('棋谱缺少可核对来源。')
    source = {name: _text(value.get(name), f'来源{name}', 2000)
              for name in ('title', 'url', 'locator')}
    url = urlsplit(source['url'])
    if url.scheme not in ('https', 'http') or not url.netloc or url.username or url.password:
        raise ValueError('棋谱来源链接格式不正确。')
    return source


def line_identity(start_fen, moves):
    """Bind a curated review to the exact starting position and whole line."""
    return hashlib.sha256(_json(dict(start_fen=start_fen, moves=moves)).encode('utf-8')).hexdigest()


def _fen(board, color, ply=0, start_color='R'):
    ranks = []
    for row in board:
        rank, empty = '', 0
        for piece in row:
            if piece is None:
                empty += 1
            else:
                if empty:
                    rank += str(empty)
                    empty = 0
                letter = _PIECES[piece[1]]
                rank += letter.upper() if piece[0] == 'R' else letter.lower()
        ranks.append(rank + (str(empty) if empty else ''))
    fullmove = (ply + (1 if start_color == 'B' else 0)) // 2 + 1
    return '/'.join(ranks) + (' w' if color == 'R' else ' b') + f' - - 0 {fullmove}'


def _validate(raw, digest):
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1:
        raise ValueError('棋谱文件版本不受支持。')
    line_id = raw.get('id')
    if not isinstance(line_id, str) or not _SAFE.fullmatch(line_id):
        raise ValueError('棋谱标识格式不正确。')
    metadata = {'id': line_id}
    version = raw.get('version')
    if type(version) is int and version > 0:
        metadata['version'] = version
    else:
        metadata['version'] = _text(version, 'version', 128)
    for name in ('title', 'family', 'variation'):
        metadata[name] = _text(raw.get(name), name, 500 if name == 'title' else 300)
    metadata['source'] = _source(raw.get('source'))
    if 'cross_sources' in raw:
        if not isinstance(raw['cross_sources'], list) or not 1 <= len(raw['cross_sources']) <= 12:
            raise ValueError('交叉来源格式不正确。')
        metadata['cross_sources'] = []
        for item in raw['cross_sources']:
            source = _source(item)
            source.update({name: _text(item.get(name), name, 2000)
                           for name in ('independence', 'coverage')})
            metadata['cross_sources'].append(source)
    for name in ('ecco', 'end_note'):
        if name in raw:
            metadata[name] = _text(raw[name], name, 2000)
    board, color = _starting_board(raw.get('start_fen'))
    start_color = color
    moves = raw.get('moves')
    if not isinstance(moves, list) or not 2 <= len(moves) <= 512:
        raise ValueError('棋谱必须含2至512个半回合。')
    if 'quality_review' in raw:
        review = raw['quality_review']
        if not isinstance(review, dict) or review.get('status') != 'reviewed':
            raise ValueError('选材核验记录格式不正确。')
        checked_at = review.get('checked_at')
        if not isinstance(checked_at, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', checked_at):
            raise ValueError('选材核验日期格式不正确。')
        if review.get('line_sha256') != line_identity(raw['start_fen'], moves):
            raise ValueError('选材核验与当前棋谱着法不匹配，请重新核验。')
        evidence = _text(review.get('evidence'), '选材核验证据', 300)
        if not re.fullmatch(r'reviews/[A-Za-z0-9][A-Za-z0-9_.-]*\.json', evidence):
            raise ValueError('选材核验证据位置格式不正确。')
        metadata['quality_review'] = dict(status='reviewed', checked_at=checked_at,
            summary=_text(review.get('summary'), '选材核验摘要', 2000),
            scope=_text(review.get('scope'), '选材核验范围', 2000),
            line_sha256=review['line_sha256'], evidence=evidence)
        evidence_hash = review.get('evidence_sha256')
        if not isinstance(evidence_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', evidence_hash):
            raise ValueError('选材核验证据缺少内容校验。')
        metadata['quality_review']['evidence_sha256'] = evidence_hash
    names, states, captures = [], [_fen(board, color)], []
    for index, move in enumerate(moves):
        if not isinstance(move, str) or not _MOVE.fullmatch(move) or move not in legal_moves(board, color):
            raise ValueError(f'第{index + 1}着未通过合法走子核验。')
        # notation_one mutates its board, so preserve the validated board here.
        names.append(notation_one([row[:] for row in board], move, black_arabic=True))
        captured = apply_move(board, move)[5]
        captures.append(captured[1] if captured else None)
        color = 'B' if color == 'R' else 'R'
        states.append(_fen(board, color, index + 1, start_color))
    red = sum((start_color == 'R') == (index % 2 == 0) for index in range(len(moves)))
    metadata.update(total_plies=len(moves), red_moves=red, black_moves=len(moves) - red,
                    content_hash=digest, start_side='red' if start_color == 'R' else 'black')
    return dict(line=metadata, start_fen=states[0], moves=list(moves), names=names,
                states=states, captures=captures, start_color=start_color)


class Service:
    def __init__(self, root, db_path=None):
        self.root = Path(root).resolve()
        self.db_path = Path(db_path) if db_path is not None else self.root / 'training.db'
        self.directory = self.root / 'data' / 'repertoire'
        self._cache = {}
        self._cache_lock = threading.Lock()

    def _check_review(self, saved):
        """A display claim must have the matching completed selection record.

        This verifies the published review envelope. Raw engine transcripts are
        verified by the offline audit publisher, not re-searched by this service.
        The file is checked even when the line itself has a warm cache.
        """
        metadata = saved['line']
        review = metadata.get('quality_review')
        if review is None:
            return
        path = (self.directory / review['evidence']).resolve()
        if not path.is_relative_to((self.directory / 'reviews').resolve()):
            raise ValueError('选材核验证据越出目录。')
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('选材核验证据过大。')
        data = path.read_bytes()
        if len(data) > 4 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != review['evidence_sha256']:
            raise ValueError('选材核验证据内容已变化。')
        audit = json.loads(data.decode('utf-8'))
        expected = dict(schema_version=1,scope='repertoire-selection-cold-root-v1',status='passed',
                        line_id=metadata['id'],line_sha256=review['line_sha256'],
                        total_plies=len(saved['moves']),checked_at=review['checked_at'])
        if not isinstance(audit,dict) or any(audit.get(key) != value for key,value in expected.items()):
            raise ValueError('选材核验证据与本谱不匹配或尚未通过。')
        policy = dict(screen_nodes=1_000_000,screen_repeats=1,screen_review_at_cp=35,
                      review_nodes=3_000_000,review_repeats=2,maximum_exclusive_cp=50,score_pov='root_mover')
        if audit.get('selection_policy') != policy:
            raise ValueError('选材核验策略版本不受支持。')
        nodes = audit.get('nodes')
        if not isinstance(nodes,list) or len(nodes) != len(saved['moves']):
            raise ValueError('选材核验节点不完整。')
        for index,(move,node) in enumerate(zip(saved['moves'],nodes)):
            if (not isinstance(node,dict) or node.get('ply') != index + 1
                    or node.get('chosen_move') != move or node.get('status') != 'passed'
                    or type(node.get('deeper_review')) is not bool
                    or type(node.get('screening_flag')) is not bool
                    or node.get('screening_candidates_retained') is not True):
                raise ValueError('选材核验逐着身份不完整。')
            deep = node['deeper_review']
            budget,repeats = (3_000_000,2) if deep else (1_000_000,1)
            if (type(node.get('nodes')) is not int or node['nodes'] != budget
                    or type(node.get('repeats')) is not int or node['repeats'] != repeats
                    or node['screening_flag'] and not deep):
                raise ValueError('选材疑点缺少独立加深复核。')
            comparisons = node.get('comparisons')
            if not isinstance(comparisons,list) or len(comparisons) != repeats:
                raise ValueError('选材核验缺少对称比较。')
            losses = []
            for repeat,comparison in enumerate(comparisons,1):
                if (not isinstance(comparison,dict) or comparison.get('repeat') != repeat
                        or comparison.get('typed_review_required') is not False):
                    raise ValueError('选材核验仍有待确认的评价类型。')
                actual,reference = comparison.get('chosen'),comparison.get('reference')
                for value in (actual,reference):
                    if (not isinstance(value,dict) or value.get('type') != 'cp'
                            or type(value.get('cp')) is not int or value.get('mate_distance') is not None):
                        raise ValueError('选材核验不能将杀棋与CP混算。')
                loss_fields = comparison.get('loss')
                if not isinstance(loss_fields,dict):
                    raise ValueError('选材核验缺少同组比较。')
                loss = loss_fields.get('cp_regret')
                if (actual.get('move') != move or type(loss) is not int or not 0 <= loss < 50
                        or loss != max(0,reference['cp']-actual['cp'])):
                    raise ValueError('选材核验未通过保存的同组门槛。')
                losses.append(loss)
            if node.get('max_cp_loss') != max(losses):
                raise ValueError('选材核验汇总与逐次比较不一致。')
            if not deep and max(losses) >= policy['screen_review_at_cp']:
                raise ValueError('选材疑点缺少独立加深复核。')

    def _sources(self):
        lines, unavailable, identities = {}, [], {}
        try:
            paths = sorted(self.directory.glob('*.json'))
        except OSError:
            return {}, [dict(file='data/repertoire', message='棋谱目录暂时不可读取。')]
        for path in paths:
            line_id = None
            try:
                # Hash exact bytes so same-size/replaced files cannot retain an old answer.
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError('棋谱文件过大。')
                data = path.read_bytes()
                if len(data) > 1024 * 1024:
                    raise ValueError('棋谱文件过大。')
                digest = hashlib.sha256(data).hexdigest()
                with self._cache_lock:
                    cached = self._cache.get(str(path))
                if cached and cached[0] == digest:
                    line = cached[1]
                else:
                    raw = json.loads(data.decode('utf-8-sig'))
                    line_id = raw.get('id') if isinstance(raw, dict) else None
                    line = _validate(raw, digest)
                    with self._cache_lock:
                        self._cache[str(path)] = (digest, line)
                self._check_review(line)
                line_id = line['line']['id']
                if line_id in identities:
                    lines.pop(line_id, None)
                    raise ValueError('棋谱标识重复，相关线路均暂停使用。')
                identities[line_id] = path.name
                lines[line_id] = line
            except (OSError, ValueError, TypeError, KeyError, IndexError, UnicodeError, OverflowError):
                message = '棋谱元信息或完整着法未通过核验，暂不可用。'
                if line_id in identities:
                    message = '棋谱标识重复，相关线路均暂停使用。'
                item = dict(file=path.name, message=message)
                if isinstance(line_id, str) and _SAFE.fullmatch(line_id):
                    item['id'] = line_id
                unavailable.append(item)
        return lines, unavailable

    @contextmanager
    def _database(self, write=False):
        db = None
        try:
            if not write and not self.db_path.is_file():
                yield None
                return
            if write:
                # Directory creation is intentionally limited to the first POST.
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                db = sqlite3.connect(str(self.db_path), timeout=10, isolation_level=None)
            else:
                db = sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro',
                                     uri=True, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
            if write:
                db.execute('BEGIN IMMEDIATE')
                for statement in (*_SCHEMA, *EDITOR_SCHEMA):
                    db.execute(statement)
            yield db
            if write:
                db.commit()
        except sqlite3.Error as exc:
            if db is not None and write:
                db.rollback()
            raise RepertoireError('storage_unavailable', '训练记录暂时不可读写，请稍后重试。', 503) from exc
        except Exception:
            if db is not None and write:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _has_tables(db):
        return db is not None and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='repertoire_runs'").fetchone() is not None

    @staticmethod
    def _row(db, run_id):
        row = db.execute('SELECT * FROM repertoire_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise RepertoireError('run_not_found', '未找到这次棋谱训练。', 404)
        result = dict(row)
        if json.loads(result['snapshot']).get('mode') == graph.MODE:
            state = db.execute('SELECT state FROM repertoire_manual_runs WHERE run_id=?', (run_id,)).fetchone()
            if state is None:
                raise RepertoireError('state_unavailable', '训练进度暂不可读取，个人记录保留。', 503)
            result['_manual_state'] = state['state']
        return result

    @staticmethod
    def _view(row):
        saved = json.loads(row['snapshot'])
        if saved.get('mode') == graph.MODE:
            return graph.run_view(row, saved, json.loads(row['_manual_state']))
        line, ply = saved['line'], row['ply']
        own_color = 'R' if row['side'] == 'red' else 'B'
        own_completed = sum((saved['start_color'] == own_color) == (i % 2 == 0) for i in range(ply))
        fen = saved['states'][ply]
        board, color = _starting_board(fen)
        previous = None if ply == 0 else dict(move=saved['moves'][ply - 1],
            name=saved['names'][ply - 1], captured=saved['captures'][ply - 1])
        return dict(id=row['id'], line_id=row['line_id'], line_version=line['version'],
                    content_hash=line['content_hash'],
                    title=line['title'], family=line['family'], variation=line['variation'],
                    side=row['side'], status=row['status'], ply=ply, total_plies=line['total_plies'],
                    own_completed=own_completed, own_total=line[row['side'] + '_moves'], fen=fen,
                    legal_moves=legal_moves(board, color) if row['status'] == 'active' else [],
                    last_move=None if previous is None else previous['move'], previous_move=previous,
                    in_check=_in_check(board, color), feedback=json.loads(row['feedback']) if row['feedback'] else None,
                    board_state='before_error' if row['status'] == 'failed' else 'line_position',
                    source=deepcopy(line['source']), created_at=row['created_at'], updated_at=row['updated_at'],
                    completed_at=row['completed_at'], cross_sources=deepcopy(line.get('cross_sources', [])),
                    quality_review=deepcopy(line.get('quality_review')))

    @staticmethod
    def _query(query, name):
        value = query.get(name) if isinstance(query, dict) else None
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        return _safe(value, name)

    def _get(self, operation, query):
        if operation == 'line':
            line_id = self._query(query, 'id') if 'id' in query else None
            if isinstance(query, dict) and 'run_id' in query:
                run_id = self._query(query, 'run_id')
                with self._database() as db:
                    if not self._has_tables(db):
                        raise RepertoireError('run_not_found', '未找到这次棋谱训练。', 404)
                    row = self._row(db, run_id)
                    if line_id is not None and row['line_id'] != line_id:
                        raise RepertoireError('source_mismatch', '棋谱与训练记录不匹配。', 409)
                    line = json.loads(row['snapshot'])
            else:
                with self._database() as db:
                    version = query.get('version')
                    if isinstance(version, list) and len(version) == 1:
                        version = version[0]
                    line = Editor.publication(db, line_id, version)
                if line is None:
                    sources, _ = self._sources()
                    line = sources.get(line_id)
            if line is None:
                raise RepertoireError('line_unavailable', '这条棋谱暂不可用，已有训练记录仍保留。', 404)
            if isinstance(query, dict) and 'version' in query:
                version = query['version']
                if isinstance(version, list) and len(version) == 1:
                    version = version[0]
                if not isinstance(version, (str, int)) or str(version) != str(line['line']['version']):
                    raise RepertoireError('source_changed', '棋谱版本已变化，请从这次训练的记录回看原谱。', 409)
            if line.get('mode') == graph.MODE:
                if isinstance(query, dict) and 'run_id' in query:
                    return Editor.preview(line, json.loads(row['_manual_state']), row['side'])
                return Editor.preview(line)
            return dict(line=deepcopy(line['line']), start_fen=line['start_fen'],
                        moves=[dict(ply=i + 1, move=move, name=line['names'][i], fen_after=line['states'][i + 1])
                               for i, move in enumerate(line['moves'])])
        if operation == 'run':
            run_id = self._query(query, 'id')
            with self._database() as db:
                if not self._has_tables(db):
                    raise RepertoireError('run_not_found', '未找到这次棋谱训练。', 404)
                return self._view(self._row(db, run_id))
        if operation == 'catalog':
            sources, unavailable = self._sources()
            active, history = [], []
            with self._database() as db:
                if self._has_tables(db):
                    active = [self._view(self._row(db, row['id'])) for row in db.execute(
                        "SELECT * FROM repertoire_runs WHERE status='active' ORDER BY updated_at DESC, id")]
                    history = [self._view(self._row(db, row['id'])) for row in db.execute(
                        "SELECT * FROM repertoire_runs WHERE status!='active' ORDER BY updated_at DESC, id LIMIT 50")]
                personal = Editor.publications(db)
            return dict(version=VERSION, lines=[deepcopy(v['line']) for v in personal] + [deepcopy(v['line']) for v in sources.values()],
                        unavailable=unavailable, active_runs=active, history=history)
        raise RepertoireError('not_found', '未找到这个棋谱训练操作。', 404)

    @staticmethod
    def _advance(saved, ply, side):
        own_color = 'R' if side == 'red' else 'B'
        while ply < len(saved['moves']):
            color = saved['start_color'] if ply % 2 == 0 else ('B' if saved['start_color'] == 'R' else 'R')
            if color == own_color:
                break
            ply += 1
        return ply

    def _start(self, db, body, request_id, now):
        line_id = _safe(body.get('line_id'), '棋谱标识')
        side = body.get('side')
        if side not in ('red', 'black'):
            raise RepertoireError('invalid_side', '请选择执红或执黑。')
        saved = Editor.publication(db, line_id)
        if saved is None:
            sources, _ = self._sources()
            saved = sources.get(line_id)
        if saved is None:
            raise RepertoireError('line_unavailable', '这条棋谱暂不可用，已有训练记录仍保留。', 404)
        if 'content_hash' in body:
            content_hash = body['content_hash']
            if not isinstance(content_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', content_hash):
                raise RepertoireError('invalid_request', '棋谱版本标识格式不正确。')
            if content_hash != saved['line']['content_hash']:
                raise RepertoireError('source_changed', '棋谱内容已变化，请重新看谱后开始。', 409)
        run_id = str(uuid.uuid4())
        if saved.get('mode') == graph.MODE:
            state = dict(node_id=saved['graph']['root_id'], revision=1,
                         opponent_choices=graph.choices(saved['graph'], run_id))
            graph.advance(saved['graph'], state, side)
            ply = len(saved['graph']['nodes'][state['node_id']]['history'])
        else:
            state = None
            ply = self._advance(saved, 0, side)
        db.execute('INSERT INTO repertoire_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (run_id, line_id, saved['line']['version'], _json(saved), side, 'active', ply, now, now, None, None))
        if state is not None:
            db.execute('INSERT INTO repertoire_manual_runs VALUES(?,?)', (run_id, _json(state)))
        db.execute('INSERT INTO repertoire_events(run_id,kind,ply,move,request_id,created_at) VALUES(?,?,?,?,?,?)',
                   (run_id, 'start', ply, None, request_id, now))
        return self._view(self._row(db, run_id))

    def _move(self, db, body, request_id, now):
        run_id = _safe(body.get('run_id'), '训练标识')
        row = self._row(db, run_id)
        if row['status'] != 'active':
            raise RepertoireError('run_closed', '这次训练已经结束，请查看结果或重新开始。', 409)
        if type(body.get('ply')) is not int or body['ply'] != row['ply']:
            raise RepertoireError('stale_position', '棋盘进度已变化，请重新读取当前训练。', 409)
        move = body.get('move')
        if not isinstance(move, str) or not _MOVE.fullmatch(move):
            raise RepertoireError('illegal_move', '请完成一次合法走子；本次未记错。')
        saved = json.loads(row['snapshot'])
        if saved.get('mode') == graph.MODE:
            return self._manual_move(db, row, saved, body, request_id, now)
        ply = row['ply']
        board, color = _starting_board(saved['states'][ply])
        if move not in legal_moves(board, color):
            raise RepertoireError('illegal_move', '这步不符合走子规则；本次未记错。')
        feedback = None
        if move != saved['moves'][ply]:
            status = 'failed'
            feedback = dict(actual=move, actual_name=notation_one([r[:] for r in board], move, black_arabic=True),
                            expected=saved['moves'][ply], expected_name=saved['names'][ply], ply=ply + 1)
        else:
            ply = self._advance(saved, ply + 1, row['side'])
            status = 'passed' if ply == len(saved['moves']) else 'active'
        db.execute('UPDATE repertoire_runs SET status=?,ply=?,updated_at=?,completed_at=?,feedback=? WHERE id=?',
                   (status, ply, now, None if status == 'active' else now,
                    _json(feedback) if feedback else None, run_id))
        db.execute('INSERT INTO repertoire_events(run_id,kind,ply,move,request_id,created_at) VALUES(?,?,?,?,?,?)',
                   (run_id, 'move', row['ply'], move, request_id, now))
        return self._view(self._row(db, run_id))

    def _manual_move(self, db, row, saved, body, request_id, now):
        state = json.loads(row['_manual_state'])
        if type(body.get('revision')) is not int or body['revision'] != state['revision']:
            raise RepertoireError('stale_revision', '训练进度已变化，请重新读取当前训练。', 409)
        compiled = saved['graph']
        node = compiled['nodes'][state['node_id']]
        board, color = _starting_board(node['fen'])
        move = body['move']
        if move not in legal_moves(board, color):
            raise RepertoireError('illegal_move', '这步不符合走子规则；本次未记错。')
        feedback = None
        if move not in node['children']:
            status = 'failed'
            expected = next(iter(node['children']))
            answers = [dict(move=value, name=compiled['nodes'][edge['child_id']]['name'])
                       for value, edge in node['children'].items()]
            feedback = dict(reason='not_selected', actual=move,
                actual_name=notation_one([r[:] for r in board], move, black_arabic=True),
                expected=expected, expected_name=compiled['nodes'][node['children'][expected]['child_id']]['name'],
                accepted_answers=answers, ply=len(node['history']) + 1,
                message='本次未走本人纳入的着法，不据此判断棋质。')
        else:
            state['node_id'] = node['children'][move]['child_id']
            graph.advance(compiled, state, row['side'])
            status = 'passed' if compiled['nodes'][state['node_id']]['terminal'] else 'active'
        state['revision'] += 1
        ply = len(compiled['nodes'][state['node_id']]['history'])
        db.execute('UPDATE repertoire_manual_runs SET state=? WHERE run_id=?', (_json(state), row['id']))
        db.execute('UPDATE repertoire_runs SET status=?,ply=?,updated_at=?,completed_at=?,feedback=? WHERE id=?',
            (status, ply, now, None if status == 'active' else now, _json(feedback) if feedback else None, row['id']))
        db.execute('INSERT INTO repertoire_events(run_id,kind,ply,move,request_id,created_at) VALUES(?,?,?,?,?,?)',
            (row['id'], 'move', row['ply'], move, request_id, now))
        return self._view(self._row(db, row['id']))

    def _abandon(self, db, body, request_id, now):
        run_id = _safe(body.get('run_id'), '训练标识')
        row = self._row(db, run_id)
        if row['status'] != 'active':
            raise RepertoireError('run_closed', '这次训练已经结束。', 409)
        db.execute("UPDATE repertoire_runs SET status='abandoned',updated_at=?,completed_at=? WHERE id=?",
                   (now, now, run_id))
        if '_manual_state' in row:
            state = json.loads(row['_manual_state'])
            state['revision'] += 1
            db.execute('UPDATE repertoire_manual_runs SET state=? WHERE run_id=?', (_json(state), run_id))
        db.execute('INSERT INTO repertoire_events(run_id,kind,ply,move,request_id,created_at) VALUES(?,?,?,?,?,?)',
                   (run_id, 'abandon', row['ply'], None, request_id, now))
        return self._view(self._row(db, run_id))

    def dispatch(self, method, operation, body=None, query=None):
        if query is None:
            query = {}
        if not isinstance(query, dict):
            raise RepertoireError('invalid_request', '查询参数格式不正确。')
        if method == 'GET':
            if operation in EDITOR_GET:
                return Editor(self).get(operation, query)
            allowed = {'catalog': set(), 'line': {'id', 'version', 'run_id'}, 'run': {'id'}}
            if operation in allowed:
                if set(query) - allowed[operation] or any(
                        isinstance(value, list) and len(value) != 1 for value in query.values()):
                    raise RepertoireError('invalid_request', '查询参数缺失、重复或不受支持。')
                if operation == 'line' and not ({'id', 'run_id'} & set(query)):
                    raise RepertoireError('invalid_request', '请选择棋谱或训练记录。')
            return self._get(operation, query)
        if method != 'POST':
            raise RepertoireError('method_not_allowed', '不支持这个请求方法。', 405)
        if operation not in ('start', 'move', 'abandon', *EDITOR_POST):
            raise RepertoireError('not_found', '未找到这个棋谱训练操作。', 404)
        if not isinstance(body, dict):
            raise RepertoireError('invalid_request', '请求内容必须是JSON对象。')
        allowed = {'start': {'line_id', 'side', 'request_id', 'content_hash'},
                   'move': {'run_id', 'ply', 'move', 'revision', 'request_id'},
                   'abandon': {'run_id', 'request_id'}, **EDITOR_POST}
        if query or set(body) - allowed[operation]:
            raise RepertoireError('invalid_request', '请求包含不受支持的参数。')
        request_id = _safe(body.get('request_id'), '请求标识')
        payload_hash = hashlib.sha256(_json(body).encode('utf-8')).hexdigest()
        with self._database(write=True) as db:
            receipt = db.execute('SELECT * FROM repertoire_requests WHERE request_id=?', (request_id,)).fetchone()
            if receipt:
                if receipt['operation'] != operation or receipt['payload_hash'] != payload_hash:
                    raise RepertoireError('request_conflict', '请求标识已用于其它操作，请重新读取训练状态。', 409)
                return json.loads(receipt['response'])
            now = _now()
            response = (Editor(self).mutate(db, operation, body, now) if operation in EDITOR_POST
                        else getattr(self, '_' + operation)(db, body, request_id, now))
            db.execute('INSERT INTO repertoire_requests VALUES(?,?,?,?,?)',
                       (request_id, operation, payload_hash, _json(response), now))
            return response

    def editor_context(self, draft_id, node_id=graph.ROOT_ID, revision=None):
        context = Editor(self).context(draft_id, node_id or graph.ROOT_ID)
        if revision is not None and (type(revision) is not int or revision != context['revision']):
            raise RepertoireError('draft_changed', '录谱已在别处修改，请重新读取后再查看参考。', 409)
        return context


_SERVICE = None
_SERVICE_LOCK = threading.Lock()


def service():
    global _SERVICE
    if _SERVICE is None:
        with _SERVICE_LOCK:
            if _SERVICE is None:
                _SERVICE = Service(Path(__file__).resolve().parents[1])
    return _SERVICE


def dispatch(method, operation, body=None, query=None):
    return service().dispatch(method, operation, body=body, query=query)
