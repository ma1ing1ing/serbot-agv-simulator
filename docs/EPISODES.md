# 기록 저장과 데이터 생성

[README](../README.md) · [게임 규칙](SIMULATION.md) · [API](API.md) · [학습 연결](TRAINING.md)

## 선택해서 실행하기

서버를 켜거나 게임을 시작하는 것만으로 파일을 저장하거나 여러 판을 생성하지 않습니다. 화면의 **플레이 기록 저장**은 기본으로 꺼져 있습니다. 켜고 시작한 판만 `artifacts/episodes/`에 저장합니다. **게임 종료**, 시간 초과, 규칙에 따른 종료, 초기화, 새 게임, 서버의 정상 종료 시 마감합니다. **로봇 정지**는 아이와 기록을 멈추지 않습니다. 브라우저만 닫으면 서버는 계속 진행합니다. 강제 종료 시 요약은 없을 수 있지만 이미 쓴 JSONL 행은 남습니다.

## 여러 판 생성하기

저장소 루트에서 직접 실행합니다. 서버·브라우저·추가 패키지는 필요하지 않습니다. Windows에서는 `python3` 대신 `py`를 사용합니다.

```bash
# 짧게 확인: 게임별 1판, 최대 10 가상 초
python3 -m simulator.batch --episodes 1 --time-limit 10

# 게임별 100판, 총 300판
python3 -m simulator.batch --episodes 100 --time-limit 120

# 얼음땡만: 8명, 다른 시드와 저장 위치
python3 -m simulator.batch --games freeze_tag --episodes 100 --count 8 --seed 1000 --output artifacts/my-freeze-run
```

기본 인원은 5명이며 `--count`는 1~8입니다. `--seed`는 첫 판의 시드이고 다음 판마다 1씩 증가합니다. 기본 저장 위치는 `artifacts/datasets/날짜-식별자/`입니다. 이미 있는 출력 폴더는 덮어쓰지 않습니다. 같은 시드·인원·설정·코드와 동일한 제어 명령 시점이면 같은 가상 결과를 재현합니다. 외부 AI의 비동기 추론·명령 도착 시각은 별도로 관리해야 합니다.

판 번호의 마지막 자리가 0~7이면 `train`, 8이면 `validation`, 9이면 `test`입니다. 게임별 100판이면 80/10/10판이며 동일 시드는 게임이 달라도 같은 분할에 남습니다. 한 판의 프레임을 섞어 분할하지 않습니다. 별도 실행 결과를 합칠 때는 시드 범위 중복을 확인하세요. 새로운 배치·성향 분포에서의 일반화는 추가 실험으로 평가합니다.

루트의 `manifest.json`은 실행 설정·완료 판 수·상태, `index.jsonl`은 완료된 판의 상대 경로·요약입니다. 각 판은 `분할/게임/시드/` 아래에 저장됩니다. Ctrl+C 시 진행 중인 판을 `batch_interrupted`로 마감하고 manifest를 `interrupted`로 남깁니다. 생성량에 따라 저장 공간이 커지므로 짧은 실행부터 확인하세요. 출력은 Git에서 제외됩니다.

## 한 판의 파일

| 파일 | 저장 내용 |
|---|---|
| `config.json` | 스키마 2·규칙 버전, 로드한 코드 SHA-256, 게임·시드·분할, 단위, 물리·시나리오·행동 간격(`control_dt`), 판정 설정, 초기 배치·장애물·아이별 성향, 합성 출처 |
| `steps.jsonl` | 공통 `time`·`tick`·`game_time`, 로봇과 모든 아이의 `ground_truth`, 입력 관측과 그 시각, 요청 행동과 실제 적용 속도, 종료 여부 |
| `events.jsonl` | 사건 번호·시각·tick·게임 시간, 종류, actor·target, 대상 또는 행위자 위치, 판정 이유·추가 정보 |
| `transitions.jsonl` | `PlayEnv` 기록을 켠 경우 추가. 각 제어 단계의 정확한 입력 관측·요청 행동·다음 관측·보상·종료 신호·시작/종료 시각 |
| `summary.json` | 종료 이유·소요 시간·시점 수·사건별 횟수·잡힘/도착 ID·최소 중심 거리·로봇 이동 거리·충돌/충돌 방지 횟수 |

기록 스키마는 2입니다. 물리는 0.02초 고정 간격, 화면 관찰용 상태 기록은 0.1초 간격입니다. 학습용 `transitions.jsonl`은 `PlayEnv.step()`의 행동 간격을 기준으로 별도 기록하므로 0.1초 상태 행을 임의로 이어 학습 전이로 해석하지 않습니다. 좌표는 바닥 `(x,z)`의 m, 방향은 rad, 시간은 가상 초입니다. 놀이 멈춤 중에는 세계 시간은 흐르지만 `game_time`과 제한 시간은 멈춥니다. 아이의 상태·행동·목표·성향·체력·속도·관절 애니메이션 종류/재생 시간을 함께 저장합니다. `vx/vz`는 직전 **물리 단계 0.02초**의 좌표 차이로 계산한 실제 속도이고 0.1초 평균이 아닙니다. 관절 좌표나 영상 자체는 저장하지 않습니다.

공통 사건은 추격 대상 변경·도망 시작·회피 회전·충돌 방지·제어 전환·게임 시작/종료입니다. 술래잡기는 `catch`, 얼음땡은 `freeze/rescue_attempt/thaw`, 무궁화꽃이 피었습니다는 `gaze_turn/gaze_change/stop_response/movement_detected/touch/escape/catch`를 기록합니다. 같은 잡힘·해제를 매 프레임 중복 기록하지 않습니다.

몸체가 겹치는 이동을 막으므로 정상 실행의 실제 `collision_count`는 0이며 막힌 시도는 `collision_prevented_count`입니다. 최소 거리는 중심 사이 거리입니다. 시간 초과는 `truncated=true`, 규칙상 종료는 `terminated=true`입니다. 사용자 종료·초기화·서버 종료 등은 `end_reason`으로 구분해 학습에서 포함·제외하세요. 마지막 행은 종료 상태이며 수동 종료 시 같은 시각의 마지막 행이 추가될 수 있습니다.

## 외부 AI의 관측 기록

```python
from simulator.client import SimRobot

robot = SimRobot()
robot.start_game('freeze_tag', seed=42, auto_chase=False, record=True)
# 모델에 실제 제공한 입력, 검출 결과 또는 저장한 프레임의 식별자
robot.record_observation({'frame_id': 123, 'detections': []}, source='my_camera_model')
robot.command_velocity(linear_mps=0.1, seconds=0.5)
robot.finish_game()
print(robot.episode())
```

공통 제어 관측은 `source=oracle` 또는 `sensor`로 구분합니다. 외부 AI의 임의 입력 기록은 등록한 사용자 출처와 원래 시각을 유지하고 등록하지 않았으면 정답 관측으로 보충하지 않습니다. 평가용 `ground_truth`를 영상 AI 입력과 섞지 마세요. `record_observation()`의 detections 예시는 기록용이며 sensor 관측에 실제로 반영하려면 별도로 `robot.set_detections(...)`를 호출합니다. 학습 연결에는 예시 보상이 있지만 모델·학습 알고리즘은 포함하지 않으며 자신의 목적에 맞는 보상과 학습 코드를 연결해야 합니다. Playground A 재생은 게임 반응 생성에 사용하지 않고 ChildACT는 선택적인 화면 애니메이션입니다.
