from overlay.drag import MOVE_THRESHOLD, RESTORE_DELAY, OutlineGuard, inside

PIECE = [(100, 100), (140, 100), (140, 180), (100, 180)]
ON_PIECE = (120, 140)
ELSEWHERE = (300, 300)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def armed():
    clock = Clock()
    guard = OutlineGuard(clock)
    guard.arm(PIECE)
    return guard, clock


def test_inside_has_margin():
    assert inside(ON_PIECE, PIECE)
    assert inside((95, 140), PIECE)          # 가장자리에서 5pt 밖: 허용
    assert not inside((80, 140), PIECE)      # 20pt 밖: 다른 곳을 클릭


def test_click_to_pick_up_then_move_hides_outline():
    """Chess.app의 클릭-클릭 방식: 말을 클릭(누름+뗌)하면 들려서 커서를 따라다닌다."""
    guard, _ = armed()
    assert guard.mouse("down", ON_PIECE) is False
    assert guard.mouse("up", ON_PIECE) is False
    assert guard.polygon == PIECE            # 클릭만으로는 아직 움직이지 않았다
    assert guard.tracking
    assert guard.mouse("move", (ON_PIECE[0] + 2, ON_PIECE[1])) is False    # 떨림
    assert guard.mouse("move", (ON_PIECE[0] + MOVE_THRESHOLD + 1, ON_PIECE[1])) is True
    assert guard.polygon is None             # 움직이기 시작하면 사라진다


def test_press_and_drag_hides_outline():
    """버튼을 누른 채 끄는 방식."""
    guard, _ = armed()
    guard.mouse("down", ON_PIECE)
    assert guard.mouse("drag", (ON_PIECE[0] + 10, ON_PIECE[1])) is True
    assert guard.polygon is None


def test_moving_without_picking_up_does_nothing():
    guard, _ = armed()
    assert not guard.tracking
    assert guard.mouse("move", (500, 500)) is False
    guard.mouse("down", ELSEWHERE)
    assert guard.mouse("drag", (350, 350)) is False
    assert guard.polygon == PIECE


def test_clicking_elsewhere_cancels_a_pending_pick():
    guard, _ = armed()
    guard.mouse("down", ON_PIECE); guard.mouse("up", ON_PIECE)
    guard.mouse("down", ELSEWHERE); guard.mouse("up", ELSEWHERE)
    assert not guard.tracking
    assert guard.mouse("move", (500, 500)) is False and guard.polygon == PIECE


def test_outline_returns_if_move_is_cancelled():
    guard, clock = armed()
    guard.mouse("down", ON_PIECE); guard.mouse("up", ON_PIECE)
    guard.mouse("move", (200, 200))
    assert guard.polygon is None
    guard.mouse("down", ELSEWHERE); guard.mouse("up", ELSEWHERE)   # 목적지를 클릭했는데 이동이 무효였다
    clock.now += RESTORE_DELAY - 0.1
    assert guard.tick() is False and guard.polygon is None
    clock.now += 0.2
    assert guard.tick() is True and guard.polygon == PIECE
    assert guard.tick() is False


def test_no_restore_while_piece_is_still_in_hand():
    guard, clock = armed()
    guard.mouse("down", ON_PIECE); guard.mouse("up", ON_PIECE)
    guard.mouse("move", (200, 200))
    clock.now += 60                          # 말을 든 채로 오래 있어도 놓기 전에는 복원하지 않는다
    assert guard.tick() is False and guard.polygon is None


def test_pressing_again_before_restore_pauses_the_timer():
    guard, clock = armed()
    guard.mouse("down", ON_PIECE); guard.mouse("up", ON_PIECE); guard.mouse("move", (200, 200))
    guard.mouse("down", ELSEWHERE); guard.mouse("up", ELSEWHERE)
    clock.now += 1.0
    guard.mouse("down", ELSEWHERE)           # 다시 누르는 중
    clock.now += 5
    assert guard.tick() is False and guard.polygon is None


def test_arm_and_clear_reset_everything():
    guard, _ = armed()
    guard.mouse("down", ON_PIECE); guard.mouse("move", (200, 200))
    assert guard.polygon is None
    guard.arm(PIECE)                         # 새 추천이 뜨면 다시 보인다
    assert guard.polygon == PIECE and not guard.tracking
    guard.clear()
    assert guard.polygon is None and guard.region is None and guard.mouse("down", ON_PIECE) is False
