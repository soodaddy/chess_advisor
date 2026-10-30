"""Chess.app의 히트 테스트(화면 좌표 → 칸)로 보드 모서리를 자동 보정한다.

말이 있는 칸은 말 몸통이 뒤쪽 칸까지 가리므로, 빈 칸의 히트 영역만으로 호모그래피를 맞춘다.
"""
import chess
import cv2
import numpy as np
from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCopyElementAtPosition
from scipy.optimize import least_squares

from board.ax_reader import chess_app_element, parse_description
from board.geometry import (GRID_CORNERS, apply_homography, grid_homography, load_corners, save_corners,
                            square_center)

SCAN_STEP = 8            # pt. 칸 한 변이 약 35~50pt라 충분히 촘촘하다.
MIN_EMPTY_SQUARES = 10   # 적합에 필요한 최소 빈 칸 수
MIN_POINTS_PER_SQUARE = 4
MIN_IN_CELL_FRACTION = 0.95
VERIFY_SQUARES = 12
VERIFY_MIN_MATCH = 0.75
PRIOR_WEIGHT = 0.1       # 칸 중앙으로 당기는 약한 사전 분포 (해가 한 점으로 정해지게)
MAX_FIT_POINTS = 2500


def hit_square(app, x, y):
    """화면 (x, y)에서 Chess.app이 응답하는 (chess.Square, Piece|None). 칸이 아니면 None."""
    err, element = AXUIElementCopyElementAtPosition(app, x, y, None)
    if err != 0 or element is None:
        return None
    err, desc = AXUIElementCopyAttributeValue(element, "AXDescription", None)
    return parse_description(desc) if err == 0 else None


def scan_window(hit, window, step=SCAN_STEP):
    """창 전체를 훑어 ({빈 칸: [창 기준 좌표, ...]}, [칸이 아닌 곳의 좌표, ...])를 만든다.

    hit(x, y)는 화면 절대좌표를 받는다. 말이 있는 칸의 점은 말 몸통 때문에 쓰지 않는다.
    """
    wx, wy, ww, wh = window
    empty, outside = {}, []
    for ry in range(step // 2, int(wh), step):
        for rx in range(step // 2, int(ww), step):
            found = hit(wx + rx, wy + ry)
            if found is None:
                outside.append((rx, ry))
            elif found[1] is None:
                empty.setdefault(found[0], []).append((rx, ry))
    return empty, outside


def _cells(points_by_square):
    pts, cells = [], []
    for square, plist in points_by_square.items():
        for p in plist:
            pts.append(p)
            cells.append((chess.square_file(square), 7 - chess.square_rank(square)))
    return np.array(pts, dtype=float), np.array(cells, dtype=float)


def _grid_coords(corners, pts):
    return apply_homography(np.linalg.inv(grid_homography(corners)), pts)


def _is_sane(corners):
    quad = np.asarray(corners, dtype=np.float32)
    return bool(cv2.isContourConvex(quad) and cv2.contourArea(quad) > 100.0
                and quad[0][0] < quad[1][0] and quad[3][0] < quad[2][0]
                and quad[0][1] < quad[3][1] and quad[1][1] < quad[2][1])


def fit_corners(points_by_square, outside=()):
    """보드 모서리(좌상, 우상, 우하, 좌하)를 구한다. 데이터가 부족하거나 안 맞으면 None.

    빈 칸의 점은 자기 칸 안에, 칸이 아닌 곳(outside)의 점은 보드 밖에 있어야 한다는 조건으로 맞춘다.
    """
    usable = {s: p for s, p in points_by_square.items() if len(p) >= MIN_POINTS_PER_SQUARE}
    files = {chess.square_file(s) for s in usable}
    ranks = {chess.square_rank(s) for s in usable}
    if len(usable) < MIN_EMPTY_SQUARES or len(files) < 5 or len(ranks) < 3:
        return None
    # 초기값: 칸별 점들의 무게중심으로 호모그래피를 구한다.
    src = np.array([[chess.square_file(s) + 0.5, 7 - chess.square_rank(s) + 0.5] for s in usable], dtype=np.float32)
    dst = np.array([np.mean(p, axis=0) for p in usable.values()], dtype=np.float32)
    h0, _ = cv2.findHomography(src, dst, cv2.RANSAC, 8.0)
    if h0 is None:
        return None
    start = apply_homography(h0, GRID_CORNERS)

    pts, cells = _cells(usable)
    if len(pts) > MAX_FIT_POINTS:
        keep = np.linspace(0, len(pts) - 1, MAX_FIT_POINTS).astype(int)
        fit_pts, fit_cells = pts[keep], cells[keep]
    else:
        fit_pts, fit_cells = pts, cells

    # 보드 가장자리 근처의 바깥 점만 쓴다 (초기 추정 기준 격자 좌표로 1.5칸 이내).
    outside = np.asarray(outside, dtype=float).reshape(-1, 2)
    if len(outside):
        g0 = _grid_coords(start, outside)
        outside = outside[np.all((g0 > -1.5) & (g0 < 9.5), axis=1)]
    if len(outside) > MAX_FIT_POINTS:
        outside = outside[np.linspace(0, len(outside) - 1, MAX_FIT_POINTS).astype(int)]

    def residuals(params):
        corners = params.reshape(4, 2)
        try:
            g = _grid_coords(corners, fit_pts)
            go = _grid_coords(corners, outside) if len(outside) else np.empty((0, 2))
        except np.linalg.LinAlgError:
            return np.full(4 * len(fit_pts) + len(outside), 1e3)
        lo, hi = fit_cells, fit_cells + 1
        off_cell = np.maximum(0, np.maximum(lo - g, g - hi))        # 자기 칸 밖으로 벗어난 만큼
        centered = PRIOR_WEIGHT * (g - (fit_cells + 0.5))           # 칸 중앙으로 약하게
        # 칸이 아닌 점이 보드 안으로 파고든 깊이 (가장 가까운 경계까지의 거리)
        depth = np.where(np.all((go > 0) & (go < 8), axis=1), np.minimum(go, 8 - go).min(axis=1), 0.0)
        return np.concatenate([5 * off_cell.ravel(), centered.ravel(), 5 * depth])

    result = least_squares(residuals, start.ravel(), method="lm")
    corners = result.x.reshape(4, 2)
    if not _is_sane(corners):
        return None
    g = _grid_coords(corners, pts)
    inside = np.all((g >= cells - 0.15) & (g <= cells + 1.15), axis=1)
    if inside.mean() < MIN_IN_CELL_FRACTION:
        return None
    return [[float(x), float(y)] for x, y in corners]


def unoccluded_empty_squares(pieces):
    """말에 가려지지 않았을 빈 칸. 앞쪽(백 방향) 두 칸과 양옆 앞 칸에 말이 없는 칸만 고른다."""
    out = []
    for square in chess.SQUARES:
        if square in pieces:
            continue
        f, r = chess.square_file(square), chess.square_rank(square)
        front = [(f, r - 1), (f, r - 2), (f - 1, r - 1), (f + 1, r - 1)]
        if any(0 <= ff < 8 and 0 <= rr < 8 and chess.square(ff, rr) in pieces for ff, rr in front):
            continue
        out.append(square)
    return out


def verify(hit, window, corners, pieces, count=VERIFY_SQUARES):
    """저장된 보정이 아직 맞는지 빈 칸 중심을 히트 테스트로 확인한다.

    True/False, 확인할 칸이 부족하면 None(판단 불가).
    """
    candidates = unoccluded_empty_squares(pieces)
    if len(candidates) < 4:
        return None
    step = max(1, len(candidates) // count)
    wx, wy = window[:2]
    matched = tested = 0
    for square in candidates[::step][:count]:
        cx, cy = square_center(corners, square)
        found = hit(wx + cx, wy + cy)
        tested += 1
        matched += found is not None and found[0] == square
    return matched / tested >= VERIFY_MIN_MATCH


class Calibrator:
    """창 크기별 보정을 캐시하고, 안 맞으면 다시 스캔해서 보정한다."""

    def __init__(self, calibration_path=None):
        self.path = calibration_path

    def _hit(self):
        app = chess_app_element()
        return None if app is None else (lambda x, y: hit_square(app, x, y))

    def is_valid(self, window, corners, pieces):
        """빠른 점검(수십 번의 히트 테스트). 판단 불가면 유효로 본다."""
        hit = self._hit()
        return hit is not None and verify(hit, window, corners, pieces) is not False

    def ensure(self, window, pieces):
        """창에 맞는 보정 모서리를 돌려준다(스캔에 수 초 걸릴 수 있음). 실패하면 None."""
        hit = self._hit()
        if hit is None:
            return None
        kwargs = {} if self.path is None else {"path": self.path}
        size = window[2:]
        cached = load_corners(size, **kwargs)
        if cached is not None and verify(hit, window, cached, pieces) is not False:
            return cached
        corners = fit_corners(*scan_window(hit, window))
        if corners is None:
            return None
        save_corners(size, corners, **kwargs)
        return corners


if __name__ == "__main__":
    import time

    from board.ax_reader import read_position

    pos = read_position()
    if pos is None:
        raise SystemExit("Chess.app 대국 창을 읽지 못했습니다.")
    app = chess_app_element()
    t = time.time()
    found = fit_corners(*scan_window(lambda x, y: hit_square(app, x, y), pos.window))
    print("창", pos.window, "| %.1fs" % (time.time() - t))
    print("모서리(좌상, 우상, 우하, 좌하):", None if found is None else [[round(v, 1) for v in c] for c in found])
