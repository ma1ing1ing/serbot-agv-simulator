# 로봇 제어기 연결과 학습용 실행

[README](../README.md) · [팀 작업](TEAMWORK.md) · [HTTP API](API.md) · [기록](EPISODES.md)

## 두 실행 방식

화면과 카메라로 관찰할 때는 기존 `python3 -m simulator.server`와 `SimRobot`을 사용합니다. 서버는 실제 경과 시간에 맞춰 세계를 진행합니다. 학습·반복 평가에서는 아래 `PlayEnv`를 사용합니다. 서버·브라우저가 없어도 실행되고 `step()`을 호출한 만큼만 시간이 흐릅니다. 모델이 추론하는 동안 아이들이 따로 움직이지 않습니다. Windows에서는 명령의 `python3`를 `py`로 바꿉니다.

```bash
# 연결 확인: 10 가상 초, 파일 저장 없음
python3 -m simulator.examples.controller_client --game tag --controller rule

# 다른 팀원의 제어기: 저장소 루트에서 import 가능한 모듈과 생성 함수
python3 -m simulator.examples.controller_client --game freeze_tag --controller my_policy:create_controller
```

기본 시연은 `rule`, 비교용 정지 제어기는 `idle`입니다. 예제는 학습된 모델을 포함하지 않습니다. 자신의 모델을 로드하는 생성 함수를 만들고 `module:factory`로 지정하면 됩니다. 모델별 PyTorch·TensorFlow 등은 각자의 Python 환경에 설치하고 공통 시뮬레이터의 필수 의존성으로 추가하지 않습니다.

## 공통 제어기 계약

```python
class MyController:
    def reset(self, seed=None):
        # 한 판마다 내부 기억·난수 상태를 초기화하고 모델을 준비
        pass

    def predict(self, observation):
        # observation을 모델 입력으로 변환하고 추론 결과를 속도로 변환
        return {'linear_mps': 0.0, 'angular_rps': 0.0, 'guard': False}

def create_controller():
    return MyController()
```

`predict()`는 세계 좌표를 직접 바꾸지 않고 **명령 속도**만 반환합니다. 전진 속도는 -0.5~0.5m/s, 회전 속도는 -3~3rad/s이며 유한한 값이어야 합니다. 양의 전진은 로봇 전방, 양의 회전은 왼쪽입니다. `MotionAction` 객체로 반환할 수도 있습니다. `guard=True`는 추가 전후방 거리 정지이며 생략 시 true입니다. 기본 20cm 가드는 잡힘 거리 0.74m보다 먼저 멈출 수 있어, 게임 제어 비교용 기준 제어기는 `guard=False`를 사용합니다. 이 경우에도 몸체 충돌 방지는 유지합니다. 제어기 비교 시 이 설정도 맞추세요. 실제 적용 속도는 공통 가속·감속·회전 제한과 충돌 방지의 영향을 받으므로 명령과 실제 속도를 구분합니다.

## 직접 환경 사용하기

```python
from simulator.controllers import RuleController
from simulator.environment import PlayEnv

controller = RuleController()  # 이 객체를 자신의 제어기로 교체
env = PlayEnv(game='tag', controller=controller, observation_mode='oracle', dt=0.1)
try:
    observation, info = env.reset(seed=42, scenario='standard', count=5,
                                  settings={'time_limit': 10})
    while True:
        observation, reward, terminated, truncated, info = env.step()
        if terminated or truncated:
            break
finally:
    env.close()
```

`reset()`은 초기 관측·추가 정보를 반환하고, `step()`은 다음 관측·보상·규칙상 종료·시간 초과·추가 정보를 반환합니다. 종료 뒤에는 다시 `reset()`해야 합니다. 기본 행동 간격은 0.1 가상 초이고 내부 물리는 0.02초 단계로 계산합니다. 각 학습 프로세스는 자기 `PlayEnv`를 가지므로 서로의 세계와 시간을 바꾸지 않습니다. 같은 시드·시나리오·설정·행동 순서를 사용하면 결과를 재현할 수 있습니다.

기록은 기본 꺼짐입니다. 필요할 때만 `reset(..., record=True)`를 지정합니다. 데이터 생성 명령과 평가 명령도 직접 실행할 때만 작동합니다. 기본 보상은 게임 진행 보상에서 시간·근접·막힘 비용을 빼는 연결·비교용 예시이며 최적의 놀이를 검증한 값이 아닙니다. 게임 담당자는 `reward_fn(previous_observation, action, observation, info) -> float`로 자신의 목적에 맞는 보상을 연결합니다. `action`은 `MotionAction`이고 `info`의 `event_delta`, `event_counts`, `game_state`를 사용할 수 있습니다. 평가용 상태를 보상 계산에 사용하더라도 제어기의 관측 입력에 섞지는 않습니다. 포획 횟수만 높이는 모델과 급격한 접근을 줄이는 모델은 목표가 다르므로 보상·평가 기준을 결과와 함께 남깁니다.

## 관측과 정답의 구분

관측은 `schema_version`, 공통 시각·tick, 로봇·게임 상태, 참가자 정보, 센서 정보를 포함하는 딕셔너리입니다. 참가자 슬롯은 최대 8명으로 고정하고 `child_mask`로 유효한 슬롯을 구분합니다. 상대 좌표는 로봇 기준 X·Z이며 X는 오른쪽, Z는 앞쪽입니다. `bearing`은 왼쪽이 양수이고 `relative_vx/vz`는 로봇 기준 상대 속도입니다. `relative_vx/vz`는 두 참가자의 평면 속도 차이를 로봇 축으로 표현한 값입니다. 모델 입력 변환은 이 계약을 기준으로 작성하고 슬롯의 0을 실제 아이 좌표로 해석하지 않습니다.

| 모드 | 아이 정보 | 용도 |
|---|---|---|
| `oracle` | 시뮬레이터가 아는 정확한 상대 위치·속도·상태 | 제어 알고리즘 자체의 학습·초기 비교 |
| `sensor` | 명시적으로 전달한 외부 검출 정보. 없으면 아이 위치를 정답으로 채우지 않음 | 자신의 인식 모델과 제어기를 연결하는 실험 |

`oracle`로 학습한 결과를 영상 인식까지 성공한 결과로 설명하면 안 됩니다. `sensor`의 거리 센서도 시뮬레이션 근사치이며 실제 카메라 검출을 대신하지 않습니다. 모델에 실제 제공한 관측과 평가용 정답은 기록에서도 구분합니다.

외부 검출은 `robot.set_detections([{'id': 0, 'relative_x': 0.2, 'relative_z': 2.0}])` 또는 `env.set_detections(...)`로 명시적으로 등록합니다. `relative_vx/vz`도 전달할 수 있으며 등록한 아이는 게임상 상태를 정답에서 가져오지 않고 `unknown`으로 취급합니다. `robot.record_observation(...)`은 실제 입력·프레임 참조를 남기는 별도 기능이며 검출을 등록하지는 않습니다.

브라우저 JPEG는 실시간 화면이 만드는 비동기 영상입니다. 이 문서의 브라우저 없는 단계 실행은 수치 상태 기반이며, 각 `step()`과 새 JPEG 한 장을 자동으로 동기화한 환경은 아닙니다. 영상 실험에서는 프레임의 epoch·가상 시각·번호를 확인해야 합니다.

## 평가할 때 고정할 것

같은 게임의 제어기를 같은 시나리오·시드·인원·물리 설정·행동 간격·관측 모드로 비교합니다. 시뮬레이터 버전, 모델 버전, 보상 설정도 함께 보관합니다. 학습에 사용하지 않은 배치와 아이 행동 유형을 평가에 남기며, 시드만 바꾼 결과를 새로운 행동 분포에 대한 검증으로 간주하지 않습니다. 게임별 성과와 최소 거리·막힌 이동·급격한 속도/회전 변화 등 공통 지표를 함께 확인합니다.


## 공통 주행 설정

모든 제어기는 같은 주행 처리를 사용합니다. `PlayEnv(physics={...})` 또는 단계 실행 HTTP 초기화의 `physics`로 설정합니다. 아래 값은 프로젝트의 **가정값**이며 실제 AGV의 측정값은 아닙니다. 물리 설정을 바꾼 결과는 같은 조건의 결과와 구분해 보고합니다.

| 설정 | 기본값 | 단위 |
|---|---|---|
| `max_linear` / `max_angular` | 0.5 / 3 | m/s / rad/s |
| `max_acceleration` / `max_deceleration` | 1 / 1.5 | m/s² |
| `max_angular_acceleration` | 6 | rad/s² |
| `body_margin` / `guard_distance` | 0.02 / 0.2 | m |
| `enabled` | true | false는 이상적인 즉시 속도 적용으로 이전 동작 비교용 |

## Gymnasium 연결(선택)

강화학습 도구와 연결할 때만 추가 의존성을 설치합니다. 일반 서버·로컬 제어기 실행에는 필요하지 않습니다.

```bash
python3 -m pip install -e '.[training]'
```

Windows PowerShell에서는 `py -m pip install -e ".[training]"`로 실행할 수 있습니다. `simulator.gym_env.GymPlayEnv(game='tag')`가 같은 학습 환경을 감쌉니다. Gym 어댑터의 기본 `guard=False`는 기준 제어기와 같으며 `guard=True`로 추가 거리 정지를 선택할 수 있습니다. 행동은 `[linear_mps, angular_rps]`인 길이 2의 연속 배열이고 관측은 수치 배열로 구성된 딕셔너리입니다. 일반 제어기의 공통 딕셔너리와 Gymnasium용 수치 관측은 서로 다른 표현입니다. 동기화된 RGB 렌더 모드는 제공하지 않으며 상태 기반 학습용입니다. 환경 어댑터가 있다고 학습 모델이나 학습이 자동으로 생성되는 것은 아닙니다.

## HTTP로 단계 실행하기

서버 화면과 함께 상태를 관찰하려면 다음처럼 연결할 수 있습니다. 단계 실행 중에는 실시간 시간이 따로 흐르지 않고 다른 실시간 변경 요청을 제한합니다. 끝나면 반드시 해제합니다.

```python
from simulator.client import SimRobot

robot = SimRobot()
try:
    initial = robot.training_reset(mode='tag', seed=42, scenario='standard',
                                    count=5, dt=0.1, settings={'time_limit': 10})
    result = robot.training_step({'linear_mps': 0.1, 'angular_rps': 0.0})
finally:
    robot.training_close()
```


## 같은 조건에서 제어기 비교

```bash
# 결과를 화면에 출력하며 플레이 기록·결과 파일은 저장하지 않음
python3 -m simulator.evaluate --game tag --group test --seeds 0 1 --controllers rule idle --time-limit 30

# 필요할 때만 결과 JSON 저장
python3 -m simulator.evaluate --game tag --group test --seeds 0 1 --controllers rule idle --time-limit 30 --output artifacts/evaluation.json
```

| 시나리오 그룹 | 배치 |
|---|---|
| `train` | `standard`, `open` |
| `validation` | `staggered`, `obstacle_course` |
| `test` | `cross_room`, `dense` |

특정 배치는 `--scenario cross_room dense`로 선택할 수 있습니다. 시나리오는 장애물·참가자 배치와 아이 행동 유형을 바꾸며, 유효한 몸체 간격을 검사합니다. 사용자 제어기는 `--controller my_policy:create_controller`로 추가합니다. 각 제어기·배치·시드 조합은 별도 환경에서 실행하며 게임 성과는 같은 게임 안에서만 집계합니다. 상세 기본값과 지원 옵션은 `python3 -m simulator.evaluate --help`로 확인합니다.

일반 주행의 변화량·최대 가속도 지표는 게임 종료·명시적 정지 같은 관리 목적 정지를 제외합니다. `administrative_stops`는 해당 정지 횟수이고, 몸체/거리 가드 정지는 `emergency_stops`·`max_emergency_deceleration`으로 따로 집계합니다. 최소 중심 거리와 0.8m 미만 근접 단계 수는 가정에 따른 진단값이며 실제 안전성 인증 지표가 아닙니다.

HTTP 학습 중 **로봇 정지**는 해당 판을 `emergency_stop`으로 종료합니다. 다시 학습하려면 `training_reset()`을 호출합니다. **실시간으로 돌아가기**는 `training_close()`와 같으며 학습 판을 마감하고 대기 상태로 돌아갑니다.

`PlayEnv(controller=...)`는 제어기를 한 판마다 초기화하고 `step()`에서 호출하며, 오류가 나면 판을 중단합니다. 직접 `step(action)`을 호출할 때는 외부 모델이 행동을 선택한 것으로 취급합니다. 각 `PlayEnv`는 초기화 epoch를 소유하며, 같은 World를 다른 환경이 재설정하면 이전 환경의 요청은 거부됩니다. 평가 JSON에는 코드 SHA-256·물리·행동 간격·관측/시나리오 버전과 제어기 클래스가 포함됩니다. 제어기의 `model_version` 속성을 지정하면 함께 기록하고, 없으면 unspecified로 표시합니다.
