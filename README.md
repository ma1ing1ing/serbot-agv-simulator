# SerBot AGV 시뮬레이터

SerBot AGV용 AI를 개발할 때 사용하는 로컬 3D 시뮬레이터입니다. 가상 아이들의 움직임과 로봇 시점의 영상을 제공하고, 외부 Python 프로그램에서 로봇을 제어할 수 있습니다.

기본 놀이는 **술래잡기**입니다. 아이들은 로봇과의 거리, 벽과 다른 아이의 위치에 따라 걷거나 달리며 도망갑니다. 로봇 자동 추격을 켜면 바로 관찰할 수 있고, 수동 버튼이나 Python 주행 명령을 보내면 자동 추격이 해제됩니다. 기존 무궁화꽃이 피었습니다도 놀이 선택에서 사용할 수 있습니다.

영상 인식 AI는 포함하지 않습니다. 자동 추격은 정답 위치를 사용하는 규칙 기반 시연입니다. 직접 만든 영상 AI를 평가할 때는 자동 추격을 끄고 카메라 영상으로 판단하세요.

![시뮬레이터 화면](docs/assets/preview.jpg)

## 실행

**Playground A 위치 기록 재생:** 놀이 선택에서 `Playground A · 위치 기록 재생`을 고르면 실제 배포 CSV의 여러 참가자 경로를 동시에 재생합니다. 시간 이동·구간 선택·아이별 이동선을 지원합니다. [원본 준비와 해석 범위](docs/PLAYGROUND_A.md)를 확인하세요.

필요한 환경: **Python 3.10 이상**, **WebGL을 지원하는 브라우저**. 서버 실행에 필요한 Python 추가 패키지는 없습니다. Three.js도 저장소에 포함되어 있습니다.

```bash
git clone https://github.com/ma1ing1ing/serbot-agv-simulator.git
cd serbot-agv-simulator
python3 -m simulator.server
```

브라우저에서 **<http://127.0.0.1:8767>**을 엽니다. Windows에서는 `python3` 대신 `py` 또는 `python`을 사용합니다. 종료는 서버 터미널에서 `Ctrl+C`입니다.

> `simulator/static/index.html`을 파일로 직접 열면 동작하지 않습니다. Python 서버를 실행한 뒤 위 HTTP 주소로 접속해야 합니다. 카메라 영상을 받는 동안 브라우저 탭을 활성 상태로 유지하세요.

## 구현된 게임 규칙

1. **술래잡기**를 선택하고 **게임 시작**을 누릅니다. 로봇이 술래입니다.
2. 가까운 아이는 달리고, 멀리 있는 아이는 걷거나 쉬며 벽과 다른 아이를 피합니다.
3. 로봇과의 중심 거리가 0.74m 이하가 되면 잡힌 것으로 처리합니다. 잡힌 아이는 붉은 표시와 함께 멈춥니다.
4. 모두 잡히면 게임이 끝납니다. 자동 추격은 시연용이며 매번 전원을 잡는다는 보장은 없습니다.
5. **로봇 정지**나 수동 주행은 자동 추격을 해제합니다. 다시 켜려면 **로봇 자동 추격**을 선택합니다.

무궁화꽃이 피었습니다에서는 기존의 시선에 따른 접근·정지, 터치 후 전원 도망 규칙을 사용합니다. [게임 규칙](docs/SIMULATION.md)을 확인하세요.

## ChildACT 관절 동작 연결

다운로드한 `ChildACT.zip`으로 로컬 모션 파일을 생성합니다. Python 표준 라이브러리만 사용하며 NumPy 설치는 필요하지 않습니다.

```bash
python3 tools/build_childact_motion.py /Users/marine/Downloads/ChildACT.zip
python3 -m simulator.server
```

브라우저에 **ChildACT 동작 연결됨**이 표시되면 걷기·조깅·달리기 기록에서 추출한 관절 각도 변화가 연결된 상태입니다. 팔꿈치와 무릎이 있는 캐릭터에 적용하며, 모션 파일이 없으면 **기본 동작 사용 중**으로 표시하고 기본 동작을 재생합니다.

**ChildACT가 제공하는 것은 관절 동작이며, 이 시뮬의 m 단위 이동 경로는 규칙으로 생성합니다.** 2차원 좌표를 투영 각도로 변환한 근사 애니메이션으로, 실제 어린이의 3차원 자세·이동 경로·속도를 복원한 결과가 아닙니다. [변환 방법과 한계](docs/CHILDACT.md)를 확인하세요. 생성된 연구 데이터는 Git과 배포 패키지에 포함하지 않습니다.

## 기능

| 기능 | 내용 |
|---|---|
| 3D 공간 | SerBot AGV 간략 모델, 가상 아이 1~8명, 실내 공간 |
| 가상 참가자 | 술래 회피·속도 변화·장애물 회피·잡힘 판정, 기존 시선 게임 선택 |
| 캐릭터 동작 | 팔꿈치·무릎 관절, 로컬 ChildACT 모션과 기본 동작 대체 |
| 카메라 | 로봇 시점 JPEG / MJPEG, 640×480, 최대 약 8fps |
| 제어 | Python 및 HTTP에서 이동·회전·정지·텍스트 발화 |
| 관찰 | 자유 시점·상단 시점·로봇 시점, 이동 궤적, 이벤트 로그 |
| 가상 센서 | 4방향 거리, 72방향 LiDAR 거리 배열 |
| 실험 제어 | 일시정지, 0.5×~4× UI 배속, 초기화 |

## 내 Python AI와 연결

서버와 브라우저를 켜 둔 후 **다른 터미널에서 이 저장소를 작업 경로로** 프로그램을 실행합니다.

```python
from simulator.client import SimRobot

robot = SimRobot()
robot.start_game(auto_chase=False)  # 외부 AI가 로봇을 제어할 때
jpeg = robot.camera_frame()  # bytes: 로봇 시점 영상

# jpeg를 자신의 AI에 입력하고, 판단 결과에 따라 명령을 보냅니다.
robot.command_velocity(linear_mps=0.1, angular_rps=0.0, seconds=0.5)
robot.stop()
```

카메라는 브라우저가 렌더링합니다. 탭이 닫혔거나 프레임이 오래되면 영상 API가 `503`을 반환합니다. [AI 연결 문서](docs/AI_INTEGRATION.md)에는 영상 준비 대기, OpenCV 입력, 비동기 명령, 기존 SerBot 스타일의 제어 예제가 있습니다.

## 문서

| 문서 | 내용 |
|---|---|
| [시작하기](docs/QUICKSTART.md) | 실행·화면 사용·포트 변경·자주 생기는 문제 |
| [AI 연결](docs/AI_INTEGRATION.md) | Python 클라이언트, OpenCV, 모델 입출력 연결 |
| [API](docs/API.md) | HTTP 경로·요청 예제·응답·단위·오류 |
| [게임 규칙과 모델](docs/SIMULATION.md) | 방향·터치·도망 판정, 좌표계, 가상 환경의 한계 |
| [구조](docs/ARCHITECTURE.md) | 서버·엔진·브라우저·AI 사이의 데이터 흐름 |
| [개발과 테스트](docs/DEVELOPMENT.md) | 코드 위치, 테스트, GitHub Actions, 수정 시 확인할 점 |
| [외부 라이브러리](THIRD_PARTY_NOTICES.md) | Three.js 버전과 라이선스 |

## 검증

```bash
python3 -m unittest discover -s simulator/tests -v
node --check simulator/static/app.js
node --test simulator/tests/motion.test.mjs
```

자동 테스트가 이동·충돌·카메라 API·술래잡기·기존 시선 게임·모션 보간을 검사합니다. JavaScript 검사에는 Node.js가 필요하며, **시뮬레이터 실행 자체에는 Node.js가 필요하지 않습니다.**

## 실제 로봇과의 차이

로봇과 아이들은 간략한 3D 모델이고, 주행·센서는 근사치입니다. CAD 수준의 치수·동역학, 실제 카메라 노이즈, 실제 사람에 대한 AI 인식 성능을 재현하지 않습니다. 가상 환경에서 통과한 결과는 실제 AGV에서도 별도로 확인해야 합니다.

기본 서버는 `127.0.0.1`에서만 실행됩니다. 이 저장소에는 실제 로봇의 SSH 연결·비밀번호·배포 도구가 들어 있지 않습니다.
