"""보드 모서리 보정값으로 칸의 화면 좌표(창 기준 상대좌표, pt)를 계산한다."""
import json
from pathlib import Path

import chess
import numpy as np

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"
# 격자 좌표계: u는 a~h, v는 8~1 (백이 아래쪽). 모서리 순서는 좌상, 우상, 우하, 좌하.
GRID_CORNERS = np.array([[0, 0], [8, 0], [8, 8], [0, 8]], dtype=float)


def grid_homography(corners):
    """격자 좌표(0..8)에서 창 기준 화면 좌표로 가는 3x3 호모그래피."""
    a, b = [], []
    for (u, v), (x, y) in zip(GRID_CORNERS, corners):
        a.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        b.append(x)
        a.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        b.append(y)
    h = np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float))
    return np.append(h, 1.0).reshape(3, 3)


def apply_homography(h, points):
    """(N, 2) 점들에 호모그래피를 적용한다."""
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    out = np.c_[pts, np.ones(len(pts))] @ h.T
    return out[:, :2] / out[:, 2:3]


def square_center(corners, square):
    """칸 중심의 창 기준 좌표 (x, y)."""
    u = chess.square_file(square) + 0.5
    v = 7 - chess.square_rank(square) + 0.5
    x, y = apply_homography(grid_homography(corners), [(u, v)])[0]
    return float(x), float(y)


def square_quad(corners, square):
    """칸의 네 꼭짓점(좌상, 우상, 우하, 좌하)의 창 기준 좌표. 원근 때문에 사다리꼴이다."""
    u = chess.square_file(square)
    v = 7 - chess.square_rank(square)
    pts = apply_homography(grid_homography(corners), [(u, v), (u + 1, v), (u + 1, v + 1), (u, v + 1)])
    return [(float(x), float(y)) for x, y in pts]


def window_key(window_size):
    return "%dx%d" % (round(window_size[0]), round(window_size[1]))


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}


def load_corners(window_size, path=CALIBRATION_PATH):
    """창 크기(w, h)에 저장된 보정 모서리 4점. 없으면 None."""
    entry = _load(path).get(window_key(window_size))
    return None if entry is None else entry["corners"]


def save_corners(window_size, corners, path=CALIBRATION_PATH, method="auto"):
    data = _load(path)
    data[window_key(window_size)] = {
        "method": method,
        "corners": [[round(float(x), 1), round(float(y), 1)] for x, y in corners],
    }
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
