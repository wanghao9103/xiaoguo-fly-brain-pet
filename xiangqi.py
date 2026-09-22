"""Chinese chess rules and a small deterministic teacher, using only stdlib.

Red (uppercase) starts at the bottom and moves first. Coordinates are zero-based
``[from_row, from_col, to_row, to_col]``. Checkmate AND stalemate lose. Repetition
is intentionally a casual rule: the third identical board/side-to-move is a draw,
not a tournament adjudication of perpetual checking or chasing.

Movement reference: World Xiangqi Federation, World Xiangqi Rules, chapter 1:
https://www.wxf-xiangqi.org/images/wxf-rules/2018_World_XiangQi_Rules_English2018.pdf
"""

from copy import deepcopy


ROWS, COLS = 10, 9
INITIAL_BOARD = (
    "rnbakabnr", ".........", ".c.....c.", "p.p.p.p.p", ".........",
    ".........", "P.P.P.P.P", ".C.....C.", ".........", "RNBAKABNR",
)
FEATURE_LABELS = (
    "吃子价值", "移动子价值", "是否吃子", "落点受攻击", "落点有保护", "是否将军",
    "落点前进程度", "落点中心程度", "接近敌方将帅", "是否过河", "己方材料占比", "是否兵卒",
)
VALUES = {"K": 0, "R": 900, "N": 400, "B": 200, "A": 200, "C": 450, "P": 100}
_MATE = 1_000_000.0
_ORTHOGONAL = ((-1, 0), (1, 0), (0, -1), (0, 1))
_DIAGONAL = ((-1, -1), (-1, 1), (1, -1), (1, 1))
_HORSE = ((-2, -1), (-2, 1), (2, -1), (2, 1), (-1, -2), (1, -2), (-1, 2), (1, 2))


def _side(piece):
    return 0 if piece == "." else 1 if piece.isupper() else -1


def _inside(row, col):
    return 0 <= row < ROWS and 0 <= col < COLS


def _palace(row, col, side):
    return 3 <= col <= 5 and (7 <= row <= 9 if side == 1 else 0 <= row <= 2)


def _crossed(row, side):
    return row <= 4 if side == 1 else row >= 5


class XiangqiGame:
    """Rules own legality; search and feature extraction do not alter the game."""

    def __init__(self, board=None, turn=1):
        if type(turn) is not int or turn not in (1, -1):
            raise ValueError("行棋方必须为 1（红）或 -1（黑）")
        source = INITIAL_BOARD if board is None else board
        if not isinstance(source, (list, tuple)) or len(source) != ROWS:
            raise ValueError("象棋棋盘必须为 10 行 9 列")
        # The explicit alphabet avoids accepting other isupper()/islower() text.
        allowed = set(".KRNBACPkrnbacp")
        if any(not isinstance(row, (str, list, tuple)) or len(row) != COLS for row in source):
            raise ValueError("象棋棋盘必须为 10 行 9 列")
        if any(not isinstance(cell, str) or len(cell) != 1 or cell not in allowed
               for row in source for cell in row):
            raise ValueError("棋盘含未知棋子")
        self.board = [list(row) for row in source]
        flat = [cell for row in self.board for cell in row]
        if flat.count("K") != 1 or flat.count("k") != 1:
            raise ValueError("棋盘必须各有一个将帅")
        for side in (1, -1):
            if not _palace(*self._king(side), side):
                raise ValueError("将帅必须在己方九宫内")
        self.turn = turn
        self.winner = None
        self.reason = None
        self.history = []
        self.winning_line = []
        self._undo_frames = []
        self._positions = {self._position_key(turn): 1}
        self._update_outcome()

    def _king(self, side):
        target = "K" if side == 1 else "k"
        for row, cells in enumerate(self.board):
            for col, piece in enumerate(cells):
                if piece == target:
                    return row, col
        return None

    def _position_key(self, side):
        return side, "".join("".join(row) for row in self.board)

    def _attacked(self, row, col, by_side):
        """Geometric attacks, including pinned pieces; never calls legal_moves."""
        board = self.board
        for dr, dc in _ORTHOGONAL:
            rr, cc, distance, screen = row + dr, col + dc, 1, False
            while _inside(rr, cc):
                piece = board[rr][cc]
                if piece != ".":
                    kind = piece.upper()
                    enemy = _side(piece) == by_side
                    if not screen:
                        king_attack = kind == "K" and (
                            distance == 1 and _palace(row, col, by_side)
                            or dc == 0 and board[row][col].upper() == "K"
                        )
                        if enemy and (kind == "R" or king_attack):
                            return True
                        screen = True
                    else:
                        if enemy and kind == "C":
                            return True
                        break
                rr, cc, distance = rr + dr, cc + dc, distance + 1
        for dr, dc in _HORSE:
            rr, cc = row + dr, col + dc
            if not _inside(rr, cc) or board[rr][cc] != ("N" if by_side == 1 else "n"):
                continue
            leg_r = rr - (dr // 2 if abs(dr) == 2 else 0)
            leg_c = cc - (dc // 2 if abs(dc) == 2 else 0)
            if board[leg_r][leg_c] == ".":
                return True
        pawn = "P" if by_side == 1 else "p"
        rr = row + by_side
        if _inside(rr, col) and board[rr][col] == pawn:
            return True
        if _crossed(row, by_side):
            for cc in (col - 1, col + 1):
                if _inside(row, cc) and board[row][cc] == pawn:
                    return True
        for dr, dc in _DIAGONAL:
            rr, cc = row + dr, col + dc
            if (_inside(rr, cc) and _palace(row, col, by_side)
                    and board[rr][cc] == ("A" if by_side == 1 else "a")):
                return True
            rr, cc = row + 2 * dr, col + 2 * dc
            if (_inside(rr, cc) and not _crossed(row, by_side)
                    and board[rr][cc] == ("B" if by_side == 1 else "b")
                    and board[row + dr][col + dc] == "."):
                return True
        return False

    def is_in_check(self, side=None):
        side = self.turn if side is None else side
        if type(side) is not int or side not in (1, -1):
            raise ValueError("行棋方必须为 1 或 -1")
        king = self._king(side)
        return king is None or self._attacked(*king, -side)

    def _pseudo_piece(self, row, col):
        piece = self.board[row][col]
        side, kind = _side(piece), piece.upper()
        if not side:
            return
        if kind in ("R", "C"):
            for dr, dc in _ORTHOGONAL:
                rr, cc, screen = row + dr, col + dc, False
                while _inside(rr, cc):
                    target = self.board[rr][cc]
                    if not screen:
                        if target == ".":
                            yield row, col, rr, cc
                        elif kind == "R":
                            if _side(target) == -side and target.upper() != "K":
                                yield row, col, rr, cc
                            break
                        else:
                            screen = True
                    elif target != ".":
                        if _side(target) == -side and target.upper() != "K":
                            yield row, col, rr, cc
                        break
                    rr, cc = rr + dr, cc + dc
            return
        if kind == "K":
            offsets = _ORTHOGONAL
        elif kind == "A":
            offsets = _DIAGONAL
        elif kind == "B":
            offsets = tuple((2 * dr, 2 * dc) for dr, dc in _DIAGONAL)
        elif kind == "N":
            offsets = _HORSE
        else:
            offsets = ((-side, 0),) + (((0, -1), (0, 1)) if _crossed(row, side) else ())
        for dr, dc in offsets:
            rr, cc = row + dr, col + dc
            if not _inside(rr, cc):
                continue
            target = self.board[rr][cc]
            if _side(target) == side or target.upper() == "K":
                continue
            if kind in ("K", "A") and not _palace(rr, cc, side):
                continue
            if kind == "B" and (_crossed(rr, side) or self.board[row + dr // 2][col + dc // 2] != "."):
                continue
            if kind == "N":
                leg_r = row + (dr // 2 if abs(dr) == 2 else 0)
                leg_c = col + (dc // 2 if abs(dc) == 2 else 0)
                if self.board[leg_r][leg_c] != ".":
                    continue
            yield row, col, rr, cc

    def _push(self, move):
        fr, fc, tr, tc = move
        captured = self.board[tr][tc]
        self.board[tr][tc], self.board[fr][fc] = self.board[fr][fc], "."
        return captured

    def _pop(self, move, captured):
        fr, fc, tr, tc = move
        self.board[fr][fc], self.board[tr][tc] = self.board[tr][tc], captured

    def _legal_iter(self, side, captures_only=False):
        for row in range(ROWS):
            for col in range(COLS):
                if _side(self.board[row][col]) != side:
                    continue
                for move in self._pseudo_piece(row, col):
                    if captures_only and self.board[move[2]][move[3]] == ".":
                        continue
                    captured = self._push(move)
                    try:
                        safe = not self.is_in_check(side)
                    finally:
                        self._pop(move, captured)
                    if safe:
                        yield move

    def legal_moves(self):
        return [] if self.winner is not None else [list(move) for move in self._legal_iter(self.turn)]

    def _coordinate(self, move):
        if not isinstance(move, (list, tuple)) or len(move) != 4:
            raise ValueError("棋步必须为 [起始行, 起始列, 目标行, 目标列]")
        if any(type(value) is not int for value in move):
            raise ValueError("行列必须为整数")
        fr, fc, tr, tc = move
        if not _inside(fr, fc) or not _inside(tr, tc):
            raise ValueError("落点超出棋盘")
        return tuple(move)

    def _validate_move(self, move):
        move = self._coordinate(move)
        if self.winner is not None:
            raise ValueError("本局已结束")
        fr, fc, _, _ = move
        if _side(self.board[fr][fc]) != self.turn or move not in self._pseudo_piece(fr, fc):
            raise ValueError("不符合棋子走法，或不是己方棋子")
        captured = self._push(move)
        try:
            safe = not self.is_in_check(self.turn)
        finally:
            self._pop(move, captured)
        if not safe:
            raise ValueError("该步会使己方被将军或将帅照面")
        return move

    def _update_outcome(self):
        self.winner, self.reason = None, None
        if next(self._legal_iter(self.turn), None) is None:
            self.winner = -self.turn
            self.reason = "checkmate" if self.is_in_check(self.turn) else "stalemate"
        elif self._positions.get(self._position_key(self.turn), 0) >= 3:
            self.winner, self.reason = 0, "repetition"

    def play(self, move):
        move = self._validate_move(move)
        fr, fc, tr, tc = move
        side, piece = self.turn, self.board[fr][fc]
        previous = self.winner, self.reason
        captured = self._push(move)
        self._undo_frames.append((move, captured, previous))
        self.history.append({"move": list(move), "side": side, "piece": piece, "captured": captured})
        self.turn = -side
        key = self._position_key(self.turn)
        self._positions[key] = self._positions.get(key, 0) + 1
        self._update_outcome()
        return self.snapshot()

    def undo(self, plies=2):
        if type(plies) is not int or plies < 1:
            raise ValueError("悔棋步数必须是正整数")
        for _ in range(min(plies, len(self._undo_frames))):
            key = self._position_key(self.turn)
            self._positions[key] -= 1
            if not self._positions[key]:
                del self._positions[key]
            move, captured, previous = self._undo_frames.pop()
            record = self.history.pop()
            self._pop(move, captured)
            self.turn = record["side"]
            self.winner, self.reason = previous
        return self.snapshot()

    def clone(self):
        return deepcopy(self)

    def snapshot(self):
        return {
            "kind": "xiangqi", "board": deepcopy(self.board), "turn": self.turn,
            "winner": self.winner, "reason": self.reason, "history": deepcopy(self.history),
            "last_move": list(self.history[-1]["move"]) if self.history else None,
            "check": self.is_in_check(), "winning_line": [],
        }

    def _evaluate(self, side):
        total = 0.0
        for row, cells in enumerate(self.board):
            for col, piece in enumerate(cells):
                owner = _side(piece)
                if not owner:
                    continue
                kind = piece.upper()
                advance = 9 - row if owner == 1 else row
                center = 4 - abs(col - 4)
                value = VALUES[kind]
                if kind == "P":
                    value += 8 * advance + (60 if _crossed(row, owner) else 0) + 3 * center
                elif kind in ("N", "C"):
                    value += 5 * center + 2 * min(advance, 6)
                elif kind == "R":
                    value += 2 * center + min(advance, 6)
                total += value if owner == side else -value
        return total

    def _quiescence(self, side, remaining, positions, alpha=-float("inf"), beta=float("inf")):
        """Extend exchanges by at most two plies without assuming a free capture.

        A checked side must consider all legal evasions, including quiet moves;
        only an unchecked side may keep its static score (stand pat). At the hard
        depth boundary the heuristic is approximate, but mate/stalemate and the
        casual repetition draw are still detected before that boundary.
        """
        if next(self._legal_iter(side), None) is None:
            return -_MATE
        if positions.get(self._position_key(side), 0) >= 3:
            return 0.0
        if remaining <= 0:
            return self._evaluate(side)
        checked = self.is_in_check(side)
        best = -float("inf") if checked else self._evaluate(side)
        if best >= beta:
            return best
        alpha = max(alpha, best)
        moves = list(self._legal_iter(side, captures_only=not checked))
        moves.sort(key=lambda move: (-VALUES.get(self.board[move[2]][move[3]].upper(), 0), move))
        for move in moves:
            captured = self._push(move)
            key = self._position_key(-side)
            positions[key] = positions.get(key, 0) + 1
            try:
                score = -self._quiescence(-side, remaining - 1, positions, -beta, -alpha)
                best = max(best, score)
                alpha = max(alpha, best)
            finally:
                positions[key] -= 1
                if not positions[key]:
                    del positions[key]
                self._pop(move, captured)
            if alpha >= beta:
                break
        return best

    def _search(self, side, depth, positions, quiet_depth=0):
        # Only one legal move is needed to distinguish a leaf from mate/stalemate.
        if depth <= 0:
            if quiet_depth:
                return self._quiescence(side, quiet_depth, positions)
            if next(self._legal_iter(side), None) is None:
                return -_MATE
            if positions.get(self._position_key(side), 0) >= 3:
                return 0.0
            return self._evaluate(side)
        moves = list(self._legal_iter(side))
        if not moves:
            return -_MATE - depth
        if positions.get(self._position_key(side), 0) >= 3:
            return 0.0
        best = -float("inf")
        for move in moves:
            captured = self._push(move)
            key = self._position_key(-side)
            positions[key] = positions.get(key, 0) + 1
            try:
                best = max(best, -self._search(-side, depth - 1, positions, quiet_depth))
            finally:
                positions[key] -= 1
                if not positions[key]:
                    del positions[key]
                self._pop(move, captured)
        return best

    def rank_moves(self, depth=2, limit=12):
        """Evaluate all legal root moves and all replies at depth two.

        Depth is capped at two full plies; depth two also extends exchanges by at
        most two capture/evasion plies. Depth one stays fast. Limit truncates the
        sorted result, never the legal set. A forced mating/stalemating line is
        marked forced. These are shallow teacher scores, not neural predictions.
        """
        if type(depth) is not int or depth < 1:
            raise ValueError("搜索深度必须是正整数")
        if type(limit) is not int or limit < 1:
            raise ValueError("候选数量必须是正整数")
        if self.winner is not None:
            return []
        depth = min(depth, 2)
        positions = self._positions.copy()
        ranked = []
        for move in list(self._legal_iter(self.turn)):
            captured = self._push(move)
            key = self._position_key(-self.turn)
            positions[key] = positions.get(key, 0) + 1
            try:
                score = -self._search(-self.turn, depth - 1, positions, quiet_depth=2 if depth == 2 else 0)
            finally:
                positions[key] -= 1
                if not positions[key]:
                    del positions[key]
                self._pop(move, captured)
            ranked.append({"move": list(move), "score": float(score), "forced": score >= _MATE})
        ranked.sort(key=lambda entry: (-entry["score"], entry["move"]))
        return ranked[:limit]

    def move_features(self, move):
        """Twelve static [0, 1] features; no teacher score or search is an input."""
        move = self._validate_move(move)
        fr, fc, tr, tc = move
        side, piece = self.turn, self.board[fr][fc]
        captured = self._push(move)
        try:
            target_king = self._king(-side)
            distance = abs(tr - target_king[0]) + abs(tc - target_king[1])
            own_material = enemy_material = 0
            for cells in self.board:
                for cell in cells:
                    if _side(cell) == side:
                        own_material += VALUES[cell.upper()]
                    elif _side(cell) == -side:
                        enemy_material += VALUES[cell.upper()]
            values = [
                VALUES.get(captured.upper(), 0) / 900,
                VALUES[piece.upper()] / 900,
                int(captured != "."), int(self._attacked(tr, tc, -side)),
                int(self._attacked(tr, tc, side)), int(self.is_in_check(-side)),
                (9 - tr if side == 1 else tr) / 9,
                1 - abs(tc - 4) / 4, 1 - distance / 17,
                int(_crossed(tr, side)),
                own_material / (own_material + enemy_material) if own_material + enemy_material else 0.5,
                int(piece.upper() == "P"),
            ]
        finally:
            self._pop(move, captured)
        return [float(max(0.0, min(1.0, value))) for value in values]
