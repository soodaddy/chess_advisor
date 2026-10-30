import chess
import pytest

from board.ax_reader import parse_description, parse_turn
from board.geometry import load_corners, save_corners, square_center


def test_parse_korean_piece():
    assert parse_description("화이트 룩, a1") == (chess.A1, chess.Piece(chess.ROOK, chess.WHITE))
    assert parse_description("블랙 나이트, g8") == (chess.G8, chess.Piece(chess.KNIGHT, chess.BLACK))


def test_parse_english_piece_and_empty():
    assert parse_description("White Queen, d1") == (chess.D1, chess.Piece(chess.QUEEN, chess.WHITE))
    assert parse_description("e4") == (chess.E4, None)


@pytest.mark.parametrize("desc", [None, "", "화이트 유니콘, a1", "화이트 룩, z9"])
def test_parse_invalid(desc):
    assert parse_description(desc) is None


def test_parse_turn():
    assert parse_turn("MBC 체스 게임 | 플레이어 - 컴퓨터   (화이트 차례)") == chess.WHITE
    assert parse_turn("게임 | 플레이어 - 컴퓨터   (블랙 차례)") == chess.BLACK
    assert parse_turn("게임 | 플레이어 - 컴퓨터   (블랙 승리!)") is None


CORNERS = [[195.6, 157.0], [536.2, 157.1], [577.2, 492.0], [154.6, 492.0]]


def test_square_center_order_and_corners():
    a8, h8 = square_center(CORNERS, chess.A8), square_center(CORNERS, chess.H8)
    a1, h1 = square_center(CORNERS, chess.A1), square_center(CORNERS, chess.H1)
    # 백이 아래쪽: 8랭크가 위, a파일이 왼쪽. 가까운 행(1랭크)이 더 넓다.
    assert a8[1] < a1[1] and a8[0] < h8[0] and a1[0] < h1[0]
    assert (h1[0] - a1[0]) > (h8[0] - a8[0])
    assert CORNERS[0][0] < a8[0] < CORNERS[1][0] and CORNERS[0][1] < a8[1]


def test_save_and_load_corners(tmp_path):
    path = tmp_path / "cal.json"
    assert load_corners((800, 600), path) is None
    save_corners((731.6, 581.2), CORNERS, path)
    assert load_corners((732, 581), path) == CORNERS
    assert load_corners((800, 600), path) is None


def _win(number, x, y, w, h, layer=0):
    return {"kCGWindowNumber": number, "kCGWindowLayer": layer,
            "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


def test_topmost_at_center():
    from board.ax_reader import is_topmost_at_center
    chess_win = _win(1, 5, 311, 732, 581)
    covering = _win(2, 0, 0, 1000, 900)
    overlay = _win(3, 5, 311, 732, 581, layer=25)   # 우리 오버레이(layer 25)는 무시된다
    assert is_topmost_at_center([overlay, chess_win, covering], 1) is True
    assert is_topmost_at_center([covering, chess_win], 1) is False
    assert is_topmost_at_center([covering], 1) is False   # 목록에 없는 창
    side = _win(4, 900, 0, 500, 500)                       # 중심점을 안 덮는 창은 상관없다
    assert is_topmost_at_center([side, chess_win], 1) is True


def test_square_quad_contains_center_and_follows_perspective():
    from board.geometry import square_quad
    quad = square_quad(CORNERS, chess.E4)
    cx, cy = square_center(CORNERS, chess.E4)
    assert min(x for x, _ in quad) < cx < max(x for x, _ in quad)
    assert min(y for _, y in quad) < cy < max(y for _, y in quad)
    # 좌상, 우상, 우하, 좌하 순서이고 가까운 쪽(아래 변)이 더 넓다.
    assert quad[0][1] < quad[3][1] and quad[0][0] < quad[1][0]
    assert quad[2][0] - quad[3][0] > quad[1][0] - quad[0][0]
    # 이웃한 칸과 꼭짓점을 공유한다 (e4의 우측 변 = f4의 좌측 변).
    f4 = square_quad(CORNERS, chess.F4)
    assert quad[1] == pytest.approx(f4[0]) and quad[2] == pytest.approx(f4[3])
