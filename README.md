# Chess Advisor

macOS 기본 **Chess.app**의 보드를 읽고, Stockfish로 **백의 추천 수**를 Chess 창 위에 겹쳐서 보여주는 어드바이저입니다.
화면을 이미지로 인식하지 않고 Chess.app의 접근성(Accessibility) 정보를 읽기 때문에 말 인식 오류가 없습니다.

## 기능

- 백 차례가 되면 추천 수를 계산해서 표시합니다.
  - **목적지 칸**: 파란색 사각 테두리 (보드 원근에 맞춘 사다리꼴)
  - **옮길 말**: 말 모양을 따라 그린 초록색 윤곽
  - **설명 패널**: 추천 수, 평가, 이유, 예상 진행, 다른 후보, 방어되지 않은 말 경고
- 말을 집어서 움직이기 시작하면 초록 윤곽이 사라집니다. 이동이 취소되면 다시 나타납니다.
- Chess 창의 크기나 위치가 바뀌어도 자동으로 보정합니다.
- 설명 패널은 끌어서 옮길 수 있고 위치를 기억합니다.
- 전부 이 Mac 안에서 동작합니다. 외부 서버나 AI API를 호출하지 않습니다.

## 동작 방식

| 단계 | 방법 |
|---|---|
| 보드 읽기 | Chess.app의 접근성 트리가 모든 칸을 `화이트 룩, a1` / `a3` 형태로 알려줍니다. |
| 추천 수 | [python-chess](https://github.com/niklasf/python-chess)로 보드를 만들고 Stockfish(UCI)에 물어봅니다. |
| 표시 좌표 | 접근성 히트 테스트(화면 좌표 → 칸)로 보드 모서리를 최적화해서 자동 보정합니다. 빈 칸의 응답 영역은 자기 칸 안에, 칸이 아닌 곳은 보드 밖에 있어야 한다는 조건을 씁니다. |
| 말 윤곽 | 창 스크린샷을 GrabCut으로 분할합니다. 화면 기록 권한이 없거나 분할이 실패하면 히트 영역으로 만든 간이 윤곽, 그것도 안 되면 출발 칸 사각형으로 대체합니다. |
| 표시 | PyObjC로 만든 클릭이 통과하는 투명 오버레이 창 |

## 요구 사항

- macOS와 기본 **Chess.app** (3D 보드)
- Python 3.14에서 개발했습니다. 다른 버전은 확인하지 않았습니다.
- [Stockfish](https://stockfishchess.org/): `brew install stockfish`
- 앱을 실행하는 터미널에 대한 권한 (시스템 설정 → 개인정보 보호 및 보안)
  - **손쉬운 사용**: 필수. 보드를 읽고 칸 위치를 찾는 데 씁니다.
  - **화면 및 시스템 오디오 녹음**: 선택. 없으면 말 윤곽이 간이 방식으로 표시됩니다.

## 설치

```bash
git clone https://github.com/soodaddy/chess_advisor.git
cd chess_advisor
python3 -m venv .venv
.venv/bin/pip install python-chess opencv-python-headless numpy scipy \
    pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
brew install stockfish
```

## 실행

Chess.app에서 대국을 시작하고 대국 창을 맨 앞에 둔 뒤 실행합니다.

```bash
.venv/bin/python -m overlay.app
```

- 백 차례일 때만 추천합니다. 상대(흑) 차례에는 기다립니다.
- Chess 창이 다른 창에 가려지면 오버레이는 숨고 설명 패널만 남습니다.
- 설명 패널을 닫으면 종료됩니다.

## 한계

- 사용자는 항상 **백**이고 백이 아래쪽에 보이는 방향만 지원합니다.
- 화면에서 알 수 없는 정보는 추정합니다. 캐슬링은 "킹과 룩이 처음 자리에 있으면 가능", 앙파상은 "없음"으로 봅니다. 드물게 불가능한 수를 추천할 수 있습니다.
- 평가 점수는 Stockfish가 계산하지만, 패널의 "이유"는 규칙으로 만든 참고용 설명입니다.
- 한국어 Chess.app에서 개발하고 확인했습니다. 영어 설명 문자열(`White Rook, a1`)을 읽는 코드가 있지만 실제 영어 환경에서는 확인하지 못했습니다.
- 같은 자리에 여러 대국 창이 겹쳐 있으면 맨 앞에 보이는 창을 따릅니다.
- 보드가 말로 거의 꽉 차서 빈 칸이 10개 미만이면 자동 보정을 못 하고 그 수에서는 표시를 생략합니다. 다음 수에서 다시 시도합니다.
- **컴퓨터와 두는 로컬 Chess.app의 연습·학습용입니다.** 사람과 두는 온라인 대국에서 쓰면 부정행위입니다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| 패널에 "Chess.app 대국 창을 찾지 못했습니다" | Chess.app을 실행하고 대국 창이 화면에 보이게 하세요. |
| 패널 맨 아래에 "화면 기록 권한이 없어 간이 윤곽으로 표시했습니다" | 터미널에 화면 기록 권한을 허용하고 터미널을 다시 시작하세요. 표시는 간이 윤곽으로도 동작합니다. |
| 아무것도 표시되지 않음 | 터미널에 손쉬운 사용 권한이 있는지, 백 차례인지 확인하세요. |
| 마우스 이벤트 진단 | `CHESS_ADVISOR_DEBUG=1 .venv/bin/python -m overlay.app` 로 실행하면 마우스 이벤트가 로그로 출력됩니다. |

부분별 확인 명령:

```bash
.venv/bin/python -m board.ax_reader   # 보드 읽기
.venv/bin/python -m board.calibrate   # 보드 모서리 자동 보정
.venv/bin/python -m engine.advisor    # 추천 수 한 번 계산
```

## 개발

```bash
.venv/bin/pip install pytest
.venv/bin/pytest -q    # Chess.app 없이 실행되는 단위 테스트
```

```
board/ax_reader.py    접근성 트리에서 말 배치와 차례 읽기
board/calibrate.py    히트 테스트 기반 보드 모서리 자동 보정과 검증
board/geometry.py     모서리 ↔ 칸 좌표 계산 (호모그래피)
board/silhouette.py   이동할 말의 윤곽 (GrabCut, 간이 윤곽)
engine/advisor.py     Stockfish 추천과 한국어 설명
overlay/app.py        투명 오버레이와 설명 패널
overlay/drag.py       말을 집어 움직이면 윤곽을 숨기는 로직
capture/window.py     창 스크린샷 도구
tests/                단위 테스트
```

설계 결정과 그 이유(AX 좌표를 화면 표시에 쓰지 않는 이유 등)는 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.

## 사용한 오픈소스

| 프로젝트 | 라이선스 | 용도 |
|---|---|---|
| [Stockfish](https://stockfishchess.org/) | GPL-3.0 | 체스 엔진. 별도 프로그램으로 실행하며 이 저장소에 포함하지 않습니다. |
| [python-chess](https://github.com/niklasf/python-chess) | GPL-3.0 이상 | 보드, 합법 수, UCI 통신 |
| [OpenCV](https://opencv.org/) | Apache-2.0 | GrabCut 분할, 도형 처리 |
| [NumPy](https://numpy.org/), [SciPy](https://scipy.org/) | BSD | 수치 계산, 보정 최적화 |
| [PyObjC](https://pyobjc.readthedocs.io/) | MIT | macOS 접근성 API와 오버레이 창 |

## 라이선스

[GNU General Public License v3.0 이상](LICENSE) (GPL-3.0-or-later)

이 프로그램은 자유 소프트웨어입니다. 자유 소프트웨어 재단이 발행한 GNU 일반 공중 사용 허가서 버전 3, 또는
(선택에 따라) 그 이후 버전의 조건에 따라 재배포하거나 수정할 수 있습니다. 이 프로그램은 유용하기를 바라며 배포되지만
**어떠한 보증도 제공하지 않습니다.** 자세한 내용은 LICENSE를 참고하세요.

python-chess(GPL-3.0 이상)를 직접 사용하므로 같은 계열인 GPL-3.0을 선택했습니다.
