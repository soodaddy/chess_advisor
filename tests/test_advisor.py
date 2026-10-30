import chess
import pytest

from engine.advisor import Advisor, build_board, eval_text, hanging, reasons


@pytest.fixture(scope="module")
def advisor():
    a = Advisor(think_time=0.2)
    yield a
    a.close()


def test_build_board_castling_rights():
    start = chess.Board()
    b = build_board(start.piece_map(), chess.WHITE)
    assert b.fen() == start.fen().replace(" 0 1", " 0 1")
    moved = chess.Board("r3k2r/8/8/8/8/8/8/4K2R w - - 0 1")
    b = build_board(moved.piece_map(), chess.WHITE)
    assert b.has_kingside_castling_rights(chess.WHITE)
    assert not b.has_queenside_castling_rights(chess.WHITE)
    assert b.has_castling_rights(chess.BLACK)


def test_mate_in_one(advisor):
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    s = advisor.suggest(board)
    assert s.move == chess.Move.from_uci("a1a8")
    assert "체크메이트" in s.text


def test_invalid_board_rejected(advisor):
    with pytest.raises(ValueError):
        advisor.suggest(chess.Board("8/8/8/8/8/8/8/8 w - - 0 1"))


def test_no_legal_moves_returns_none(advisor):
    assert advisor.suggest(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")) is None


def test_reasons_free_capture_and_develop():
    b = chess.Board("4k3/8/8/3q4/8/2N5/8/4K3 w - - 0 1")
    assert any("방어되지 않는 상대 퀸" in r for r in reasons(b, chess.Move.from_uci("c3d5")))
    start = chess.Board()
    assert "나이트 전개" in reasons(start, chess.Move.from_uci("g1f3"))


def test_hanging_and_eval_text():
    b = chess.Board("4k3/8/8/8/8/2n5/8/R3K3 w - - 0 1")
    assert hanging(chess.Board("4k3/8/8/3r4/8/8/3N4/7K w - - 0 1"), chess.WHITE) == ["나이트(d2)"]
    assert hanging(b, chess.WHITE) == []
    assert eval_text(chess.engine.PovScore(chess.engine.Cp(250), chess.WHITE), chess.BLACK) == "-2.50 (불리)"
