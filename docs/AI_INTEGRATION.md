# AI 프로그램 연결

[README로 돌아가기](../README.md) · [API](API.md) · [게임 규칙](SIMULATION.md)

## 역할

시뮬레이터는 3D 공간과 가상 센서를 제공합니다. 자신의 AI가 영상을 읽고 판단한 다음 로봇 명령을 보냅니다. 아래 코드는 연결 예제이며 인식 모델이나 놀이 AI가 아닙니다.

## 카메라 준비 대기

서버를 실행하고 브라우저 탭을 열어 둡니다. 초기화 직후, 탭을 닫은 경우, 2.5초 이상 새 프레임이 없는 경우에는 카메라를 준비된 것으로 취급하지 않습니다.

```python
import time
from simulator.client import SimRobot, SimulationError

robot = SimRobot()
deadline = time.monotonic() + 10
while not robot.camera_metadata()["ready"]:
    if time.monotonic() >= deadline:
        raise RuntimeError("시뮬레이터 탭을 열고 활성화하세요")
    time.sleep(0.1)

jpeg = robot.camera_frame()
print(len(jpeg), "bytes")
```

촬영 메타데이터에는 `frame_id`, `sim_time`, `epoch`가 있습니다. 새로운 영상인지, 어느 가상 시각의 영상인지 확인할 때 사용합니다. JPEG 응답 헤더에는 `X-Frame-ID`, `X-Sim-Time`도 포함됩니다. 메타데이터와 JPEG를 별도 호출하면 그 사이 프레임이 바뀔 수 있습니다. 프레임과 정확히 짝을 맞춰야 하면 JPEG 응답의 헤더를 직접 읽으세요.

## OpenCV로 한 장 읽기

OpenCV와 NumPy는 자신의 AI 개발 환경에 따로 설치합니다. 시뮬레이터 서버 자체에는 필요하지 않습니다.

```python
import cv2
import numpy as np
from simulator.client import SimRobot

robot = SimRobot()
jpeg = robot.camera_frame()
image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
if image is None:
    raise RuntimeError("JPEG 디코딩 실패")
# image: BGR, uint8, 480 × 640 × 3
# 자신의 AI 모델에 image를 전달합니다.
```

## MJPEG 연속 입력

```python
import cv2
from simulator.client import SimRobot

robot = SimRobot()
capture = cv2.VideoCapture(robot.camera_stream_url)
try:
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        # frame을 자신의 AI에 전달합니다.
finally:
    capture.release()
    robot.stop()
```

브라우저 렌더링이 중단되면 스트림도 종료될 수 있습니다. 실제 AI 프로그램에서는 준비 상태를 확인하고 다시 연결하는 처리를 넣습니다. 브라우저 카메라 설정은 로봇 3D 위치·방향을 따르며, 관찰자 화면의 자유 시점을 바꿔도 AI 카메라 방향은 바뀌지 않습니다.

## 로봇 동작

SI 단위를 사용합니다. 선속도는 m/s, 각속도는 rad/s, 시간은 가상 초입니다. 양의 각속도는 왼쪽 회전입니다.

```python
from simulator.client import SimRobot

robot = SimRobot()
try:
    robot.command_velocity(linear_mps=0.1, seconds=0.5)
    robot.command_velocity(angular_rps=1.0, seconds=1.0)
finally:
    robot.stop()
```

기본적으로 명령이 끝날 때까지 기다립니다. AI의 영상 처리를 계속하려면 `wait=False`로 즉시 반환받고 이후 새 판단으로 명령을 갱신할 수 있습니다.

```python
command = robot.command_velocity(
    linear_mps=0.0,
    angular_rps=0.5,
    seconds=0.3,
    wait=False,
)
# 이 시점에 다른 영상 처리가 가능합니다.
# 새 명령은 이전 명령을 대체합니다. 누적 대기열이 아닙니다.
```

명령을 지나치게 자주 덮어쓰면 요청한 시간이 끝나기 전에 대체됩니다. 적절한 제어 주기를 정하고, 프로그램 종료·예외 처리에서 `stop()`을 호출합니다. GUI의 일시정지는 외부 Python의 추론이나 `time.sleep()`을 멈추지 않습니다.

## 기존 SerBot 스타일

```python
from simulator.client import SimRobot as SerBot

robot = SerBot.from_env()
robot.forward(speed=6, seconds=0.5)
robot.backward(speed=6, seconds=0.5)
robot.spin_left(speed=5, seconds=0.4)
robot.spin_right(speed=5, seconds=0.4)
robot.drive(linear=6, angular=2, seconds=0.5)
robot.wheels(6, -6, seconds=0.5)
```

속도 단위 1을 기본 `0.025m/s`, 회전 속도 단위 1을 기본 `0.24rad/s`로 환산합니다. **실제 AGV에서 측정한 보정값은 아닙니다.** `SimRobot(metres_per_speed=..., radians_per_speed=...)`으로 바꿀 수 있습니다. 편의 메서드의 속도 범위는 -10~10입니다.

`sequence()`는 사전 목록이나 `to_dict()` 메서드가 있는 동작 객체를 받습니다. 실제 로봇 라이브러리 전체와 호환되는 것은 아니며 SSH·배포·하드웨어 진단은 제공하지 않습니다.

## 게임과 센서

```python
robot.start_game(auto_chase=False)  # 술래잡기 시작, 로봇은 직접 만든 AI로 제어
robot.hold_children(True)        # 놀이 참가자 이동 잠깐 멈춤
robot.hold_children(False)       # 이동 재개
robot.say("안녕하세요")          # 화면 텍스트, 선택적 브라우저 TTS
distances = robot.ultrasonic()   # cm, 전후좌우
scan = robot.lidar_scan()        # m, 72방향
```

기본 모드는 술래잡기입니다. 시연용 자동 추격은 정답 위치를 사용하므로 영상 AI 평가에서는 끕니다. 수동 주행·정지 명령도 자동 추격을 해제하며, 명령 종료 후 자동으로 켜지지 않습니다. 필요하면 `robot.auto_chase(True)`로 시연을 재개합니다.

기존 놀이는 `robot.start_game('red_light')`로 선택합니다. 이 모드에서 터치 후에는 전원 도망 규칙을 유지하기 위해 `hold_children()`이 오류를 반환합니다. 세계 전체 일시정지는 GUI나 HTTP 설정 API로 할 수 있습니다.

## 영상 AI 평가 시 구분할 것

`robot.status()`는 아이의 실제 좌표, `watched`, `escaped`, 터치한 아이 등의 **정답 상태**를 포함합니다. 디버깅에는 쓸 수 있지만 영상 인식 성능을 시험할 때 모델 입력으로 섞으면 평가가 달라집니다.

가상 아이들은 단순 3D 인체 모델입니다. 실제 사람 영상으로 학습한 인식·포즈 추정 모델이 이 영상을 잘 인식한다고 보장할 수 없습니다. 가상 영상과 실제 로봇 영상의 차이를 별도로 확인하세요.
