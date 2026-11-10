"""Synthetic rule sequences only; no engine, real games or personal answers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from app.repertoire_training import Service, RepertoireError

PAWNS = ['a3a4', 'a6a5', 'c3c4', 'c6c5']
OTHER = ['g3g4', 'g6g5', 'i3i4', 'i6i5']


class ManualRepertoireTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = Service(self.root)
        self.serial = 0

    def call(self, operation, **body):
        self.serial += 1
        body.setdefault('request_id', 'synthetic-' + str(self.serial))
        return self.service.dispatch('POST', operation, body)

    def create(self, goal=4):
        return self.call('editor_create', title='Synthetic pawn branches', goal_plies=goal)

    def get(self, draft, node='root'):
        return self.service.dispatch('GET', 'editor', query={'id': draft['id'], 'node_id': node})

    def record(self, draft, move, enabled=False):
        return self.call('editor_record', id=draft['id'], revision=draft['revision'],
                         node_id=draft['current']['id'], move=move, enabled=enabled)

    def route(self, draft, moves, enabled=True):
        draft = self.get(draft)
        for move in moves:
            draft = self.record(draft, move, enabled)
        return draft

    def publish(self, draft):
        return self.call('editor_publish', id=draft['id'], revision=draft['revision'])

    def start(self, draft, side='red'):
        p = draft['published']
        return self.call('start', line_id=p['line_id'], side=side, content_hash=p['content_hash'])

    def move(self, run, move):
        return self.call('move', run_id=run['id'], ply=run['ply'], revision=run['revision'], move=move)

    def rejects(self, code, operation):
        with self.assertRaises(RepertoireError) as finding:
            operation()
        self.assertEqual(finding.exception.code, code)

    def test_get_does_not_initialize_storage(self):
        self.assertEqual(self.service.dispatch('GET', 'editor_catalog'), {'drafts': []})
        self.assertFalse((self.root / 'training.db').exists())

    def test_recording_does_not_select_moves(self):
        draft = self.route(self.create(), PAWNS, enabled=False)
        self.assertEqual(len(draft['nodes']), 5)
        self.assertFalse(any(node['enabled'] for node in draft['nodes']))
        self.rejects('incomplete_repertoire', lambda: self.publish(draft))

    def test_enabled_dead_end_prevents_partial_publication(self):
        draft = self.route(self.create(), PAWNS)
        draft = self.record(self.get(draft), OTHER[0], enabled=True)
        self.rejects('incomplete_repertoire', lambda: self.publish(draft))

    def test_explicit_endpoint_and_unselected_draft_are_retained(self):
        draft = self.route(self.create(goal=20), PAWNS[:2])
        draft = self.call('editor_terminal', id=draft['id'], revision=draft['revision'],
                          node_id=draft['current']['id'], terminal=True)
        selected = self.publish(draft)
        run = self.start(selected)
        self.assertEqual(self.move(run, PAWNS[0])['status'], 'passed')
        draft = self.record(self.get(selected), OTHER[0])
        self.assertEqual(len(draft['nodes']), 4)
        selected = self.publish(draft)
        line = self.service.dispatch('GET', 'line', query={'id': selected['published']['line_id']})
        self.assertEqual([v['move'] for v in line['moves']], PAWNS[:2])

    def test_two_user_selected_branches_accept_both_and_reply_on_actual_path(self):
        draft = self.route(self.create(), PAWNS)
        published = self.publish(self.route(draft, OTHER))
        for moves in (PAWNS, OTHER):
            run = self.move(self.start(published), moves[0])
            self.assertEqual(run['last_move'], moves[1])
            self.assertEqual(self.move(run, moves[2])['status'], 'passed')

    def test_black_side_uses_only_the_published_opponent_edges(self):
        published = self.publish(self.route(self.create(), PAWNS))
        run = self.start(published, 'black')
        self.assertEqual((run['ply'], run['last_move']), (1, PAWNS[0]))
        run = self.move(run, PAWNS[1])
        self.assertEqual((run['ply'], run['last_move']), (3, PAWNS[2]))
        self.assertEqual(self.move(run, PAWNS[3])['status'], 'passed')

    def test_unselected_legal_move_fails_without_a_quality_claim(self):
        published = self.publish(self.route(self.create(), PAWNS))
        run = self.start(published)
        failed = self.move(run, OTHER[0])
        self.assertEqual((failed['status'], failed['ply'], failed['fen']), ('failed', 0, run['fen']))
        self.assertEqual(failed['feedback']['reason'], 'not_selected')
        self.assertIsNone(failed['quality_review'])

    def test_illegal_move_and_stale_revision_do_not_advance(self):
        published = self.publish(self.route(self.create(), PAWNS))
        run = self.start(published)
        self.rejects('illegal_move', lambda: self.move(run, 'a0a9'))
        self.rejects('stale_revision', lambda: self.call('move', run_id=run['id'], ply=0,
                     revision=999, move=PAWNS[0]))
        self.assertEqual(self.service.dispatch('GET', 'run', query={'id': run['id']}), run)

    def test_editor_compare_and_swap_prevents_lost_updates(self):
        draft = self.create()
        after = self.record(draft, PAWNS[0])
        self.rejects('draft_changed', lambda: self.record(draft, OTHER[0]))
        self.assertEqual(self.get(draft, after['current']['id']), after)

    def test_replayed_move_returns_original_receipt_without_rewinding(self):
        published = self.publish(self.route(self.create(), PAWNS))
        run = self.start(published)
        body = dict(run_id=run['id'], ply=0, revision=run['revision'], move=PAWNS[0], request_id='durable-request')
        after = self.service.dispatch('POST', 'move', body)
        final = self.move(after, PAWNS[2])
        self.assertEqual(self.service.dispatch('POST', 'move', body), after)
        self.assertEqual(Service(self.root).dispatch('GET', 'run', query={'id': run['id']}), final)

    def test_old_publication_is_not_regraded_after_draft_changes(self):
        first = self.publish(self.route(self.create(), PAWNS))
        old = self.start(first)
        changed = self.call('editor_toggle', id=first['id'], revision=first['revision'],
                            node_id='root', move=PAWNS[0], enabled=False)
        second = self.publish(self.route(changed, OTHER))
        self.assertEqual(second['published']['version'], 2)
        self.assertEqual(self.move(old, PAWNS[0])['status'], 'active')
        self.assertEqual(self.move(self.start(second), PAWNS[0])['status'], 'failed')

    def test_parallel_submissions_share_one_transaction_receipt(self):
        published = self.publish(self.route(self.create(), PAWNS))
        run = self.start(published)
        body = dict(run_id=run['id'], ply=0, revision=run['revision'], move=PAWNS[0], request_id='parallel-synthetic')
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: Service(self.root).dispatch('POST', 'move', body), range(3)))
        self.assertTrue(all(value == results[0] for value in results))
        self.assertEqual(results[0]['ply'], 2)

    def test_same_board_keeps_different_histories_and_selected_edges(self):
        a = ['a3a4', 'a6a5', 'c3c4', 'c6c5', 'g3g4', 'g6g5']
        b = ['c3c4', 'c6c5', 'a3a4', 'a6a5', 'i3i4', 'i6i5']
        draft = self.route(self.create(goal=6), a)
        first = next(n['id'] for n in draft['nodes'] if n['ply'] == 4)
        draft = self.route(draft, b)
        second = next(n['id'] for n in draft['nodes'] if n['ply'] == 4 and n['id'] != first)
        one, two = self.get(draft, first), self.get(draft, second)
        self.assertIn(second, one['transpositions'])
        self.assertEqual([x['move'] for x in one['edges']], [a[4]])
        self.assertEqual([x['move'] for x in two['edges']], [b[4]])

    def test_default_ten_rounds_completes_both_sides(self):
        # Deliberate synthetic palace shuffles, not an instructional game line.
        moves = ['e0e1', 'e9e8', 'e1e0', 'e8e9'] * 5
        published = self.publish(self.route(self.create(goal=20), moves))
        for side in ('red', 'black'):
            run = self.start(published, side)
            while run['status'] == 'active':
                run = self.move(run, moves[run['ply']])
            self.assertEqual((run['ply'], run['own_completed'], run['own_total']), (20, 10, 10))


if __name__ == '__main__':
    unittest.main()
