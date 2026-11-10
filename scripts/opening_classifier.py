"""Pure rule helpers extracted from QipuWu opening_classifier.

Only piece geometry and king safety are included. No ECCO classifier, DLL,
opening database, subprocess, engine, or personal materials are distributed.
See docs/manual-repertoire-provenance.md for the exact source functions.
"""

_PIECE = {'车': 'R', '車': 'R', '马': 'N', '馬': 'N', '相': 'B',
          '象': 'B', '仕': 'A', '士': 'A', '帅': 'K', '將': 'K',
          '炮': 'C', '兵': 'P', '卒': 'P'}

def _screens(board, fr, fc, tr, tc):
    if fr != tr and fc != tc:
        return None
    dr = (tr > fr) - (tr < fr)
    dc = (tc > fc) - (tc < fc)
    r, c, total = fr + dr, fc + dc, 0
    while (r, c) != (tr, tc):
        total += board[r][c] is not None
        r, c = r + dr, c + dc
    return total

def _geometry(board, fr, fc, tr, tc, *, attacking=False):
    """Pure piece-movement rules; the caller checks side and king safety."""
    color, typ = board[fr][fc]
    typ = _PIECE[typ]
    dr, dc = tr - fr, tc - fc
    ar, ac = abs(dr), abs(dc)
    if not (ar or ac):
        return False
    if typ in ('R', 'C'):
        screens = _screens(board, fr, fc, tr, tc)
        return screens == (1 if typ == 'C' and board[tr][tc] else 0)
    if typ == 'N':
        if (ar, ac) not in ((1, 2), (2, 1)):
            return False
        lr = fr + (dr // 2 if ar == 2 else 0)
        lc = fc + (dc // 2 if ac == 2 else 0)
        return board[lr][lc] is None
    if typ == 'B':
        return (ar == ac == 2 and (tr >= 5 if color == 'R' else tr <= 4)
                and board[fr + dr // 2][fc + dc // 2] is None)
    if typ == 'A':
        return (ar == ac == 1 and 3 <= tc <= 5
                and (7 <= tr <= 9 if color == 'R' else 0 <= tr <= 2))
    if typ == 'K':
        if attacking and fc == tc and board[tr][tc] and _PIECE[board[tr][tc][1]] == 'K':
            return _screens(board, fr, fc, tr, tc) == 0
        return (ar + ac == 1 and 3 <= tc <= 5
                and (7 <= tr <= 9 if color == 'R' else 0 <= tr <= 2))
    fwd = -1 if color == 'R' else 1
    return ((dr == fwd and dc == 0) or
            (dr == 0 and ac == 1 and (fr <= 4 if color == 'R' else fr >= 5)))

def _in_check(board, color):
    king = next(((r, c) for r in range(10) for c in range(9)
                 if board[r][c] and board[r][c][0] == color
                 and _PIECE[board[r][c][1]] == 'K'), None)
    if king is None:
        return True
    for r in range(10):
        for c in range(9):
            if board[r][c] and board[r][c][0] != color:
                if _geometry(board, r, c, *king, attacking=True):
                    return True
    return False
