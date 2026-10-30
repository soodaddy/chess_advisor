"""Stockfish로 추천 수를 계산하고 한국어 설명 텍스트를 만든다."""
import shutil
import threading
from dataclasses import dataclass, field

import chess
import chess.engine

STOCKFISH_PATHS = ("/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish")
PIECE_KO = {
    chess.PAWN: "폰", chess.KNIGHT: "나이트", chess.BISHOP: "비숍",
    chess.ROOK: "룩", chess.QUEEN: "퀸", chess.KING: "킹",
}
PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
CENTER = (chess.D4, chess.E4, chess.D5, chess.E5)


@dataclass
class Suggestion:
    move: chess.Move
    text: str
    candidates: list = field(default_factory=list)


def build_board(pieces, turn):
    """AX로 읽은 말 배치로 Board를 만든다. 화면에서 알 수 없는 캐슬링/앙파상은 추정한다.

    캐슬링: 킹과 룩이 처음 자리에 있으면 가능하다고 가정한다(움직였다 돌아온 경우는 구분 못 함).
    앙파상: 알 수 없어서 없다고 본다.
    """
    board = chess.Board(None)
    for sq, piece in pieces.items():
        board.set_piece_at(sq, piece)
    board.turn = turn
    rights = 0
    for color, king_sq, rooks in ((chess.WHITE, chess.E1, (chess.A1, chess.H1)),
                                  (chess.BLACK, chess.E8, (chess.A8, chess.H8))):
        if board.piece_at(king_sq) == chess.Piece(chess.KING, color):
            for rook_sq in rooks:
                if board.piece_at(rook_sq) == chess.Piece(chess.ROOK, color):
                    rights |= chess.BB_SQUARES[rook_sq]
    board.castling_rights = rights
    return board


def eval_text(score, turn):
    s = score.pov(turn)
    mate = s.mate()
    if mate is not None:
        return "%d수 안에 체크메이트 가능" % mate if mate > 0 else "%d수 안에 체크메이트당할 위험" % -mate
    pawns = s.score() / 100
    a = abs(pawns)
    label = "대등" if a < 0.3 else "약간 유리" if a < 1 else "유리" if a < 3 else "크게 유리"
    if label != "대등" and pawns < 0:
        label = label.replace("유리", "불리")
    return "%+.2f (%s)" % (pawns, label)


def reasons(board, move):
    """엔진이 고른 수에 대한 휴리스틱 설명. 평가의 근거는 엔진 점수이고 이 목록은 참고용이다."""
    me = board.turn
    piece = board.piece_at(move.from_square)
    name = PIECE_KO[piece.piece_type]
    out = []
    if board.is_castling(move):
        out.append("킹을 안전하게 하고 룩을 활성화하는 캐슬링")
    if move.promotion:
        out.append("폰이 %s(으)로 승급" % PIECE_KO[move.promotion])
    if board.is_capture(move):
        captured = chess.Piece(chess.PAWN, not me) if board.is_en_passant(move) else board.piece_at(move.to_square)
        if board.is_en_passant(move) or not board.is_attacked_by(not me, move.to_square):
            out.append("방어되지 않는 상대 %s 포획" % PIECE_KO[captured.piece_type])
        else:
            out.append("상대 %s 포획 (재포획 가능성 있음)" % PIECE_KO[captured.piece_type])
    elif board.is_attacked_by(not me, move.from_square):
        out.append("공격받고 있던 %s을(를) 이동" % name)
    home_rank = 0 if me == chess.WHITE else 7
    if (piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank
            and not board.is_capture(move)):
        out.append("%s 전개" % name)
    if move.to_square in CENTER and piece.piece_type in (chess.PAWN, chess.KNIGHT):
        out.append("중앙 장악")
    after = board.copy()
    after.push(move)
    if after.is_checkmate():
        out.append("체크메이트")
    elif after.is_check():
        out.append("상대 킹에 체크")
    threats = []
    for sq in after.attacks(move.to_square):
        target = after.piece_at(sq)
        if target and target.color != me and target.piece_type != chess.KING:
            if not after.is_attacked_by(not me, sq) or PIECE_VALUE[target.piece_type] > PIECE_VALUE[piece.piece_type]:
                threats.append("%s(%s)" % (PIECE_KO[target.piece_type], chess.square_name(sq)))
    if threats and not after.is_check():
        out.append("상대 " + ", ".join(threats[:2]) + " 위협")
    return out


def hanging(board, color):
    """color 쪽에서 공격받는데 방어되지 않는 말 목록 (킹 제외)."""
    out = []
    for sq, piece in board.piece_map().items():
        if piece.color == color and piece.piece_type != chess.KING:
            if board.is_attacked_by(not color, sq) and not board.is_attacked_by(color, sq):
                out.append("%s(%s)" % (PIECE_KO[piece.piece_type], chess.square_name(sq)))
    return out


class Advisor:
    def __init__(self, stockfish_path=None, think_time=0.8, multipv=3):
        path = stockfish_path or shutil.which("stockfish") or next(
            (p for p in STOCKFISH_PATHS if shutil.os.path.exists(p)), None)
        if path is None:
            raise FileNotFoundError("Stockfish를 찾지 못했습니다. `brew install stockfish`")
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self._lock = threading.Lock()
        self.think_time = think_time
        self.multipv = multipv

    def close(self):
        with self._lock:
            self._engine.quit()

    def suggest(self, board):
        """board의 차례 쪽 추천 수. 합법 수가 없으면 None."""
        if not board.is_valid():
            raise ValueError("유효하지 않은 보드입니다: %s" % board.status().name)
        if not any(board.legal_moves):
            return None
        with self._lock:
            infos = self._engine.analyse(board, chess.engine.Limit(time=self.think_time), multipv=self.multipv)
        best = infos[0]
        move = best["pv"][0]
        lines = ["추천 수: %s  (%s → %s)" % (board.san(move), chess.square_name(move.from_square),
                                          chess.square_name(move.to_square)),
                 "평가: " + eval_text(best["score"], board.turn)]
        why = reasons(board, move)
        lines.append("이유: " + (" · ".join(why) if why else "엔진이 가장 높게 평가한 수 (장기적인 위치상 이점)"))
        lines.append("예상 진행: " + board.variation_san(best["pv"][:5]))
        others = ["%s (%s)" % (board.san(i["pv"][0]), eval_text(i["score"], board.turn).split(" ")[0])
                  for i in infos[1:] if i.get("pv")]
        if others:
            lines.append("다른 후보: " + ", ".join(others))
        warn = hanging(board, board.turn)
        if warn:
            lines.append("주의: 방어되지 않은 말 " + ", ".join(warn))
        return Suggestion(move, "\n".join(lines), [i["pv"][0] for i in infos])


if __name__ == "__main__":
    from board.ax_reader import read_position
    pos = read_position()
    if pos is None:
        raise SystemExit("Chess.app 대국 창을 읽지 못했습니다.")
    if pos.turn is None:
        raise SystemExit("진행 중인 대국이 아닙니다: " + pos.title)
    b = build_board(pos.pieces, pos.turn)
    print(pos.title, "|", b.fen())
    advisor = Advisor()
    try:
        s = advisor.suggest(b)
        print(s.text if s else "합법 수가 없습니다.")
    finally:
        advisor.close()
