"""말을 집어서 움직이기 시작하면 옮길 말의 윤곽을 숨기고, 이동이 취소되면 다시 보여준다.

Chess.app은 말을 클릭하면 말이 들려서 커서를 따라다니고 목적지를 다시 클릭하는 방식과,
버튼을 누른 채 끄는 방식을 모두 쓴다. 두 경우 모두 "말을 누른 뒤 커서가 움직이기 시작함"이 신호다.
"""
import time

import cv2
import numpy as np

HIT_MARGIN = 6.0       # pt. 윤곽 가장자리에서 이만큼 벗어난 클릭도 그 말을 집은 것으로 본다
MOVE_THRESHOLD = 4.0   # pt. 말을 집은 자리에서 커서가 이만큼 움직이면 움직이기 시작한 것으로 본다
RESTORE_DELAY = 1.2    # s. 말을 놓은 뒤에도 같은 수를 추천 중이면(이동이 취소됨) 윤곽을 다시 보여준다


def inside(point, polygon, margin=HIT_MARGIN):
    """point가 polygon 안이거나 가장자리에서 margin 이내인가."""
    poly = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(poly, (float(point[0]), float(point[1])), True) >= -margin


class OutlineGuard:
    """옮길 말 윤곽의 표시 여부. 좌표는 모두 창 기준 pt.

    mouse()/tick()은 윤곽이 보이는지가 바뀌었을 때 True를 돌려준다.
    이벤트 종류: "down", "up", "drag"(버튼을 누른 채 이동), "move"(버튼 없이 이동).
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.clear()

    def arm(self, polygon):
        """새 윤곽을 보이기 시작한다."""
        self._region = polygon
        self._hidden = False
        self._origin = None         # 말을 집은 자리. 커서가 움직이기 시작하면 윤곽을 숨긴다
        self._released_at = None    # 말을 놓은 시각 (숨김 중에만 의미 있음)

    def clear(self):
        self.arm(None)

    @property
    def region(self):
        """추천된 말의 윤곽(숨김 여부와 무관). 없으면 None."""
        return self._region

    @property
    def polygon(self):
        """지금 그려야 할 윤곽. 숨김 중이거나 없으면 None."""
        return None if self._hidden else self._region

    @property
    def tracking(self):
        """커서 이동 이벤트를 살펴봐야 하는가 (말을 집은 뒤 아직 움직이기 전)."""
        return self._origin is not None and not self._hidden

    def mouse(self, kind, point):
        if self._region is None:
            return False
        if kind == "down":
            if self._hidden:
                self._released_at = None        # 이미 집은 말을 놓는 중 (목적지 클릭 또는 취소)
            elif inside(point, self._region):
                self._origin = point            # 말을 집었다
            else:
                self._origin = None             # 다른 곳을 눌렀으니 집은 것이 아니다
            return False
        if kind in ("drag", "move"):
            if not self.tracking:
                return False
            dx, dy = point[0] - self._origin[0], point[1] - self._origin[1]
            if (dx * dx + dy * dy) ** 0.5 < MOVE_THRESHOLD:
                return False
            self._hidden = True
            self._origin = None
            return True
        if kind == "up" and self._hidden:
            self._released_at = self._clock()   # 놓았다: 보드가 안 바뀌면 곧 복원한다
        return False

    def tick(self):
        """말을 놓은 지 RESTORE_DELAY가 지났는데도 같은 수라면 윤곽을 다시 보여준다."""
        if self._hidden and self._released_at is not None and self._clock() - self._released_at >= RESTORE_DELAY:
            self._hidden = False
            self._released_at = None
            return True
        return False
