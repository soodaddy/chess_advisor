import chess
import cv2
import numpy as np

from board.geometry import square_quad
from board.silhouette import covers_cell, hit_silhouette, outline_for_square, piece_outline

WINDOW = (0.0, 0.0, 400.0, 300.0)       # pt
SCALE = 2
CORNERS = [[60.0, 40.0], [340.0, 40.0], [360.0, 280.0], [40.0, 280.0]]
SQUARE = chess.D3


def make_scene():
    """잡음 있는 보드 바닥 위에 밝은 말(밑동 + 몸통 + 머리) 하나를 그린 합성 장면과 그 정답 마스크."""
    rng = np.random.default_rng(0)
    base = np.array([105, 125, 150], np.float32)
    img = np.clip(base + rng.normal(0, 6, (int(WINDOW[3] * SCALE), int(WINDOW[2] * SCALE), 3)), 0, 255).astype(np.uint8)
    quad = np.array(square_quad(CORNERS, SQUARE)) * SCALE
    cx, cy = quad.mean(axis=0)
    cell_w = quad[:, 0].max() - quad[:, 0].min()
    piece = np.zeros(img.shape[:2], np.uint8)
    cv2.ellipse(piece, (int(cx), int(cy)), (int(0.28 * cell_w), int(0.13 * cell_w)), 0, 0, 360, 1, -1)
    cv2.fillPoly(piece, [np.array([[cx - 0.2 * cell_w, cy], [cx + 0.2 * cell_w, cy],
                                   [cx + 0.1 * cell_w, cy - 1.4 * cell_w], [cx - 0.1 * cell_w, cy - 1.4 * cell_w]], np.int32)], 1)
    cv2.circle(piece, (int(cx), int(cy - 1.55 * cell_w)), int(0.16 * cell_w), 1, -1)
    img[piece > 0] = (225, 228, 232)
    return img, piece, quad


def fake_hit(piece_mask, quad):
    """히트 테스트 흉내: 칸 사각형과 말 실루엣이 모두 이 칸으로 응답한다(실제 Chess.app과 같다)."""
    def hit(x, y):
        px, py = int(x * SCALE), int(y * SCALE)
        in_piece = 0 <= py < piece_mask.shape[0] and 0 <= px < piece_mask.shape[1] and piece_mask[py, px] > 0
        in_cell = cv2.pointPolygonTest(quad.astype(np.float32), (float(px), float(py)), False) >= 0
        return (SQUARE, chess.Piece(chess.PAWN, chess.WHITE)) if in_piece or in_cell else None
    return hit


def test_outline_follows_piece_not_whole_cell():
    img, piece, quad = make_scene()
    poly = piece_outline(img, WINDOW, CORNERS, SQUARE, fake_hit(piece, quad))
    assert poly is not None
    found = np.zeros(piece.shape, np.uint8)
    cv2.fillPoly(found, [(np.array(poly) * SCALE).astype(np.int32)], 1)
    iou = (found & piece).sum() / max(1, (found | piece).sum())
    assert iou > 0.75, iou
    cell = np.zeros(piece.shape, np.uint8)
    cv2.fillPoly(cell, [quad.astype(np.int32)], 1)
    assert (found & cell & ~piece.astype(bool)).sum() < 0.25 * cell.sum()   # 칸 바닥을 통째로 감싸지 않는다


def test_outline_none_when_square_never_responds():
    img, piece, quad = make_scene()
    assert piece_outline(img, WINDOW, CORNERS, SQUARE, lambda x, y: None) is None


def _iou(poly, piece):
    found = np.zeros(piece.shape, np.uint8)
    cv2.fillPoly(found, [(np.array(poly) * SCALE).astype(np.int32)], 1)
    return (found & piece).sum() / max(1, (found | piece).sum())


def test_hit_silhouette_works_without_any_screenshot():
    _, piece, quad = make_scene()
    poly = hit_silhouette(WINDOW, CORNERS, SQUARE, fake_hit(piece, quad))
    assert poly is not None
    assert _iou(poly, piece) > 0.5


def test_covers_cell_detects_cell_shaped_result():
    quad = square_quad(CORNERS, SQUARE)
    assert covers_cell(quad, quad) is True
    cx, cy = np.mean(quad, axis=0)
    small = [(cx - 6, cy - 30), (cx + 6, cy - 30), (cx + 10, cy), (cx - 10, cy)]
    assert covers_cell(small, quad) is False


def test_outline_prefers_screenshot_when_allowed():
    img, piece, quad = make_scene()
    poly, note = outline_for_square(WINDOW, CORNERS, SQUARE, hit=fake_hit(piece, quad),
                                    grab=lambda: img, capture_allowed=lambda: True)
    assert note is None and _iou(poly, piece) > 0.75


def test_outline_falls_back_to_hit_silhouette_without_permission():
    img, piece, quad = make_scene()
    grabbed = []
    poly, note = outline_for_square(WINDOW, CORNERS, SQUARE, hit=fake_hit(piece, quad),
                                    grab=lambda: grabbed.append(1) or img, capture_allowed=lambda: False)
    assert poly is not None and "권한" in note
    assert not grabbed                     # 권한이 없으면 캡처를 시도하지 않는다


def test_outline_falls_back_when_capture_fails():
    _, piece, quad = make_scene()
    poly, note = outline_for_square(WINDOW, CORNERS, SQUARE, hit=fake_hit(piece, quad),
                                    grab=lambda: None, capture_allowed=lambda: True)
    assert poly is not None and note


def test_outline_returns_none_with_message_when_everything_fails():
    poly, note = outline_for_square(WINDOW, CORNERS, SQUARE, hit=lambda x, y: None,
                                    grab=lambda: None, capture_allowed=lambda: False)
    assert poly is None and "출발 칸" in note
