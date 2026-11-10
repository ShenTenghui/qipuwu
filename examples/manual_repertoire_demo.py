"""Small synthetic pawn recording; the temporary database is always discarded."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from app.repertoire_training import Service


def main():
    with tempfile.TemporaryDirectory() as directory:
        service = Service(directory)
        serial = 0

        def post(operation, **body):
            nonlocal serial
            serial += 1
            return service.dispatch('POST', operation, dict(body, request_id='demo-' + str(serial)))

        draft = post('editor_create', title='Synthetic pawn practice', goal_plies=4)
        moves = ['a3a4', 'a6a5', 'c3c4', 'c6c5']
        for move in moves:
            draft = post('editor_record', id=draft['id'], revision=draft['revision'],
                         node_id=draft['current']['id'], move=move, enabled=True)
        draft = post('editor_publish', id=draft['id'], revision=draft['revision'])
        pub = draft['published']
        run = post('start', line_id=pub['line_id'], side='red', content_hash=pub['content_hash'])
        while run['status'] == 'active':
            run = post('move', run_id=run['id'], ply=run['ply'], revision=run['revision'], move=moves[run['ply']])
        print('Recorded and explicitly selected four synthetic halfmoves.')
        print('Published version:', pub['version'])
        print('Red rehearsal:', run['status'], '| own moves:', run['own_completed'])
        print('No engine, personal game, or retained database was used.')


if __name__ == '__main__':
    main()
