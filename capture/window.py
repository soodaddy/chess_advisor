"""Chess.app 창을 찾아 PNG로 캡처한다."""
import subprocess
import sys
from pathlib import Path

import Quartz
from AppKit import NSRunningApplication

# 앱 이름은 시스템 언어에 따라 달라지므로("체스") 번들 ID로 찾는다.
BUNDLE_ID = "com.apple.Chess"


def find_chess_window():
    """Chess.app의 가장 큰 일반 창 (id, bounds)을 반환한다. 없으면 None."""
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    if not apps:
        return None
    pid = apps[0].processIdentifier()
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )
    best = None
    for w in windows:
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer") != 0:
            continue
        b = w["kCGWindowBounds"]
        area = b["Width"] * b["Height"]
        if best is None or area > best[0]:
            best = (area, w["kCGWindowNumber"], dict(b))
    return None if best is None else best[1:]


def capture(path):
    """창을 path에 저장한다. 성공하면 True."""
    found = find_chess_window()
    if found is None:
        return False
    window_id, _ = found
    # -o: 그림자 제외, -x: 소리 없음
    result = subprocess.run(
        ["screencapture", "-l", str(window_id), "-o", "-x", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("screencapture 오류:", result.stderr.strip())
        return False
    return Path(path).exists() and Path(path).stat().st_size > 0


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "capture_test.png")
    found = find_chess_window()
    if found is None:
        sys.exit("Chess.app 창을 찾지 못했습니다. 앱을 실행하고 창을 화면에 보이게 하세요.")
    print("창 id/영역:", found)
    if not capture(out):
        sys.exit("캡처 실패 (화면 기록 권한을 확인하세요).")
    print("저장:", out.resolve())
