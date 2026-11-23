# API

기록·데이터 생성은 [EPISODES](EPISODES.md), Playground A 기록 재생 API와 추가 상태 필드는 [위치 기록 재생](PLAYGROUND_A.md#python과-http)을 참고하세요.

[README로 돌아가기](../README.md) · [Python 사용 예제](AI_INTEGRATION.md)

기본 주소는 `http://127.0.0.1:8767`입니다. 서버는 로컬 컴퓨터에만 바인딩합니다. HTTP 클라이언트에 `Host` 헤더는 일반적으로 자동 설정되며, 서버는 `localhost`/`127.0.0.1`과 자신의 포트만 받습니다. 웹 요청의 Origin은 같은 로컬 주소여야 합니다.

JSON POST는 `Content-Type: application/json`이 필요합니다. 요청 본문은 1바이트~1,000,000바이트입니다. 빈 동작도 `{}`를 보냅니다. 예제의 `curl`은 서버 실행 후 다른 터미널에서 실행합니다.

## 카메라

| 경로 | 응답 |
|---|---|
| `GET /api/camera.jpg` | 최신 `image/jpeg`. 준비되지 않았거나 오래된 영상이면 503 JSON. |
| `GET /api/camera/stream.mjpg` | `multipart/x-mixed-replace; boundary=frame` 연속 영상. |
| `GET /api/camera/meta` | 준비 상태, 프레임 번호·가상 시각·크기. |
| `GET /api/camera/sync.jpg?tick=&epoch=` | 선택. 요청한 tick의 상태로 렌더링한 JPEG. 단계 실행·일시정지 중에만, 열린 탭 필요. `width`·`height`(최대 1280×960), 세로 `fov`, `timeout`. 409/504/400. [상세](SHIMCHEONG.md#3-tick-동기-카메라) |

```bash
curl http://127.0.0.1:8767/api/camera/meta
curl http://127.0.0.1:8767/api/camera.jpg --output camera.jpg
```

메타데이터의 예시 형태입니다. 값은 매 실행마다 달라집니다.

```json
{
  "ready": true,
  "frame_id": 42,
  "age_seconds": 0.08,
  "sim_time": 3.2,
  "width": 640,
  "height": 480,
  "epoch": "world-identifier"
}
```

`ready`는 새 프레임이 2.5초 이내에 도착했고 현재 세계의 `epoch`와 일치할 때만 참입니다. 초기화·게임 재시작은 epoch를 바꿉니다. JPEG 응답의 `X-Frame-ID`, `X-Sim-Time` 헤더는 해당 영상과 짝을 이룹니다. `meta`와 JPEG를 따로 요청하면 서로 다른 프레임일 수 있습니다.

한 장이 없는 경우 `camera.jpg`는 503을 반환합니다. MJPEG는 시작 시 준비되지 않았으면 503이고, 스트리밍 도중 렌더링이 중단되면 연결을 종료할 수 있습니다. 여러 탭을 열면 프레임 발행을 공유하므로, 보통 렌더링 탭 하나만 유지하는 것을 권장합니다.

## 공통 관측과 단계 실행

`GET /api/observation?mode=oracle`은 버전이 있는 공통 관측을 반환합니다. `mode=sensor`는 외부 검출 정보를 사용하고 정답 아이 좌표로 보충하지 않습니다. 관측의 상대 X는 오른쪽, Z는 앞쪽이며 각도·거리·시간 단위와 8명 슬롯/마스크는 [학습 연결](TRAINING.md)을 참고하세요. `/api/state`는 기존 화면·디버깅용 정답 상태이므로 공통 모델 입력과 구분합니다.

| 경로 | 요청 | 응답·의미 |
|---|---|---|
| `POST /api/training/reset` | 아래 예시 | `{observation, info}`. 새로운 독립 단계 실행 판 시작 |
| `POST /api/training/step` | `{"action":{"linear_mps":0.1,"angular_rps":0.0,"guard":true}}` | `{observation,reward,terminated,truncated,info}`. 지정된 행동 간격만 진행 |
| `POST /api/training/close` | `{}` | 단계 실행 종료, 실시간 대기 상태로 복귀 |

```json
{
  "mode": "tag",
  "seed": 42,
  "scenario": "open",
  "count": 5,
  "settings": {"time_limit": 10},
  "observation_mode": "oracle",
  "dt": 0.1,
  "record": false
}
```

`physics` 객체로 공통 주행 제한을 지정할 수도 있습니다. 선택 기능으로 `"physics": "serbot_measured"`(프리셋 이름)와 `"serbot_sensors": true`(관측에 `serbot` 블록 추가)를 받습니다. 두 값은 `POST /api/game/start`에서도 사용할 수 있으며 [심청이 연결](SHIMCHEONG.md)을 참고하세요. 단계 실행 중에는 서버의 실시간 tick이 세계를 진행하지 않으며, 다른 탭의 게임 시작·설정·주행 등 변경 요청은 409를 반환합니다. 로봇 정지, 단계 실행 경로, 관측·검출 등록, 게임 종료는 허용합니다. 학습 중 로봇 정지는 해당 판을 emergency_stop으로 종료합니다. SDK는 초기화 epoch를 후속 요청에 포함하고 오래된 요청은 409로 거부합니다. `training/close`로 명시적으로 해제합니다. 영상 렌더러와 단계 실행은 자동 동기화되지 않으므로 영상의 epoch·가상 시각을 따로 확인해야 합니다.

`info`에는 게임·단계·종료 이유·시드·시나리오·관측 출처·시간·tick과 `metrics`가 있습니다. 지표는 최소 중심 거리, 막힌 이동 시도, 근접 단계 수, 선속도/각속도 변화, 최대 선가속도/각가속도, 표본 수와 누적 보상을 포함합니다. 최소 중심 거리는 몸체 사이 빈 공간을 뜻하지 않습니다.

외부 검출은 `id`, 로봇 기준 `relative_x/relative_z`와 선택적 `relative_vx/relative_vz`를 사용합니다. `robot.set_detections(list)` 또는 로컬 `env.set_detections(list)`로 등록합니다. `record_observation()`은 임의의 실제 모델 입력을 기록하는 기능이며 검출 상태를 바꾸지 않습니다.

Python에서는 `robot.observation(mode='oracle')`, `robot.training_reset(...)`, `robot.training_step(action)`, `robot.training_close()`를 사용합니다. 수치 기반 로컬 학습은 HTTP 없이 `PlayEnv`를 직접 사용할 수 있습니다.

## 로봇 주행

`POST /api/robot/command`

| 필드 | 기본값 | 범위 / 의미 |
|---|---|---|
| `linear_mps` | `0` | -0.5~0.5 m/s, 양수 전진 |
| `angular_rps` | `0` | -3~3 rad/s, 양수 왼쪽 회전 |
| `seconds` | `0.5` | 0.02~30 가상 초 |
| `guard` | `true` | 전후방 20cm 가상 거리 가드 |

속도·시간은 유한한 수여야 합니다. `seconds`는 가속 구간을 포함한 명령 속도 요청 시간이고, 정상 완료는 이후 감속해 멈춘 시점입니다. 가감속 때문에 이동 거리가 속도×시간과 정확히 같지는 않습니다. 명시적 정지·놀이 멈춤·게임 종료는 즉시 정지하는 관리 동작입니다. `guard=false`라도 몸체 충돌 처리는 남습니다.

```bash
curl -X POST http://127.0.0.1:8767/api/robot/command \
  -H 'Content-Type: application/json' \
  -d '{"linear_mps":0.1,"angular_rps":0,"seconds":0.5}'
```

```json
{"id":"command-identifier","epoch":"world-identifier","status":"running"}
```

HTTP 호출은 완료를 기다리지 않고 ID를 반환합니다. `GET /api/command?id=명령ID`로 조회합니다. 서버에는 주행 명령 하나만 활성화됩니다. 새 명령은 이전 명령을 대체합니다.

| 상태 | 의미 |
|---|---|
| `running` | 실행 중 |
| `completed` | 요청 시간 완료 |
| `stopped` | 정지 요청으로 중단 |
| `guard` | 가상 거리 가드로 중단 |
| `collision` | 가상 충돌 방지로 중단 |
| `superseded` | 새 명령으로 대체 |
| `unknown` | 없는 ID, 초기화로 소실, 또는 보관 결과 만료 |

완료 결과는 최근 최대 100개를 보관합니다. 초기화 시 결과도 지워집니다. 완료된 결과에는 완료 가상 시각 `time`이 포함됩니다.

`POST /api/robot/stop`은 `{}`를 받아 로봇 명령과 자동 추격을 중단합니다. 아이들 움직임이나 세계 시간은 멈추지 않습니다. 수동 주행 명령도 자동 추격을 해제합니다. 명령이 끝나도 자동 추격은 재개되지 않습니다.

`POST /api/robot/say`는 `{"text":"안녕하세요"}`를 받습니다. 최대 200자로 자르고 말풍선·로그에 표시합니다. 브라우저의 음성 옵션을 켠 경우 TTS로도 읽습니다. 실제 스피커 장치에 명령을 보내는 API는 아닙니다.

## 게임과 아이들

| 경로 | 요청 | 의미 |
|---|---|---|
| `POST /api/game/start` | `{"mode":"tag","auto_chase":true}` | 새 게임. `mode`는 `tag`(기본), `freeze_tag`, `red_light`. `seed`(정수, 기본 0), `settings`(객체), `record`(bool, 기본 false)를 추가로 받음. 인원·배속 유지. |
| `POST /api/game/auto` | `{"enabled":true}` | 세 게임 진행 중 자동 제어 전환. 진행 중인 수동 명령은 대체. |
| `POST /api/game/hold` | `{"held":true}` | 로봇·아이·게임 제한 시간 멈춤. 세계 시간은 진행. false는 재개. |
| `POST /api/game/finish` | `{}` | 현재 게임 종료, 켜 둔 기록 마감 |
| `GET /api/episode` | 없음 | 저장 여부·폴더·집계·종료 요약 |
| `POST /api/detections` | `{"detections":[{"id":0,"relative_x":0.2,"relative_z":2.0}]}` | sensor 모드의 명시적 외부 검출 입력. 최대 8명, id 중복 불가 |
| `POST /api/episode/observation` | `{"source":"my_model","value":{"frame_id":7}}` | 외부 AI의 실제 관측·검출·프레임 참조 등록 |
| `POST /api/children` | `{"id":0,"mode":"walk"}` | 한 아이의 행동. id 생략 시 전원 적용. |

행동은 `still`(멈춤), `walk`(걷기), `intermittent`(걷다 멈춤), `wiggle`(제자리 움직임)입니다. 진행 중인 술래잡기에서는 아이들이 자체 규칙으로 도망가므로 개별 행동 변경을 거부합니다. 무궁화꽃이 피었습니다에서는 시선·반응 지연·적발 규칙이 우선하고 터치 후 개별 행동 변경을 거부합니다.

`seed`는 0~4294967295 정수이고 `settings`는 [게임 설정](SIMULATION.md#설정과-제어)의 일부 필드입니다. 잘못된 설정은 400이며 진행 중인 게임을 초기화하지 않습니다. `record:true`일 때만 서버의 `artifacts/episodes/`에 저장하며 HTTP에서 저장 경로를 지정하지 않습니다.

시작 전에는 개별 보행으로 센서 입력만 실험할 수도 있습니다. 게임 규칙을 쓰려면 `game/start`를 호출합니다.

## 세계 설정

`POST /api/world/config`는 아래 필드를 부분적으로 받습니다.

```json
{"paused":false,"rate":1,"count":5}
```

- `paused`: 세계 시간·움직임 일시정지. 외부 AI 프로세스는 멈추지 않음.
- `rate`: API 범위 0.25~4. UI 선택지는 0.5, 1, 2, 4.
- `count`: 1~8. 접근 중·도망 중·술래잡기 중에는 인원 변경 거부.

`POST /api/world/reset` (`{}`)은 게임 대기 상태로 초기화합니다. 인원·배속도 기본값으로 돌아갑니다. 현재 명령과 카메라 epoch가 바뀌므로, AI 측에서도 새 상태와 프레임을 기다려야 합니다.

## 센서와 디버깅

| 경로 | 내용 |
|---|---|
| `GET /api/ultrasonic` | `front_min_cm`, `rear_min_cm`, `left_min_cm`, `right_min_cm`, `simulated=true`. |
| `GET /api/lidar` | `ranges` 72개(m), `angle_min/max/increment`, `range_min/max`, `ok`, `simulated`. |
| `GET /api/state` | 로봇·아이·게임·카메라·로그·이동 궤적을 포함한 정답 상태. |

LiDAR의 각도 0은 로봇의 정면이며, 양의 각도는 왼쪽입니다. 몸체 반경을 뺀 가상 광선 거리를 반환합니다. 실제 초음파나 LiDAR의 잡음·반사 특성을 재현한 값은 아닙니다.

`state.game`의 필드:

| 필드 | 의미 |
|---|---|
| `mode` | `tag`, `freeze_tag`, `red_light`, `playground_a` |
| `phase` | `ready`, `chasing`(술래잡기·얼음땡), `approaching`, `escaping`, `finished` |
| `held` | 놀이 참가자 이동 멈춤 여부 |
| `auto_chase` | 규칙 기반 로봇 자동 추격 여부 |
| `target_id` | 자동 추격 대상 아이 ID, 없으면 null |
| `caught_ids` | 현재 잡힌 아이 ID 목록. 얼음 해제 시 제거 |
| `frozen_ids` / `eliminated_ids` | 얼음 / 움직임 적발 탈락 ID 목록 |
| `seed` / `elapsed` / `end_reason` | 시드 / 게임 시간 / 종료 이유 |
| `touched_by` | 첫 터치 아이 ID(0부터), 터치 전 null |
| `touched_at` | 터치한 가상 시각, 터치 전 null |
| `escaped_ids` | 출발선에 도착한 아이 ID 목록 |

게임 중 `children[].watched`는 전방에 있는지, `escaped`는 출발선 도착 여부입니다. `moving`은 게임 중 실제 보행 여부입니다. `state/action/target_id/profile`은 아이의 상태·행동·목표·성향입니다. 최상위 `episode`는 저장 여부·폴더·집계·요약입니다. `status`를 영상 AI의 입력으로 쓰면 정답 상태를 함께 제공하게 되므로, 인식 평가 시에는 구분해야 합니다.

술래잡기에서 `children[].caught`는 잡힘 여부, `speed`는 시뮬 이동 속도(m/s), `motion_kind`와 `motion_time`은 관절 애니메이션의 종류와 재생 위치입니다. 이 위치·속도는 실측 데이터가 아니라 엔진이 생성한 값입니다.

## 오류

오류 본문은 보통 `{"error":"설명"}`입니다.

| 코드 | 의미 |
|---|---|
| 400 | 잘못된 값·JSON·Content-Type, 허용되지 않은 게임 단계의 조작 등 |
| 403 | 허용되지 않은 Host/Origin 또는 잘못된 렌더러 세션 |
| 404 | 없는 경로 |
| 409 | 초기화 이전 영상, 또는 단계 실행 중 허용되지 않는 실시간 상태 변경 |
| 500 | 기록 저장 실패. 저장 공간·쓰기 권한 확인 |
| 503 | 사용할 수 있는 카메라 프레임 없음 |

`GET /api/session`, `POST /api/camera/frame`은 브라우저 렌더러용 내부 프로토콜입니다. 동기 카메라 요청이 걸려 있는 동안에만 `/api/state`에 `camera_sync`가 나타납니다. 일반 AI 프로그램은 영상을 읽기만 하면 됩니다. 렌더러 토큰은 서버 실행 시 생성되는 임시 값이며, 실제 로봇 인증 정보가 아닙니다.

기본 환경은 장애물 없는 `open` 공간입니다. 게임 시작에서 `scenario`를 생략하거나 null로 보내도 `open`을 사용하고 학습 초기화도 기본 `open`입니다. 기존 시나리오 인자는 프로그램 호환을 위해 유지하지만 화면에 환경 배치 선택 메뉴는 제공하지 않습니다.
