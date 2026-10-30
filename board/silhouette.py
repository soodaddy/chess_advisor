"""이동할 말의 실루엣 윤곽을 구한다.

히트 테스트 영역(칸 사각형 + 말 몸통)은 말이 있을 범위를 알려주는 사전 정보로만 쓰고,
정확한 경계는 창 스크린샷에서 GrabCut으로 분할한다.
"""
import math

import cv2
import numpy as np

from board.geometry import square_quad

HIT_STEP = 3            # pt. 히트 테스트 간격 (경계는 GrabCut이 픽셀 단위로 다듬는다)
MAX_PIECE_HEIGHT = 165  # pt. 칸 위로 말이 솟을 수 있는 최대 높이 (킹/퀸 기준 여유 포함)
GRABCUT_ITERATIONS = 5
MIN_AREA_FRACTION = 0.15   # 칸 면적 대비 이보다 작은 결과는 실패로 본다


def _roi(quad, window_size):
    """말이 차지할 수 있는 창 기준 사각 영역 (x0, y0, x1, y1), pt."""
    xs, ys = quad[:, 0], quad[:, 1]
    x0 = max(0, int(math.floor(xs.min())) - 24)
    x1 = min(int(window_size[0]), int(math.ceil(xs.max())) + 24)
    y0 = max(0, int(math.floor(ys.min())) - MAX_PIECE_HEIGHT)
    y1 = min(int(window_size[1]), int(math.ceil(ys.max())) + 10)
    return x0, y0, x1, y1


def hit_mask(hit, window, square, roi, step=HIT_STEP):
    """roi 안에서 해당 칸이 응답하는 점들의 불리언 격자와 그 간격 (창 기준 pt)."""
    wx, wy = window[:2]
    x0, y0, x1, y1 = roi
    xs, ys = range(x0, x1, step), range(y0, y1, step)
    mask = np.zeros((len(ys), len(xs)), np.uint8)
    for iy, ry in enumerate(ys):
        for ix, rx in enumerate(xs):
            found = hit(wx + rx, wy + ry)
            if found is not None and found[0] == square:
                mask[iy, ix] = 255
    return mask


def piece_outline(image, window, corners, square, hit):
    """image(창 스크린샷)에서 square의 말 윤곽 다각형을 창 기준 좌표(pt)로 돌려준다. 실패하면 None."""
    scale = image.shape[1] / window[2]
    quad = np.array(square_quad(corners, square))
    roi = _roi(quad, window[2:])
    x0, y0, x1, y1 = roi
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    grid = hit_mask(hit, window, square, roi)
    if not grid.any():
        return None

    # 영상 좌표(px)의 ROI 안에서 작업한다.
    px0, py0 = int(x0 * scale), int(y0 * scale)
    px1, py1 = min(image.shape[1], int(x1 * scale)), min(image.shape[0], int(y1 * scale))
    crop = np.ascontiguousarray(image[py0:py1, px0:px1, :3])
    h, w = crop.shape[:2]
    hit_px = cv2.resize(grid, (w, h), interpolation=cv2.INTER_NEAREST) > 0
    hit_px = cv2.morphologyEx(hit_px.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool)

    quad_px = ((quad * scale) - np.array([px0, py0])).astype(np.int32)
    cell = np.zeros((h, w), np.uint8)
    cv2.fillPoly(cell, [quad_px], 1)
    cell_wide = cv2.dilate(cell, np.ones((13, 13), np.uint8)).astype(bool)

    cx, cy = quad_px.mean(axis=0)
    cell_w = quad_px[:, 0].max() - quad_px[:, 0].min()
    cell_h = quad_px[:, 1].max() - quad_px[:, 1].min()
    mask = np.full((h, w), cv2.GC_BGD, np.uint8)
    band = cv2.dilate(hit_px.astype(np.uint8), np.ones((11, 11), np.uint8)).astype(bool)
    mask[band] = cv2.GC_PR_BGD
    mask[hit_px & ~cell_wide] = cv2.GC_PR_FGD      # 칸 위로 솟은 부분은 아마 말
    # 칸 안쪽은 말 밑동이 아니면 보드 바닥이다. 아마 배경에서 시작해 색으로 말 부분을 되찾게 한다.
    inside = hit_px & cell_wide
    mask[inside] = cv2.GC_PR_BGD
    xs = np.arange(w)[None, :]
    ys = np.arange(h)[:, None]
    too_wide = np.abs(xs - cx) > 0.46 * cell_w     # 밑동은 칸 폭의 92% 안쪽
    too_front = ys > cy + 0.62 * cell_h            # 칸 앞쪽(아래) 가장자리는 바닥
    mask[inside & (too_wide | too_front)] = cv2.GC_BGD
    body = cv2.erode((hit_px & ~cell_wide).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    mask[body] = cv2.GC_FGD                       # 칸 위로 솟은 몸통은 확실히 말
    core = np.zeros((h, w), np.uint8)
    cv2.circle(core, (int(cx), int(cy)), max(3, int(0.15 * cell_w)), 1, -1)
    mask[core.astype(bool) & hit_px] = cv2.GC_FGD  # 칸 중앙(말 밑동)은 확실히 말

    try:
        cv2.grabCut(crop, mask, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                    GRABCUT_ITERATIONS, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    # 칸 중앙을 포함하는 가장 큰 덩어리를 말로 본다.
    contours = [c for c in contours if cv2.pointPolygonTest(c, (float(cx), float(cy)), False) >= 0] or contours
    biggest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(biggest) < MIN_AREA_FRACTION * cv2.contourArea(quad_px):
        return None
    poly = cv2.approxPolyDP(biggest, 1.5, True).reshape(-1, 2).astype(float)
    return [((px + px0) / scale, (py + py0) / scale) for px, py in poly]


SIL_STEP = 2            # pt. 이미지 없이 히트 영역만 쓰므로 더 촘촘히 훑는다
SIL_RASTER = 4          # px per pt
CELL_COVERED_LIMIT = 0.85   # 윤곽이 칸 면적의 이만큼 이상을 덮으면 칸 사각형이 섞인 실패로 본다


def covers_cell(polygon, quad):
    """polygon이 칸 사각형 면적의 CELL_COVERED_LIMIT 이상을 덮는가 (GrabCut이 칸 바닥까지 가져간 경우)."""
    pts = np.vstack([np.asarray(polygon), np.asarray(quad)])
    ox, oy = pts.min(axis=0) - 2
    size = (int(pts[:, 0].max() - ox + 4) * 2, int(pts[:, 1].max() - oy + 4) * 2)
    cell = np.zeros(size[::-1], np.uint8)
    shape = np.zeros_like(cell)
    cv2.fillPoly(cell, [((np.asarray(quad) - [ox, oy]) * 2).astype(np.int32)], 1)
    cv2.fillPoly(shape, [((np.asarray(polygon) - [ox, oy]) * 2).astype(np.int32)], 1)
    return bool((cell & shape).sum() >= CELL_COVERED_LIMIT * cell.sum())


def hit_silhouette(window, corners, square, hit):
    """화면 캡처 없이 만든 대략적인 말 윤곽(창 기준 pt 다각형). 못 만들면 None.

    히트 영역에서 칸 사각형을 뺀 부분은 말 몸통의 실제 실루엣이다. 칸 안쪽의 밑동은 보이지 않으므로
    몸통 아래쪽 폭에서 밑동 타원으로 이어지는 사다리꼴로 메운다.
    """
    quad = np.array(square_quad(corners, square))
    x0, y0, x1, y1 = roi = _roi(quad, window[2:])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    grid = hit_mask(hit, window, square, roi, step=SIL_STEP)
    if not grid.any():
        return None
    R, step = SIL_RASTER, SIL_STEP
    # 표본 하나는 step x step pt 영역을 대표한다 (표본점이 그 영역의 중앙).
    ox, oy = x0 - step / 2, y0 - step / 2
    big = cv2.resize(grid, (grid.shape[1] * step * R, grid.shape[0] * step * R), interpolation=cv2.INTER_NEAREST)
    big = (cv2.GaussianBlur(big, (0, 0), R * 1.0) > 127).astype(np.uint8)

    def px(points):
        return ((np.asarray(points, dtype=float) - [ox, oy]) * R).astype(np.int32)

    cell = np.zeros_like(big)
    cv2.fillPoly(cell, [px(quad)], 1)
    cell = cv2.dilate(cell, np.ones((3 * R + 1, 3 * R + 1), np.uint8))   # 보정 오차 몇 pt 여유
    upper = (big & ~cell.astype(bool)).astype(np.uint8)
    # 칸 가장자리에 남은 얇은 조각은 몸통이 아니다. 몸통보다 얇은 것을 지운다.
    upper = cv2.morphologyEx(upper, cv2.MORPH_OPEN, np.ones((5 * R, 5 * R), np.uint8))
    if not upper.any():
        return None

    # 몸통이 칸 뒤쪽 경계를 지나는 높이 부근의 폭과 중심
    top_y = (quad[:, 1].min() - oy) * R
    rows = np.where(upper.any(axis=1))[0]
    near = [r for r in rows if top_y - 16 * R <= r <= top_y - 6 * R]
    band = near or list(rows[-6 * R:])
    xs = np.where(upper[band].any(axis=0))[0]
    xj0, xj1, yj = xs.min(), xs.max(), max(band)

    cx, cy = px(quad.mean(axis=0))
    cell_w = (quad[:, 0].max() - quad[:, 0].min()) * R
    cell_h = (quad[:, 1].max() - quad[:, 1].min()) * R
    rx = 0.30 * cell_w
    ry = rx * cell_h / cell_w
    canvas = upper.astype(np.uint8)
    cv2.ellipse(canvas, (int(cx), int(cy)), (int(rx), int(ry)), 0, 0, 360, 1, -1)
    cv2.fillPoly(canvas, [np.array([[xj0, yj], [xj1, yj], [cx + rx, cy], [cx - rx, cy]], np.int32)], 1)
    canvas = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, np.ones((R * 2 + 1, R * 2 + 1), np.uint8))
    contours, _ = cv2.findContours(canvas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    biggest = max(contours, key=cv2.contourArea)
    poly = cv2.approxPolyDP(biggest, 0.8 * R, True).reshape(-1, 2).astype(float)
    return [(x / R + ox, y / R + oy) for x, y in poly]


def screen_capture_allowed():
    """이 프로세스에 화면 기록 권한이 있는가."""
    import Quartz
    try:
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except AttributeError:
        return True   # 확인할 수 없는 OS에서는 시도해 본다


def grab_window_image():
    """Chess 창 스크린샷(BGR)을 돌려준다. 실패하면 None."""
    import os
    import tempfile

    from capture.window import capture

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        return cv2.imread(path) if capture(path) else None
    except Exception:
        return None
    finally:
        os.unlink(path)


def outline_for_square(window, corners, square, hit=None, grab=grab_window_image, capture_allowed=screen_capture_allowed):
    """이동할 말의 윤곽을 (다각형, 안내 문구)로 돌려준다. 다각형은 창 기준 pt 좌표.

    1) 화면 기록 권한이 있으면 스크린샷을 GrabCut으로 분할한다 (정밀). 안내 문구는 None.
    2) 안 되면 히트 테스트 영역만으로 만든 간이 윤곽을 쓴다.
    3) 그것도 안 되면 (None, 문구): 호출한 쪽이 출발 칸 사각형으로 대신한다.
    """
    if hit is None:
        from board.ax_reader import chess_app_element
        from board.calibrate import hit_square

        app = chess_app_element()
        if app is None:
            return None, "Chess.app을 찾지 못해 말 윤곽을 만들지 못했습니다."
        hit = lambda x, y: hit_square(app, x, y)

    quad = square_quad(corners, square)
    reason = None
    if not capture_allowed():
        reason = "화면 기록 권한이 없어 간이 윤곽으로 표시했습니다."
    else:
        try:
            image = grab()
            polygon = None if image is None else piece_outline(image, window, corners, square, hit)
        except Exception:
            polygon = None
        if polygon is not None and not covers_cell(polygon, quad):
            return polygon, None
        reason = "화면 분할이 잘 안 돼 간이 윤곽으로 표시했습니다."
    try:
        polygon = hit_silhouette(window, corners, square, hit)
    except Exception:
        polygon = None
    if polygon is not None:
        return polygon, reason
    return None, "말 윤곽을 만들지 못해 출발 칸을 표시했습니다."
