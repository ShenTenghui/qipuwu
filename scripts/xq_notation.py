"""UCCI着法(引擎坐标, rank0=红方底线) -> 中文记谱(炮二平五)"""
FEN0 = 'rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1'
FILES = 'abcdefghi'
RED_NUM = {'车': 1, '马': 2, '相': 3, '仕': 4, '帅': 5, '炮': 6, '兵': 7}
BLACK_NUM = {'車': 1, '馬': 2, '象': 3, '士': 4, '將': 5, '炮': 6, '卒': 7}
RED_PIECES = set(RED_NUM)
BLACK_PIECES = set(BLACK_NUM)


def parse_fen(fen):
    """X-FEN -> 10x9 board, 元素 (color, type) 或 None"""
    board = [[None] * 9 for _ in range(10)]
    for r, row in enumerate(fen.split()[0].split('/')):
        c = 0
        for ch in row:
            if ch.isdigit():
                c += int(ch)
            else:
                color = 'R' if ch.isupper() else 'B'
                if color == 'R':
                    typ = {'R': '车', 'N': '马', 'B': '相', 'A': '仕', 'K': '帅', 'C': '炮', 'P': '兵'}[ch]
                else:
                    typ = {'r': '車', 'n': '馬', 'b': '象', 'a': '士', 'k': '將', 'c': '炮', 'p': '卒'}[ch]
                board[r][c] = (color, typ)
                c += 1
    return board


def apply_move(board, mv):
    """返回 (from, to, piece, captured). 着法为引擎坐标(行号从红方底线), 棋盘为X-FEN行序(黑在上)"""
    f, t = mv[:2], mv[2:]
    fr, fc = 9 - int(f[1]), FILES.index(f[0])
    tr, tc = 9 - int(t[1]), FILES.index(t[0])
    p = board[fr][fc]
    cap = board[tr][tc]
    board[fr][fc] = None
    board[tr][tc] = p
    return (fr, fc, tr, tc, p, cap)


def file_num(color, col):
    """列字母 -> 该方视角文件号(1-9)"""
    idx = FILES.index(col)
    return 9 - idx if color == 'R' else idx + 1


NUM_AR = str.maketrans('一二三四五六七八九', '123456789')


def notation_one(board, mv, black_arabic=False):
    """单步中文记谱. 歧义判定在走子前进行(同列同类子>=2需前/后)
    black_arabic=True: 黑方数字用阿拉伯数字(炮2平5), 符合标准棋谱习惯;
    默认False(全中文), 鲨鱼PGN走自己的全角转换"""
    f, t = mv[:2], mv[2:]
    fr, fc = 9 - int(f[1]), FILES.index(f[0])
    tr, tc = 9 - int(t[1]), FILES.index(t[0])
    color, typ = board[fr][fc]
    # 走子前: 起点列上除自己外的同色同类子
    others = [r for r in range(10) if r != fr and board[r][fc]
              and board[r][fc][0] == color and board[r][fc][1] == typ]
    CN = '一二三四五六七八九'
    prefix = ''
    if others and typ in '車馬炮兵卒相象仕士车马帥將帅':
        if color == 'R':
            order = sorted([fr] + others)  # 行小=靠近黑方=前
        else:
            order = sorted([fr] + others, reverse=True)  # 行大=靠近红方=前
        pos = order.index(fr)
        names = ['前', '中', '后'] if len(order) == 3 else ['前', '后']
        prefix = names[pos] if pos < len(names) else names[-1]
    else:
        prefix = CN[file_num(color, FILES[fc]) - 1]
    # 更新棋盘
    board[fr][fc] = None
    board[tr][tc] = (color, typ)
    # 方向与目标
    fwd = fr > tr if color == 'R' else fr < tr  # 进
    if typ in '車炮车':
        if fr == tr:
            act = '平' + CN[file_num(color, FILES[tc]) - 1]
        else:
            act = ('进' if fwd else '退') + CN[abs(fr - tr) - 1]
    elif typ in '馬相象仕士马':
        act = ('进' if fwd else '退') + CN[file_num(color, FILES[tc]) - 1]
    elif typ in '帥將帅':
        if fr == tr:
            act = '平' + CN[file_num(color, FILES[tc]) - 1]
        else:
            act = ('进' if fwd else '退') + '一'
    elif typ in '兵卒':
        if fr == tr:
            act = '平' + CN[file_num(color, FILES[tc]) - 1]
        else:
            act = '进一'
    # 前/中/后 在棋子名前(前车进六), 文件号在棋子名后(炮二平五)
    s = prefix + typ + act if prefix in ('前', '中', '后') else typ + prefix + act
    if black_arabic and color == 'B':
        s = s.translate(NUM_AR)
    return s


def moves_to_chinese(moves, fen=FEN0, black_arabic=False):
    """完整着法序列 -> 中文记谱列表"""
    board = parse_fen(fen)
    out = []
    for mv in moves:
        out.append(notation_one(board, mv, black_arabic))
    return out


if __name__ == '__main__':
    test = ['h2e2', 'b9c7', 'h0g2', 'b7b8', 'c3c4', 'g6g5']
    print(' '.join(moves_to_chinese(test)))
