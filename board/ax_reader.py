"""Chess.app의 접근성(AX) 트리에서 보드 상태를 읽는다. 화면 인식이 필요 없다."""
import re
from dataclasses import dataclass

import chess
import Quartz
from AppKit import NSRunningApplication
from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication

BUNDLE_ID = "com.apple.Chess"

# 앱 표시 언어에 따라 설명 문자열이 달라지므로 한국어/영어를 모두 받는다.
PIECE_TYPES = {
    "폰": chess.PAWN, "나이트": chess.KNIGHT, "비숍": chess.BISHOP,
    "룩": chess.ROOK, "퀸": chess.QUEEN, "킹": chess.KING,
    "pawn": chess.PAWN, "knight": chess.KNIGHT, "bishop": chess.BISHOP,
    "rook": chess.ROOK, "queen": chess.QUEEN, "king": chess.KING,
}
COLORS = {"화이트": chess.WHITE, "블랙": chess.BLACK, "white": chess.WHITE, "black": chess.BLACK}
TURN_RE = re.compile(r"\((화이트|블랙|White|Black)[^)]*?(차례|turn|move)", re.IGNORECASE)


@dataclass
class Position:
    pieces: dict           # chess.Square -> chess.Piece
    turn: object           # chess.WHITE / chess.BLACK / None (대국 종료 등)
    title: str
    window: tuple          # (x, y, width, height) pt, 화면 좌상단 기준
    visible: bool = True   # 보드 중심이 다른 창에 가려지지 않고 맨 앞에 보이는가


def _attr(el, name):
    err, value = AXUIElementCopyAttributeValue(el, name, None)
    return value if err == 0 else None


def parse_description(desc):
    """'화이트 룩, a1' -> (chess.A1, Piece), 'a3' -> (chess.A3, None). 해석 불가면 None."""
    if not desc:
        return None
    parts = [p.strip() for p in desc.split(",")]
    try:
        square = chess.parse_square(parts[-1].lower())
    except ValueError:
        return None
    if len(parts) == 1:
        return square, None
    words = parts[0].lower().split()
    if len(words) != 2 or words[0] not in COLORS or words[1] not in PIECE_TYPES:
        return None
    return square, chess.Piece(PIECE_TYPES[words[1]], COLORS[words[0]])


def parse_turn(title):
    m = TURN_RE.search(title or "")
    if not m:
        return None
    return chess.WHITE if m.group(1) in ("화이트", "White", "white") else chess.BLACK


def chess_app_element():
    """Chess.app의 AX 애플리케이션 요소. 실행 중이 아니면 None."""
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    return AXUIElementCreateApplication(apps[0].processIdentifier()) if apps else None


def _on_screen_windows_front_to_back():
    return Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )


def is_topmost_at_center(windows, target_number):
    """일반 창(layer 0) 중 target 창의 중심점을 덮는 가장 앞의 창이 target인가. windows는 앞→뒤 순서."""
    target = next((w for w in windows if w["kCGWindowNumber"] == target_number), None)
    if target is None:
        return False
    b = target["kCGWindowBounds"]
    cx, cy = b["X"] + b["Width"] / 2, b["Y"] + b["Height"] / 2
    for w in windows:
        if w.get("kCGWindowLayer") != 0:
            continue
        wb = w["kCGWindowBounds"]
        if wb["X"] <= cx <= wb["X"] + wb["Width"] and wb["Y"] <= cy <= wb["Y"] + wb["Height"]:
            return w["kCGWindowNumber"] == target_number
    return False


def _read_board_from_ax_window(ax_window):
    groups = [c for c in (_attr(ax_window, "AXChildren") or []) if _attr(c, "AXRole") == "AXGroup"]
    for group in groups:
        pieces, squares = {}, 0
        for button in _attr(group, "AXChildren") or []:
            parsed = parse_description(_attr(button, "AXDescription"))
            if parsed is None:
                continue
            squares += 1
            if parsed[1] is not None:
                pieces[parsed[0]] = parsed[1]
        if squares == 64:
            return pieces
    return None


def read_position():
    """화면 맨 앞에 보이는 Chess 대국 창의 Position. Chess.app이 없거나 보드를 못 읽으면 None."""
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    if not apps:
        return None
    pid = apps[0].processIdentifier()
    ax_windows = _attr(AXUIElementCreateApplication(pid), "AXWindows") or []
    all_windows = _on_screen_windows_front_to_back()
    chess_windows = [w for w in all_windows if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0]
    # 같은 자리에 겹친 창이 여러 개일 수 있어서 Quartz의 앞→뒤 순서로 제목이 일치하는 창을 고른다.
    for qw in chess_windows:
        title = qw.get("kCGWindowName") or ""
        for ax_window in ax_windows:
            if _attr(ax_window, "AXTitle") != title:
                continue
            pieces = _read_board_from_ax_window(ax_window)
            if pieces is None:
                continue
            b = qw["kCGWindowBounds"]
            return Position(pieces, parse_turn(title), title, (b["X"], b["Y"], b["Width"], b["Height"]),
                            is_topmost_at_center(all_windows, qw["kCGWindowNumber"]))
    return None


if __name__ == "__main__":
    pos = read_position()
    if pos is None:
        raise SystemExit("Chess.app 대국 창을 읽지 못했습니다.")
    board = chess.Board(None)
    for sq, piece in pos.pieces.items():
        board.set_piece_at(sq, piece)
    print(pos.title)
    print(board)
    print("차례:", {chess.WHITE: "백", chess.BLACK: "흑", None: "-"}[pos.turn], "| 창:", pos.window)
