# API

[README로 돌아가기](../README.md) · [Python 사용 예제](AI_INTEGRATION.md)

기본 주소는 `http://127.0.0.1:8767`입니다. 서버는 로컬 컴퓨터에만 바인딩합니다. HTTP 클라이언트에 `Host` 헤더는 일반적으로 자동 설정되며, 서버는 `localhost`/`127.0.0.1`과 자신의 포트만 받습니다. 웹 요청의 Origin은 같은 로컬 주소여야 합니다.

JSON POST는 `Content-Type: application/json`이 필요합니다. 요청 본문은 1바이트~1,000,000바이트입니다. 빈 동작도 `{}`를 보냅니다. 예제의 `curl`은 서버 실행 후 다른 터미널에서 실행합니다.

## 카메라

| 경로 | 응답 |
|---|---|
| `GET /api/camera.jpg` | 최신 `image/jpeg`. 준비되지 않았거나 오래된 영상이면 503 JSON. |
| `GET /api/camera/stream.mjpg` | `multipart/x-mixed-replace; boundary=frame` 연속 영상. |
| `GET /api/camera/meta` | 준비 상태, 프레임 번호·가상 시각·크기. |

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

## 로봇 주행

`POST /api/robot/command`

| 필드 | 기본값 | 범위 / 의미 |
|---|---|---|
| `linear_mps` | `0` | -0.5~0.5 m/s, 양수 전진 |
| `angular_rps` | `0` | -3~3 rad/s, 양수 왼쪽 회전 |
| `seconds` | `0.5` | 0.02~30 가상 초 |
| `guard` | `true` | 전후방 20cm 가상 거리 가드 |

속도·시간은 유한한 수여야 합니다. `guard=false`라도 몸체 충돌 처리는 남습니다.

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

`POST /api/robot/stop`은 `{}`를 받아 로봇 명령만 중단합니다. 아이들 움직임이나 세계 시간은 멈추지 않습니다.

`POST /api/robot/say`는 `{"text":"안녕하세요"}`를 받습니다. 최대 200자로 자르고 말풍선·로그에 표시합니다. 브라우저의 음성 옵션을 켠 경우 TTS로도 읽습니다. 실제 스피커 장치에 명령을 보내는 API는 아닙니다.

## 게임과 아이들

| 경로 | 요청 | 의미 |
|---|---|---|
| `POST /api/game/start` | `{}` | 로봇·아이·시간·카메라·명령을 초기화하고 새 게임 시작. 인원·배속 유지. |
| `POST /api/game/hold` | `{"held":true}` | 터치 전 접근만 멈춤. false는 재개. 방향 규칙은 유지. |
| `POST /api/children` | `{"id":0,"mode":"walk"}` | 한 아이의 행동. id 생략 시 전원 적용. |

행동은 `still`(멈춤), `walk`(걷기), `intermittent`(걷다 멈춤), `wiggle`(제자리 움직임)입니다. 게임 중 로봇 전방에 있으면 이 행동보다 시선 정지 규칙이 우선합니다. 터치 후에는 전원 도망 규칙이 우선하며 개별 행동 변경과 `game/hold`를 거부합니다.

시작 전에는 개별 보행으로 센서 입력만 실험할 수도 있습니다. 게임 규칙을 쓰려면 `game/start`를 호출합니다.

## 세계 설정

`POST /api/world/config`는 아래 필드를 부분적으로 받습니다.

```json
{"paused":false,"rate":1,"count":5}
```

- `paused`: 세계 시간·움직임 일시정지. 외부 AI 프로세스는 멈추지 않음.
- `rate`: API 범위 0.25~4. UI 선택지는 0.5, 1, 2, 4.
- `count`: 1~8. 접근 중·도망 중에는 인원 변경 거부.

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
| `phase` | `ready`, `approaching`, `escaping`, `finished` |
| `held` | 접근 수동 멈춤 여부 |
| `touched_by` | 첫 터치 아이 ID(0부터), 터치 전 null |
| `touched_at` | 터치한 가상 시각, 터치 전 null |
| `escaped_ids` | 출발선에 도착한 아이 ID 목록 |

게임 중 `children[].watched`는 전방에 있는지, `escaped`는 출발선 도착 여부입니다. `moving`은 동작/애니메이션 의도이고 장애물 때문에 실제 좌표 이동이 막힐 수도 있습니다. `status`를 영상 AI의 입력으로 쓰면 정답 상태를 함께 제공하게 되므로, 인식 평가 시에는 구분해야 합니다.

## 오류

오류 본문은 보통 `{"error":"설명"}`입니다.

| 코드 | 의미 |
|---|---|
| 400 | 잘못된 값·JSON·Content-Type, 허용되지 않은 게임 단계의 조작 등 |
| 403 | 허용되지 않은 Host/Origin 또는 잘못된 렌더러 세션 |
| 404 | 없는 경로 |
| 409 | 렌더러가 초기화 이전 epoch의 영상을 발행 |
| 503 | 사용할 수 있는 카메라 프레임 없음 |

`GET /api/session`, `POST /api/camera/frame`은 브라우저 렌더러용 내부 프로토콜입니다. 일반 AI 프로그램은 영상을 읽기만 하면 됩니다. 렌더러 토큰은 서버 실행 시 생성되는 임시 값이며, 실제 로봇 인증 정보가 아닙니다.
