# 심청이 주행 모델 연결과 SerBot 실측 설정

[README](../README.md) · [로봇 제어·학습](TRAINING.md) · [API](API.md) · [팀 작업](TEAMWORK.md)

안내견 로봇 주행 모델 **심청이**(Hugging Face `koreashin/simcheongi`)를 이 시뮬레이터에 연결하려고 추가한 기능입니다. **모두 선택 기능이며 기본으로 꺼져 있습니다.** 켜지 않으면 기존 실행·평가·기록 결과는 그대로입니다.

## 바뀐 것

| 기능 | 켜는 방법 | 위치 |
|---|---|---|
| 주행 제한 프리셋 `serbot_measured` | `PlayEnv(physics='serbot_measured')`, HTTP `"physics": "serbot_measured"`, CLI `--physics serbot_measured` | `simulator/motion.py` |
| SerBot 센서 관측 `observation['serbot']` | `PlayEnv(serbot_sensors=True)`, HTTP `"serbot_sensors": true`, CLI `--serbot-sensors` | `simulator/serbot_sensors.py` |
| tick 동기 카메라 | `GET /api/camera/sync.jpg`, `robot.camera_frame_sync(tick)` | `simulator/server.py`, `static/app.js` |
| 심청이 제어기 예제 | `simulator.examples.shimcheong_controller` | 선택 패키지 `simcheongi` 필요 |

CLI 옵션은 `simulator.evaluate`와 `simulator.examples.controller_client`에 추가했습니다. 프리셋 이름 대신 `{"preset": "serbot_measured", "guard_distance": 0.3}`처럼 일부 값만 바꿀 수도 있습니다.

## 그대로인 것

- 기본 주행값, 공통 관측·행동 형식(`schema_version` 1), 게임 규칙, 아이 행동, 기존 카메라 API와 화면은 바꾸지 않았습니다.
- 기준 `main`(커밋 `c780770`)과 이 브랜치에서 같은 결과를 만들어 비교했습니다. 세 게임 각각 `oracle`·`sensor` 평가 보고서(시드 0~3, 20초), 같은 두 모드의 무작위 행동 8초 관측·보상·info 기록, 기록을 켠 4초 판의 기록 파일, CLI `simulator.evaluate` 기본값(시드 0~5, 30초), `tag_comparison`(시드 0~3)입니다. `code_sha256`을 빼면 **모두 바이트 단위로 같습니다.**
- `code_sha256`은 달라집니다. 해시 대상 파일이 바뀌었고 `serbot_sensors.py`를 해시에 추가했기 때문입니다. 결과를 공유할 때는 이 브랜치 커밋을 함께 적습니다([팀 작업](TEAMWORK.md#변경-공유하기)).
- 프리셋 이름을 지정한 경우에만 `physics`에 `"preset"` 키가 붙고, 센서 블록을 켠 경우에만 관측·평가 보고서·기록 설정에 `serbot` 항목이 생깁니다.

## 1. 주행 제한 프리셋 `serbot_measured`

우리 로봇 운전기 소스 `rp_core.py`(비공개, 2026-11-20 판)와 주행 기록에서 가져온 값입니다. **프리셋을 쓴 결과는 다른 환경의 결과**이므로 기본값 결과와 섞어 비교하지 않습니다.

| 설정 | 기본 | `serbot_measured` | 근거 |
|---|---|---|---|
| `max_linear` | 0.5 | 0.5 m/s | 실외 요청 상한 `OUTDOOR_VMAX`는 기본 0.30, 허용 최댓값 0.60 m/s(`rp_core.py:410`), 빠른 단계 0.70 m/s(`:249`). 공통 행동 계약의 상한이 0.5 m/s라서 0.5. 모델을 운용한 속도는 0.25 m/s(`:210` `V_CAP`)이고 심청이 제어기는 기본 0.25로 보냄 |
| `max_angular` | 3 | 0.698 rad/s (40°/s) | 실외 주행 기록 37개(2026-11-19~20, 1개는 빈 기록)의 tick 10,215개 중 4,916개가 `"w_cap_dps": 40`(가장 흔한 값, 나머지 56.4~91.7°/s). 코드 요청 상한은 30°/s(`:211`), 빠른 단계 100°/s(`:253`) |
| `max_acceleration` | 1 | 0.3 m/s² | 추종기 가속 0.30(`:56`) |
| `max_deceleration` | 1.5 | 0.3 m/s² | 명령 감속 `THIN_DEC` 0.30(`:357`). 실측 정지 감속 p10 0.29·p50 0.41·최소 0.20 m/s²(n=30, `:224`) |
| `max_angular_acceleration` | 6 | 2.094 rad/s² (120°/s²) | `THIN_W_RATE`(`:359`) |
| `body_margin` | 0.02 | 0.06 m | `G_OUTLINE`: 몸체 외곽 + 0.06 m 안에 반사가 있으면 정지(`:114`) |
| `guard_distance` | 0.2 | 0.125 m | `G_FRONT_MARGIN`: 범퍼 + 0.125 m(`:112`) |

**넣지 않은 것:** 전방 정지 거리의 속도 항 0.40 s × v(`:113`, 이 시뮬레이터의 가드는 고정 거리), 과속 정지(주행 설정 120°/s, 코드 기본 45°/s `:213`), 바퀴 데드밴드(전진 3.5단위 이하는 초당 2~8 mm, 최소 4단위 `:123`·`:125`), 정지 지연 0.15 s(`:226`), 장애물 근처 감속 구역, 초음파 정지, 탈출 동작. 몸체도 그대로 반지름 0.39 m 원입니다. 실제 몸체는 0.45 × 0.33 m 직사각형(2026-11-18 벽에 몸체를 대고 라이다로 잰 값 0.447 × 0.327 m)이라 시뮬레이터 몸체의 앞쪽이 실제 범퍼보다 약 0.17 m 앞에 있습니다. 운전기 값은 환경 변수로 자주 바뀌었으므로 프리셋은 2026-11-20 시점의 스냅숏입니다.

**기존 기준 제어기에 미치는 영향** (`rule`, 시드 0~19, 아이 5명, 30초, `oracle`, n=20, ± 표준오차):

| 게임 | 기본 task_score | `serbot_measured` task_score |
|---|---|---|
| 술래잡기 | 0.190 ± 0.010 | 0.130 ± 0.022 |
| 얼음땡 | 0.210 ± 0.018 | 0.120 ± 0.022 |
| 무궁화꽃이 피었습니다 | 0.650 ± 0.050 | 0.660 ± 0.046 |

## 2. SerBot 센서 관측 `observation['serbot']`

켜면 매 관측(같은 tick)에 아래 블록이 추가됩니다. 값은 심청이 입력 형식(모델 README와 `simcheongi/geometry.py`)을 따릅니다.

| 필드 | 형식 |
|---|---|
| `schema` | `serbot-sensors/1` |
| `pose` | `{x, y, yaw}` 모델 세계 좌표. x = 시뮬레이터 Z, y = −X, yaw = heading(반시계 +). 원점은 라이다 중심 = 몸체 중심에서 0.025 m 뒤 |
| `lidar_m` | 400개(m). i번 빔 = 정면에서 반시계 i × 0.9°. 0.10 m 미만·12 m 초과는 0.0(반사 없음). 모델이 안에서 360칸으로 묶음 |
| `ultrasonic_m` | 6개(m). 왼쪽·앞왼쪽·앞오른쪽·오른쪽·뒤왼쪽·뒤오른쪽, 센서 위치·방향은 모델의 `ULTRA_LAYOUT`과 같음. 각 센서 ±15° 원뿔 안의 광선 5개 중 최솟값, 4.0 = 반향 없음 |

- `World.ray`와 같은 모양(방 벽, 상자 장애물, 반지름 0.22 m 원인 아이)에 대해 광선을 정확히 계산합니다. 4 cm 간격으로 나아가는 `World.ray`와 0.045 m 이내로 일치하는지 테스트합니다(스치는 광선 제외).
- 세계를 바꾸지 않습니다. 같은 시드·행동에서 켠 환경과 끈 환경의 로봇·아이 상태와 지표가 같은지 테스트합니다. 관측 한 번에 약 1 ms(아이 5~8명, 측정 0.7~1.8 ms)가 걸립니다.
- **근사의 한계:** 잡음·반사·유리·높이가 없습니다(모든 물체가 무한히 높은 기둥). 초음파는 라이다와 같은 물체만 봅니다. 아이는 꽉 찬 원판입니다. 모델 README에 따르면 심청이는 원판 모양 사람에는 잘 반응(판단 변화 0.960 ± 0.011, n=298)하지만 실제 다리 두 개 모양에는 약합니다(0.105 ± 0.020, n=229). 그래서 **이 시뮬레이터는 실제 아이를 피하는 능력을 과대평가할 수 있습니다.**

## 3. tick 동기 카메라

기존 `camera.jpg`는 브라우저가 초당 약 8장 올리는 최신 영상이라 `step()`과 맞지 않습니다. 동기 카메라는 **요청한 tick의 상태로 렌더링한 영상만** 돌려줍니다.

1. Python이 `GET /api/camera/sync.jpg?tick=…&epoch=…&width=1280&height=720&fov=43.3`을 보내면 서버가 요청을 걸어 두고 기다립니다.
2. 열린 시뮬레이터 탭이 `/api/state`에서 요청을 보고, **같은 world lock 안에서 찍은 상태의 tick이 요청 tick과 같을 때만** 렌더링합니다. 단계 실행·일시정지 중에는 아이 위치·자세를 보간 없이 그 상태로 맞춥니다.
3. 탭이 요청 ID와 함께 올린 JPEG만 받아 응답합니다. 헤더 `X-Sim-Tick`, `X-Sim-Time`, `X-Epoch`, `X-Frame-Size`가 붙습니다.

```python
from simulator.client import SimRobot

robot = SimRobot()
try:
    first = robot.training_reset(mode='tag', seed=42, physics='serbot_measured', serbot_sensors=True)
    observation = first['observation']
    jpeg = robot.camera_frame_sync(observation['tick'], width=1280, height=720, fov_deg=43.3)
    step = robot.training_step({'linear_mps': 0.2, 'angular_rps': 0.0})
    jpeg = robot.camera_frame_sync(step['observation']['tick'], width=1280, height=720, fov_deg=43.3)
finally:
    robot.training_close()
```

- 단계 실행(`training_reset`) 또는 일시정지 상태에서만 동작합니다. 세계가 흐르는 중이거나 tick·epoch가 다르면 409, 시간 안에 렌더링되지 않으면 504, 잘못된 값은 400입니다. 크기는 최대 1280 × 960, `fov`는 세로 화각(°)입니다.
- **브라우저 탭이 열려 있고 활성 상태여야 합니다.** 백그라운드 탭은 렌더링을 멈춥니다. 한 장에 상태 확인 주기(65 ms)와 렌더링·JPEG 시간이 더해집니다.
- 카메라 위치는 시뮬레이터 카메라(높이 1.04 m) 그대로이고, 43.3°는 로봇 카메라(1280 × 720)의 공칭 수평 화각 70.4°를 16:9 세로 화각으로 바꾼 값이며 보정하지 않았습니다. 실제 로봇 카메라의 설치 높이는 이 브랜치에서 확인하지 않았습니다. 장면도 단순한 3D 모델이라 **모델이 학습한 영상과 많이 다릅니다.**
- **확인 범위:** 자동 테스트는 가짜 렌더러와 JPEG 형식의 fixture로 서버 프로토콜(tick·epoch·요청 ID 일치, 시간 초과, 거부)을 검사합니다. 이 브랜치를 만든 환경에는 WebGL이 되는 브라우저가 없어 **실제 렌더링 결과는 확인하지 못했습니다.** 처음 쓸 때 브라우저를 열고 위 예제로 tick마다 영상이 바뀌는지 확인하세요.

## 4. 심청이 제어기 예제

[`shimcheong_controller.py`](../simulator/examples/shimcheong_controller.py)는 `SimcheongiPolicy`를 공통 `reset(seed)`·`predict(observation)` 계약으로 감쌉니다.

**설치:** 자신의 가상환경에 Hugging Face `koreashin/simcheongi` 저장소의 코드를 받아 설치합니다(PyTorch 2.8, transformers 5.14.1, Pillow 12.0.0 고정, 자세한 내용은 그 README). 시뮬레이터 기본 실행·테스트에는 필요 없습니다. 설치하지 않고 실행하면 설치 안내가 담긴 `ImportError`가 납니다.

```bash
# 서버 없이 한 판: 회색 영상(카메라 없음), 라이다·초음파·경로는 시뮬레이터 값
python3 -m simulator.examples.shimcheong_controller --game tag --frames blank --device cpu

# 서버와 브라우저 탭을 연 상태에서 tick 동기 영상으로 한 판
python3 -m simulator.examples.shimcheong_controller --game tag --frames sync --device cuda

# 기준 제어기와 같은 조건으로 비교(회색 영상, 모델은 SIMCHEONGI_MODEL·SIMCHEONGI_DEVICE 환경 변수로 지정 가능)
python3 -m simulator.evaluate --game tag --controllers rule --controller simulator.examples.shimcheong_controller:create_controller --physics serbot_measured --serbot-sensors --catch-distance 0.85 --seeds 10000 10001 10002 --time-limit 30
```

Windows에서는 `python3`를 `py`로 바꿉니다. 예제 CLI는 `serbot_measured`, 센서 블록, 잡힘 거리 0.85 m를 자동으로 켭니다.

| 동작 | 구현 |
|---|---|
| 결정 주기 | 0.5 s마다 한 번(학습·로봇과 같음). 사이에는 마지막 5 s 계획을 따라감 |
| 영상 기록 | t0 − 1.5 / −1.0 / −0.5 / 0 s 영상 4장. 이전 결정 때 받은 영상을 쓰고, 기록이 부족하면 첫 영상 |
| 자기 위치 기록 | 0.1 s 간격, 판 시작부터 센 초, 최대 41행(3 s 이상이면 31행 이상) |
| 경로 | 게임이 제공: 로봇에서 가장 가까운 대상 아이까지의 직선(기존 대상에 0.3 m 유지 보정). `route_fn`으로 교체 가능 |
| 추종 | 순수 추종: 앞보기 0.45 m(`rp_core.py:350`), 곡률 분모 최소 0.30 m(`:358`), 끝 0.08 m에서 정지(`:354`), 0.15 m보다 짧은 계획은 대기(`:307`), 110°보다 뒤면 제자리 회전(`:360`), 0.03 m/s 미만은 정지(`:356`) |
| 속도 | min(0.25, 모델의 `speed_hint`), 회전은 프리셋 40°/s로 자름, `guard=True` |
| 무궁화 시선 단계 | 모델에 시선 기능이 없어 기존 `RedLightController`를 40°/s로 잘라 사용. 180° 회전에 약 4.5 s가 걸려 기본 시선 주기(앞보기 1.8 s·뒤돌기 3.2 s)와 맞지 않음 |

```python
from simulator.environment import PlayEnv
from simulator.examples.shimcheong_controller import BlankFrames, ShimcheongController

controller = ShimcheongController(frame_source=BlankFrames(), device='cpu')
env = PlayEnv(game='tag', controller=controller, physics='serbot_measured', serbot_sensors=True)
try:
    env.reset(seed=42, settings={'time_limit': 30, 'catch_distance': 0.85})
    while True:
        observation, reward, terminated, truncated, info = env.step()
        if terminated or truncated:
            break
finally:
    env.close()
```

CPU에서는 결정 하나에 1.5~2.0 s가 걸립니다(모델 README, CPU 32스레드 기준, H100 0.08 s, n이 작은 참고값). 30초 판이면 결정 60번입니다. `PlayEnv`는 추론하는 동안 시간이 흐르지 않습니다. 실시간 서버의 자동 제어(`set_controller`)에 붙이면 추론 동안 세계가 멈추므로 단계 실행을 권장합니다.

## 접촉 없는 잡힘 거리

새 코드는 없고 기존 게임 설정 `catch_distance`(0.67~1.5 m, 기본 0.74 m)를 사용합니다. `serbot_measured`의 가드(0.125 m)가 켜진 로봇은 정면의 아이와 중심 거리 약 0.75~0.79 m에서 멈춰 기본값으로는 잡지 못할 수 있습니다. `settings={'catch_distance': 0.85}`로 두면 시뮬레이터 몸체 사이에 약 0.24 m 간격을 남기고 잡힘으로 판정합니다. 이 값을 바꾼 결과도 다른 조건으로 보고합니다.

## 한계

- **심청이는 게임용 모델이 아닙니다.** 실내 복도·경로 주행용으로 학습했고, 게임·아이·이 시뮬레이터의 영상에서 학습하거나 검증하지 않았습니다. 서 있는 사람을 비켜 가도록 학습했으므로 잡아야 할 아이를 비켜 갈 수 있습니다. 결과는 연결·행동 확인용이며 모델이나 게임 전략의 성능으로 해석하지 않습니다.
- 0.25 m/s로는 도망가는 아이를 따라잡기 어렵습니다. 경로를 그대로 0.25 m/s로 따라가는 가짜 계획기로 술래잡기를 돌리면 60초 동안 한 명도 잡지 못했습니다(시드 3, 아이 2명, n=1, 단순 확인).
- 센서·영상·몸체는 근사입니다(위 2·3절). `--frames blank`는 카메라 입력이 없는 실행입니다.
- 모델은 안전 장치가 아닙니다. 실제 로봇에서는 운전기의 정지 규칙이 늘 함께 돌았습니다. 시뮬레이터에서 통과한 결과도 실제 로봇에서 따로 확인해야 합니다.

## 검증

```bash
python3 -m unittest simulator.tests.test_serbot_options simulator.tests.test_shimcheong simulator.tests.test_sync_camera -v
```

네트워크·GPU·`simcheongi`가 없어도 실행됩니다. `test_serbot_options`는 프리셋 값과 기본값 불변, 센서 배치·좌표계·`World.ray` 일치, 센서를 켜도 같은 동역학, HTTP 옵션을 검사합니다. `test_shimcheong`은 가짜 계획기로 결정 주기·영상 기록·자기 위치 기록·경로·추종 규칙과 설치 안내 오류를 검사합니다. `test_sync_camera`는 로컬 TCP 서버와 가짜 렌더러로 동기 카메라 프로토콜을 검사합니다.
