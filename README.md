# SerBot AGV 시뮬레이터

SerBot AGV용 AI를 개발할 때 사용하는 로컬 3D 시뮬레이터입니다. 가상 아이들의 움직임과 로봇 시점의 영상을 제공하고, 외부 Python 프로그램에서 로봇을 제어할 수 있습니다.

**AI 모델은 포함하지 않습니다.** 영상 인식, 구호, 로봇의 회전·추격 판단은 직접 작성합니다. 시뮬레이터는 환경과 가상 참가자의 반응을 담당합니다.

![시뮬레이터 화면](docs/assets/preview.jpg)

## 실행

필요한 환경: **Python 3.10 이상**, **WebGL을 지원하는 브라우저**. 서버 실행에 필요한 Python 추가 패키지는 없습니다. Three.js도 저장소에 포함되어 있습니다.

```bash
git clone https://github.com/ma1ing1ing/serbot-agv-simulator.git
cd serbot-agv-simulator
python3 -m simulator.server
```

브라우저에서 **<http://127.0.0.1:8767>**을 엽니다. Windows에서는 `python3` 대신 `py` 또는 `python`을 사용합니다. 종료는 서버 터미널에서 `Ctrl+C`입니다.

> `simulator/static/index.html`을 파일로 직접 열면 동작하지 않습니다. Python 서버를 실행한 뒤 위 HTTP 주소로 접속해야 합니다. 카메라 영상을 받는 동안 브라우저 탭을 활성 상태로 유지하세요.

## 구현된 게임 규칙

1. **게임 시작**을 누릅니다. 로봇은 처음에 아이들을 바라봅니다.
2. 로봇이 **뒤돌아 있으면** 아이들이 다가옵니다.
3. 로봇이 **바라보면** 아이들이 멈춥니다.
4. 한 명이 술래인 로봇을 **터치하면 전원이 도망갑니다.** 이때는 로봇이 바라봐도 멈추지 않습니다.
5. 모두 출발선에 돌아오면 게임이 끝납니다. **새 게임**으로 다시 시작합니다.

처음에는 아이들이 멈춰 있는 것이 정상입니다. 수동 회전 버튼이나 자신의 AI 프로그램으로 로봇을 돌리세요. 로봇이 자동으로 돌아보는 AI는 들어 있지 않습니다.

## 기능

| 기능 | 내용 |
|---|---|
| 3D 공간 | SerBot AGV 간략 모델, 가상 아이 1~8명, 실내 공간 |
| 가상 참가자 | 접근·시선에 따른 정지·터치 후 전원 도망, 터치 전 개별 행동 설정 |
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
```

자동 테스트 30개가 이동·충돌·카메라 API·게임 전환·로봇 방향에 따른 아이들의 반응을 검사합니다. JavaScript 문법 검사에는 Node.js가 필요하며, **시뮬레이터 실행 자체에는 Node.js가 필요하지 않습니다.**

## 실제 로봇과의 차이

로봇과 아이들은 간략한 3D 모델이고, 주행·센서는 근사치입니다. CAD 수준의 치수·동역학, 실제 카메라 노이즈, 실제 사람에 대한 AI 인식 성능을 재현하지 않습니다. 가상 환경에서 통과한 결과는 실제 AGV에서도 별도로 확인해야 합니다.

기본 서버는 `127.0.0.1`에서만 실행됩니다. 이 저장소에는 실제 로봇의 SSH 연결·비밀번호·배포 도구가 들어 있지 않습니다.
