"""Deterministic, dependency-free freestyle Gomoku rules and a casual search teacher.

The search is deliberately separate from the learnable move scorer. Features contain
only board geometry, never search scores or game rewards. Five or more stones win;
there are no forbidden moves. Coordinates are zero-based ``[row, column]``.
"""

from copy import deepcopy
from math import inf


SIZE = 15
DIRECTIONS = ((0, 1), (1, 0), (1, 1), (1, -1))
FEATURE_LABELS = (
    "己方最长连线", "对方最长连线", "己方连线开口", "对方连线开口",
    "己方潜在成五窗口", "对方潜在成五窗口", "邻域己方棋子", "邻域对方棋子",
    "落点中心程度", "棋局进度", "己方连接方向", "对方连接方向",
)
_WIN = 10_000_000.0


class GomokuGame:
    """Mutable game; ranking and feature extraction leave its state unchanged."""

    def __init__(self):
        self.board = [[0] * SIZE for _ in range(SIZE)]
        self.turn = 1
        self.winner = None
        self.history = []
        self.winning_line = []

    @staticmethod
    def _inside(row, col):
        return 0 <= row < SIZE and 0 <= col < SIZE

    def _coordinate(self, move):
        if not isinstance(move, (list, tuple)) or len(move) != 2:
            raise ValueError("棋步必须是 [行, 列]")
        row, col = move
        if type(row) is not int or type(col) is not int:
            raise ValueError("行列必须是整数")
        if not self._inside(row, col):
            raise ValueError("落点超出棋盘")
        return row, col

    def _validate_move(self, move):
        row, col = self._coordinate(move)
        if self.winner is not None:
            raise ValueError("本局已结束")
        if self.board[row][col] != 0:
            raise ValueError("落点已有棋子")
        return row, col

    def _line(self, row, col, side, dr, dc):
        """Full contiguous line through a virtual stone at the given coordinate."""
        before, after = [], []
        rr, cc = row - dr, col - dc
        while self._inside(rr, cc) and self.board[rr][cc] == side:
            before.append([rr, cc])
            rr, cc = rr - dr, cc - dc
        rr, cc = row + dr, col + dc
        while self._inside(rr, cc) and self.board[rr][cc] == side:
            after.append([rr, cc])
            rr, cc = rr + dr, cc + dc
        return list(reversed(before)) + [[row, col]] + after

    def _win_line(self, row, col, side):
        for dr, dc in DIRECTIONS:
            line = self._line(row, col, side, dr, dc)
            if len(line) >= 5:
                return line
        return []

    def play(self, move):
        row, col = self._validate_move(move)
        side = self.turn
        self.board[row][col] = side
        self.history.append({"move": [row, col], "side": side})
        self.winning_line = self._win_line(row, col, side)
        if self.winning_line:
            self.winner = side
        elif not any(0 in line for line in self.board):
            self.winner = 0
        self.turn = -side
        return self.snapshot()

    def undo(self, plies=2):
        if type(plies) is not int or plies < 1:
            raise ValueError("悔棋步数必须是正整数")
        for _ in range(min(plies, len(self.history))):
            previous = self.history.pop()
            row, col = previous["move"]
            self.board[row][col] = 0
            self.turn = previous["side"]
        self.winner = None
        self.winning_line = []
        for row in range(SIZE):
            for col in range(SIZE):
                side = self.board[row][col]
                if side:
                    line = self._win_line(row, col, side)
                    if line:
                        self.winner, self.winning_line = side, line
                        return self.snapshot()
        if not any(0 in line for line in self.board):
            self.winner = 0
        return self.snapshot()

    def clone(self):
        return deepcopy(self)

    def snapshot(self):
        return {
            "kind": "gomoku", "board": deepcopy(self.board), "turn": self.turn,
            "winner": self.winner, "history": deepcopy(self.history),
            "last_move": list(self.history[-1]["move"]) if self.history else None,
            "winning_line": deepcopy(self.winning_line), "check": False,
        }

    def legal_moves(self):
        if self.winner is not None:
            return []
        return [[r, c] for r in range(SIZE) for c in range(SIZE) if not self.board[r][c]]

    def _nearby(self):
        occupied = [(r, c) for r in range(SIZE) for c in range(SIZE) if self.board[r][c]]
        if not occupied:
            return [(SIZE // 2, SIZE // 2)]
        result = set()
        for row, col in occupied:
            for rr in range(max(0, row - 2), min(SIZE, row + 3)):
                for cc in range(max(0, col - 2), min(SIZE, col + 3)):
                    if self.board[rr][cc] == 0:
                        result.add((rr, cc))
        return sorted(result)

    def _shape(self, row, col, side):
        """(longest run, open ends, promising windows, linked directions, value)."""
        longest = open_ends = windows = linked = 0
        value = 0.0
        for dr, dc in DIRECTIONS:
            negative = positive = 0
            rr, cc = row - dr, col - dc
            while self._inside(rr, cc) and self.board[rr][cc] == side:
                negative += 1
                rr, cc = rr - dr, cc - dc
            openings = int(self._inside(rr, cc) and self.board[rr][cc] == 0)
            rr, cc = row + dr, col + dc
            while self._inside(rr, cc) and self.board[rr][cc] == side:
                positive += 1
                rr, cc = rr + dr, cc + dc
            openings += int(self._inside(rr, cc) and self.board[rr][cc] == 0)
            count = negative + positive + 1
            longest = max(longest, count)
            open_ends += openings
            linked += int(count > 1)
            value += self._run_value(count, openings)
            # Include broken threes/fours in move ordering and geometric features.
            for start in range(-4, 1):
                cells = [(row + k * dr, col + k * dc) for k in range(start, start + 5)]
                if not all(self._inside(r, c) for r, c in cells):
                    continue
                stones = [side if (r, c) == (row, col) else self.board[r][c] for r, c in cells]
                if -side not in stones:
                    own = stones.count(side)
                    if own >= 3:
                        windows += 1
                        value += 2500 if own == 4 else 120 if own == 3 else 0
        return longest, open_ends, windows, linked, value

    @staticmethod
    def _run_value(count, openings):
        if count >= 5:
            return _WIN
        if openings == 0:
            return 0.0
        return {
            4: (0, 18_000, 160_000),
            3: (0, 550, 6500),
            2: (0, 30, 200),
            1: (0, 1, 3),
        }[count][openings]

    def _order_score(self, move, side):
        row, col = move
        attack = self._shape(row, col, side)[4]
        defend = self._shape(row, col, -side)[4]
        return attack + 1.05 * defend + 0.1 * (14 - abs(row - 7) - abs(col - 7))

    def _forced(self, candidates, side):
        wins = [move for move in candidates if self._win_line(*move, side)]
        if wins:
            return wins, "win"
        threats = [move for move in candidates if self._win_line(*move, -side)]
        if not threats:
            return [], None
        # One placement can remove exactly one distinct immediate winning point.
        if len(threats) == 1:
            return threats, "block"
        return [], "lost"

    def _evaluate(self, side):
        score = 0.0
        for row in range(SIZE):
            for col in range(SIZE):
                stone = self.board[row][col]
                if not stone:
                    continue
                signed = 1 if stone == side else -1
                score += signed * 0.05 * (14 - abs(row - 7) - abs(col - 7))
                for dr, dc in DIRECTIONS:
                    prev_r, prev_c = row - dr, col - dc
                    if self._inside(prev_r, prev_c) and self.board[prev_r][prev_c] == stone:
                        continue
                    count = 1
                    openings = int(self._inside(prev_r, prev_c) and self.board[prev_r][prev_c] == 0)
                    rr, cc = row + dr, col + dc
                    while self._inside(rr, cc) and self.board[rr][cc] == stone:
                        count += 1
                        rr, cc = rr + dr, cc + dc
                    openings += int(self._inside(rr, cc) and self.board[rr][cc] == 0)
                    score += signed * self._run_value(count, openings)
        return score

    def _search(self, side, depth, alpha, beta):
        if depth <= 0:
            return self._evaluate(side)
        candidates = self._nearby()
        if not candidates:
            return 0.0
        forced, reason = self._forced(candidates, side)
        if reason == "win":
            return _WIN + depth
        if reason == "lost":
            return -_WIN - depth
        moves = forced or sorted(candidates, key=lambda move: (-self._order_score(move, side), move))[:10]
        best = -inf
        for row, col in moves:
            self.board[row][col] = side
            try:
                value = -self._search(-side, depth - 1, -beta, -alpha)
            finally:
                self.board[row][col] = 0
            best = max(best, value)
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return best

    def rank_moves(self, depth=2, limit=12):
        """Rank local legal candidates using bounded minimax, not a neural net.

        Depth is capped at 3 for a responsive casual opponent. Immediate wins and
        an available defense against a one-move win are returned exclusively, so
        a downstream learned scorer cannot override these tactical constraints.
        """
        if type(depth) is not int or depth < 1:
            raise ValueError("搜索深度必须是正整数")
        if type(limit) is not int or limit < 1:
            raise ValueError("候选数量必须是正整数")
        if self.winner is not None:
            return []
        depth = min(depth, 3)
        candidates = self._nearby()
        forced, reason = self._forced(candidates, self.turn)
        moves = forced or sorted(candidates, key=lambda move: (-self._order_score(move, self.turn), move))[:max(24, min(limit, 48))]
        ranked = []
        for row, col in moves:
            if reason == "win":
                score = _WIN
            else:
                self.board[row][col] = self.turn
                try:
                    score = -self._search(-self.turn, depth - 1, -inf, inf)
                finally:
                    self.board[row][col] = 0
            ranked.append({"move": [row, col], "score": float(score), "forced": bool(forced)})
        ranked.sort(key=lambda item: (-item["score"], -self._order_score(item["move"], self.turn), item["move"]))
        return ranked[:limit]

    def move_features(self, move):
        """Twelve bounded, board-derived features from the side-to-move viewpoint."""
        row, col = self._validate_move(move)
        own = self._shape(row, col, self.turn)
        other = self._shape(row, col, -self.turn)
        nearby_own = nearby_other = 0
        for rr in range(max(0, row - 2), min(SIZE, row + 3)):
            for cc in range(max(0, col - 2), min(SIZE, col + 3)):
                nearby_own += int(self.board[rr][cc] == self.turn)
                nearby_other += int(self.board[rr][cc] == -self.turn)
        occupied = sum(cell != 0 for line in self.board for cell in line)
        values = [
            own[0] / 5, other[0] / 5, own[1] / 8, other[1] / 8,
            own[2] / 20, other[2] / 20, nearby_own / 24, nearby_other / 24,
            1 - max(abs(row - 7), abs(col - 7)) / 7, occupied / (SIZE * SIZE),
            own[3] / 4, other[3] / 4,
        ]
        return [float(max(0.0, min(1.0, value))) for value in values]
