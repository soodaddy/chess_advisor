import chess
import numpy as np

from board.calibrate import fit_corners, scan_window, unoccluded_empty_squares, verify
from board.geometry import apply_homography, grid_homography, square_center

TRUE_CORNERS = [[196.0, 157.0], [536.0, 157.0], [577.0, 492.0], [155.0, 492.0]]
WINDOW = (5.0, 311.0, 732.0, 581.0)


def fake_chess_app(pieces, corners=TRUE_CORNERS, body_height=0.9):
    """화면 절대좌표 -> (칸, 말|None). 말이 있는 칸의 몸통이 뒤쪽 칸(화면 위쪽)을 가리는 것도 흉내 낸다."""
    h_inv = np.linalg.inv(grid_homography(corners))

    def hit(x, y):
        u, v = apply_homography(h_inv, [(x - WINDOW[0], y - WINDOW[1])])[0]
        if not (0 <= u < 8 and 0 <= v < 8):
            return None
        f, r = int(u), 7 - int(v)
        # 바로 앞(아래쪽) 칸에 말이 있고 이 칸의 아래 body_height 부분이면 그 말이 가린다.
        if r > 0 and chess.square(f, r - 1) in pieces and (v - int(v)) > 1 - body_height:
            return chess.square(f, r - 1), pieces[chess.square(f, r - 1)]
        sq = chess.square(f, r)
        return sq, pieces.get(sq)
    return hit


def start_pieces():
    return chess.Board().piece_map()


def test_fit_recovers_corners_from_synthetic_hits():
    hit = fake_chess_app(start_pieces())
    empty, outside = scan_window(hit, WINDOW)
    corners = fit_corners(empty, outside)
    assert corners is not None
    err = np.abs(np.array(corners) - np.array(TRUE_CORNERS)).max()
    assert err < 6, err  # 격자 8pt 간격 샘플링 한계 안


def test_fit_without_outside_points_still_returns_plausible_result():
    hit = fake_chess_app(start_pieces())
    empty, _ = scan_window(hit, WINDOW)
    assert fit_corners(empty) is not None


def test_fit_refuses_when_too_few_empty_squares():
    hit = fake_chess_app(chess.Board().piece_map())
    empty, outside = scan_window(hit, WINDOW)
    few = {s: p for s, p in list(empty.items())[:5]}
    assert fit_corners(few, outside) is None


def test_verify_accepts_good_and_rejects_bad_corners():
    pieces = start_pieces()
    hit = fake_chess_app(pieces)
    assert verify(hit, WINDOW, TRUE_CORNERS, pieces) is True
    shifted = [[x + 60, y] for x, y in TRUE_CORNERS]   # 보드가 옆으로 밀렸다고 가정
    assert verify(hit, WINDOW, shifted, pieces) is False


def test_verify_inconclusive_when_board_is_crowded():
    full = {sq: chess.Piece(chess.PAWN, chess.WHITE) for sq in chess.SQUARES}
    assert verify(lambda x, y: None, WINDOW, TRUE_CORNERS, full) is None


def test_unoccluded_squares_skip_occluded_cells():
    pieces = {chess.E2: chess.Piece(chess.PAWN, chess.WHITE)}
    testable = unoccluded_empty_squares(pieces)
    assert chess.E3 not in testable and chess.E4 not in testable   # e2 폰이 가린다
    assert chess.E2 not in testable                                # 말이 있는 칸
    assert chess.A5 in testable
    cx, cy = square_center(TRUE_CORNERS, chess.A5)
    assert 150 < cx < 300 and 150 < cy < 500
