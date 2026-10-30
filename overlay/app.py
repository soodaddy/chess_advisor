"""Chess.app 위에 추천 수(목적지 칸 테두리, 옮길 말 윤곽)를 겹쳐 그리고, 옆 패널에 설명을 보여준다.

사용자는 항상 백이다. 백 차례일 때만 추천한다.
"""
import os
import sys
import threading

import chess
import objc
from AppKit import (
    NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSBezierPath,
    NSColor, NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseDragged, NSEventMaskLeftMouseUp,
    NSEventMaskMouseMoved, NSEventTypeLeftMouseDown, NSEventTypeLeftMouseDragged, NSEventTypeLeftMouseUp,
    NSEventTypeMouseMoved, NSFloatingWindowLevel, NSFont, NSPanel, NSScreen, NSStatusWindowLevel, NSTextField, NSView,
    NSWindow, NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskClosable, NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled, NSWindowStyleMaskUtilityWindow,
)
from Foundation import NSMakeRect, NSObject, NSTimer, NSUserDefaults
from PyObjCTools import AppHelper

from board.ax_reader import read_position
from board.calibrate import Calibrator
from board.geometry import square_quad
from board.silhouette import outline_for_square
from engine.advisor import Advisor, build_board
from overlay.drag import OutlineGuard, inside

TICK_SECONDS = 1.0
DEBUG = bool(os.environ.get("CHESS_ADVISOR_DEBUG"))   # 마우스 이벤트 진단 로그
MOUSE_KINDS = {NSEventTypeLeftMouseDown: "down", NSEventTypeLeftMouseDragged: "drag", NSEventTypeLeftMouseUp: "up",
               NSEventTypeMouseMoved: "move"}
MOUSE_MASK = NSEventMaskLeftMouseDown | NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp | NSEventMaskMouseMoved
PANEL_SIZE = (380, 260)
PANEL_AUTOSAVE_NAME = "ChessAdvisorPanel"


BLUE_EDGE = (0.10, 0.40, 1.00, 0.95)     # 목적지 칸 테두리
GREEN_EDGE = (0.10, 0.80, 0.30, 1.00)    # 옮길 말의 윤곽


def polygon_path(points):
    path = NSBezierPath.bezierPath()
    path.moveToPoint_(points[0])
    for point in points[1:]:
        path.lineToPoint_(point)
    path.closePath()
    path.setLineJoinStyle_(1)
    return path


class MarkView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(MarkView, self).initWithFrame_(frame)
        if self is not None:
            self.target_quad = None  # 목적지 칸의 네 꼭짓점
            self.piece_outline = None  # 옮길 말의 윤곽 다각형 (없으면 출발 칸 사각형)
        return self

    def isFlipped(self):
        return True  # 좌상단 원점이라 창 기준 상대좌표를 그대로 쓸 수 있다.

    def drawRect_(self, rect):
        if self.target_quad:
            box = polygon_path(self.target_quad)   # 원근에 맞는 사각형 테두리 (채우지 않음)
            NSColor.colorWithSRGBRed_green_blue_alpha_(*BLUE_EDGE).setStroke()
            box.setLineWidth_(4)
            box.stroke()
        if self.piece_outline:
            outline = polygon_path(self.piece_outline)   # 옮길 말의 모양을 따라 그린 초록 테두리
            NSColor.colorWithSRGBRed_green_blue_alpha_(*GREEN_EDGE).setStroke()
            outline.setLineWidth_(1.75)
            outline.stroke()


class Controller(NSObject):
    def init(self):
        self = objc.super(Controller, self).init()
        if self is None:
            return None
        self.advisor = Advisor()
        self.calibrator = Calibrator()
        self.last_key = None      # 직전 tick에서 읽은 상태 (안정화 확인용)
        self.requested_key = None  # 분석을 요청한 상태
        self.result = None        # (key, Suggestion|str, 보정 모서리|None, 말 윤곽|None, 안내|None)
        self.shown_key = None
        self.shown_corners = None  # 지금 화살표를 그리는 데 쓴 보정
        self.bad_checks = 0        # 보정 점검 연속 실패 횟수
        self.guard = OutlineGuard()  # 말을 집어 끌기 시작하면 초록 윤곽을 숨긴다
        self.window_origin = None    # Chess 창의 좌상단 (화면 좌표, pt)
        self.build_ui()
        # Chess.app의 클릭을 가로채지 않고 지켜만 보는 전역 마우스 모니터 (마우스 이벤트는 별도 권한이 필요 없다).
        self.mouse_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            MOUSE_MASK, self.on_mouse)
        if self.mouse_monitor is None:
            print("마우스 모니터를 만들지 못해 말을 끌 때 윤곽이 숨지 않습니다.", file=sys.stderr, flush=True)
        return self

    @objc.python_method
    def build_ui(self):
        self.overlay = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 100, 100), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.overlay.setOpaque_(False)
        self.overlay.setBackgroundColor_(NSColor.clearColor())
        self.overlay.setHasShadow_(False)
        self.overlay.setIgnoresMouseEvents_(True)
        self.overlay.setLevel_(NSStatusWindowLevel)
        self.overlay.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary)
        self.mark_view = MarkView.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 100))
        self.overlay.setContentView_(self.mark_view)

        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskUtilityWindow | NSWindowStyleMaskNonactivatingPanel
                 | NSWindowStyleMaskClosable)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, *PANEL_SIZE), style, NSBackingStoreBuffered, False)
        self.panel.setTitle_("체스 어드바이저 (백)")
        self.panel.setFloatingPanel_(True)
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setDelegate_(self)
        # 창을 끌어서 옮길 수 있고, 위치는 자동 저장되어 다음 실행에도 유지된다.
        self.panel.setMovableByWindowBackground_(True)
        self.panel.setFrameAutosaveName_(PANEL_AUTOSAVE_NAME)
        self.panel_placed = NSUserDefaults.standardUserDefaults().objectForKey_(
            "NSWindow Frame " + PANEL_AUTOSAVE_NAME) is not None
        self.label = NSTextField.wrappingLabelWithString_("Chess.app을 찾는 중…")
        self.label.setFont_(NSFont.systemFontOfSize_(13))
        self.label.setFrame_(NSMakeRect(12, 10, PANEL_SIZE[0] - 24, PANEL_SIZE[1] - 20))
        self.panel.contentView().addSubview_(self.label)
        self.panel.orderFrontRegardless()

    def windowWillClose_(self, notification):
        NSApplication.sharedApplication().terminate_(None)

    def applicationWillTerminate_(self, notification):
        self.advisor.close()

    # -- 표시 ------------------------------------------------------------
    @objc.python_method
    def say(self, text):
        self.label.setStringValue_(text)

    @objc.python_method
    def place_windows(self, window, visible):
        x, y, w, h = window
        self.window_origin = (x, y)
        screen_h = NSScreen.screens()[0].frame().size.height
        self.overlay.setFrame_display_(NSMakeRect(x, screen_h - (y + h), w, h), True)
        if visible:
            self.overlay.orderFrontRegardless()
        else:
            self.overlay.orderOut_(None)  # 다른 창이 Chess를 가리면 화살표를 그 위에 띄우지 않는다.
        if not self.panel_placed:  # 처음 한 번만 Chess 창 옆에 놓고, 이후 위치는 사용자가 정한다.
            screen_w = NSScreen.screens()[0].frame().size.width
            px = x + w + 12 if x + w + 12 + PANEL_SIZE[0] <= screen_w else max(0, x - PANEL_SIZE[0] - 12)
            self.panel.setFrameTopLeftPoint_((px, screen_h - y))
            self.panel_placed = True

    @objc.python_method
    def set_marks(self, target_quad=None, piece_outline=None):
        if piece_outline:
            self.guard.arm(piece_outline)
        else:
            self.guard.clear()
        self.mark_view.target_quad = target_quad
        self.refresh_piece_mark()

    @objc.python_method
    def refresh_piece_mark(self):
        """초록 윤곽을 guard 상태(끌기 중이면 숨김)에 맞춰 다시 그린다."""
        self.mark_view.piece_outline = self.guard.polygon
        self.mark_view.setNeedsDisplay_(True)

    @objc.python_method
    def on_mouse(self, event):
        try:
            kind = MOUSE_KINDS.get(event.type())
            if kind is None or self.window_origin is None:
                return
            if kind in ("move", "drag") and not self.guard.tracking:
                return   # 말을 집은 뒤 움직임만 본다. 평소 마우스 이동은 바로 버린다.
            location = NSEvent.mouseLocation()   # 화면 좌표 (좌하단 원점)
            screen_h = NSScreen.screens()[0].frame().size.height
            point = (location.x - self.window_origin[0], (screen_h - location.y) - self.window_origin[1])
            region = self.guard.region
            changed = self.guard.mouse(kind, point)
            if DEBUG and (kind not in ("drag", "move") or changed):
                print("마우스 %-4s 창기준=(%.0f,%.0f) 윤곽=%s 안쪽=%s 숨김으로변경=%s" % (
                    kind, point[0], point[1], "있음" if region else "없음",
                    inside(point, region) if region else "-", changed), file=sys.stderr, flush=True)
            if changed:
                self.refresh_piece_mark()
        except Exception as e:
            print("마우스 이벤트 처리 오류: %s" % e, file=sys.stderr, flush=True)

    # -- 주기 작업 ---------------------------------------------------------
    def tick_(self, timer):
        try:
            self.update()
        except Exception as e:  # 한 번의 실패로 앱이 죽지 않게 한다.
            self.say("오류: %s" % e)

    @objc.python_method
    def update(self):
        pos = read_position()
        if pos is None:
            self.overlay.orderOut_(None)
            self.set_marks()
            self.say("Chess.app 대국 창을 찾지 못했습니다.\n앱을 실행하고 창이 보이게 해 주세요.")
            return
        self.place_windows(pos.window, pos.visible)
        if self.guard.tick():   # 끌기가 취소돼 보드가 그대로면 윤곽을 다시 보여준다
            self.refresh_piece_mark()
        if pos.turn is None:
            self.set_marks()
            self.say("진행 중인 대국이 아닙니다.\n" + pos.title)
            return
        if pos.turn != chess.WHITE:
            self.set_marks()
            self.say("상대(흑) 차례입니다. 기다리는 중…")
            self.last_key = None
            return
        board = build_board(pos.pieces, pos.turn)
        key = (board.board_fen(), pos.window[2:])
        stable = key == self.last_key  # 말이 움직이는 도중에는 분석하지 않는다.
        self.last_key = key
        if not stable:
            return
        if key != self.requested_key:
            self.requested_key = key
            self.shown_corners = None
            self.set_marks()
            self.say("분석 중…")
            threading.Thread(target=self.analyze, args=(key, board, pos), daemon=True).start()
            return
        if self.result and self.result[0] == key and self.shown_key != key:
            self.shown_key = key
            self.show_result(*self.result[1:])
        elif self.shown_corners is not None:
            self.check_calibration(pos)

    @objc.python_method
    def check_calibration(self, pos):
        """사용자가 보드를 회전/확대했거나 창 크기가 바뀌면 보정이 어긋난다. 연속 2회 실패하면 다시 보정한다."""
        if self.calibrator.is_valid(pos.window, self.shown_corners, pos.pieces):
            self.bad_checks = 0
            return
        self.bad_checks += 1
        if self.bad_checks >= 2:
            self.bad_checks = 0
            self.requested_key = None  # 다음 tick에 다시 분석하며 보정한다.
            self.shown_key = None
            self.set_marks()

    @objc.python_method
    def analyze(self, key, board, pos):
        try:
            result = self.advisor.suggest(board) or "합법 수가 없습니다."
        except ValueError as e:
            result = "보드를 해석하지 못했습니다: %s" % e
        corners, outline, note = None, None, None
        if not isinstance(result, str):
            try:
                corners = self.calibrator.ensure(pos.window, pos.pieces)  # 새 창 크기면 스캔에 수 초 걸린다.
            except Exception:
                corners = None
            if corners is not None:
                outline, note = outline_for_square(pos.window, corners, result.move.from_square)
        self.result = (key, result, corners, outline, note)

    @objc.python_method
    def show_result(self, result, corners, outline, note):
        if isinstance(result, str):
            self.say(result)
            return
        text = result.text
        if corners is None:
            text += "\n\n(보드 위치를 자동으로 찾지 못해 표시를 생략했습니다. 다음 수에서 다시 시도합니다.)"
            self.set_marks()
        else:
            self.set_marks(square_quad(corners, result.move.to_square),
                           outline or square_quad(corners, result.move.from_square))
        self.shown_corners = corners
        if note:
            text += "\n\n(%s)" % note
            print(note, file=sys.stderr, flush=True)
        self.say(text)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = Controller.alloc().init()
    app.setDelegate_(controller)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        TICK_SECONDS, controller, b"tick:", None, True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
