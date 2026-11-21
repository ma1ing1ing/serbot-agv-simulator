# 개발과 테스트

[README로 돌아가기](../README.md) · [구조](ARCHITECTURE.md)

## 개발 환경

Python 3.10 이상을 사용합니다. 서버와 테스트는 표준 라이브러리만 사용합니다. JavaScript 문법 검사에는 Node.js가 필요합니다.

```bash
python3 -m simulator.server
```

서버 코드를 바꾸면 서버를 재시작하고, HTML·CSS·JS를 바꾸면 브라우저를 새로고침합니다. Three.js는 저장소에 고정되어 있어 `npm install` 단계는 없습니다.

## 자동 테스트

```bash
python3 -m unittest discover -s simulator/tests -v
node --check simulator/static/app.js
node --check simulator/static/motion.js
node --test simulator/tests/motion.test.mjs
```

Python 테스트는 기존 로봇·시선 게임 검증에 술래잡기와 HTTP 요청 처리 검증을 추가합니다. 모션 테스트는 원본에서 변환한 로컬 데이터가 있을 때 주기 경계·유한한 관절 값·실제 변화량을 검사합니다.

- 선속도·회전, 명령 완료·대체·정지, 가상 시간·배속·일시정지
- 벽/아이 충돌과 거리 가드, 입력 범위·유한값 검사
- 카메라 준비·오래된 프레임·초기화 epoch, 로컬 HTTP 요청 경계
- 1~8명 각각의 전체 게임 완료
- 얼음 해제·정지 지연 적발·시드/배속 재현성·세 게임의 시간 초과
- 저장 기본 꺼짐·기록 4개 파일·분할 시드 중복 방지·중단 시 마감(임시 폴더에서만 검증)
- 로봇 전방 정지, 뒤쪽 접근, 돌아보면 다시 정지
- 이동한 로봇 기준의 상대 방향, 각도 감김·정확히 옆의 경계
- 터치한 한 명 때문에 정지 중인 참가자까지 전원 도망
- 터치 후에는 시선 규칙 무시, 중복 터치 방지, 재시작
- 실제 HTTP/Python 제어 명령으로 회전했을 때 아이들의 반응
- 술래잡기에서 시선과 무관하게 이동, 가까우면 도주, 개별 잡힘·종료
- 자동 추격과 수동 명령 인계, 정지 후 자동 재출발 방지
- 인원 1·5·8명과 배속 1·4에서 충돌·좌표 범위
- 로컬 ChildACT 파일 제공과 모션의 재생 주기 경계
- Playground A 공통 시간축 보간·누락 숨김·시간 이동·종료·기존 게임 전환 (`test_replay.py`)

이 테스트는 내부에 임시 로컬 서버를 열지만 브라우저나 실제 로봇은 필요하지 않습니다. 카메라 프로토콜의 단위 테스트는 JPEG 모양의 fixture를 사용하므로 실제 3D 렌더링 결과를 검증한 것으로 해석하면 안 됩니다.

포트 열기 권한이 제한된 실행 환경에서는 아래 비네트워크 검사를 사용할 수 있습니다. `RouteTests`는 실제 HTTP 요청 파서와 핸들러를 메모리 입출력으로 실행합니다. TCP 연결과 브라우저 렌더링 검사를 대신하지 않습니다.

```bash
python3 -m unittest simulator.tests.test_simulator.WorldTests simulator.tests.test_simulator.GameTests simulator.tests.test_tag_game simulator.tests.test_http_routes simulator.tests.test_replay simulator.tests.test_games simulator.tests.test_recording simulator.tests.test_contracts simulator.tests.test_motion simulator.tests.test_child_reactions simulator.tests.test_scenarios simulator.tests.test_evaluation simulator.tests.test_environment simulator.tests.test_training_routes simulator.tests.test_gym_env -v
node --test simulator/tests/motion.test.mjs
```

## 브라우저와 실제 렌더링 연결 검사

서버와 활성 브라우저 탭을 켠 상태에서 별도 실행합니다.

```bash
python3 -m unittest simulator.tests.live_camera_check -v
```

이 검사는 **가상 세계를 전후로 초기화**합니다. 다른 AI 실험을 진행 중일 때 실행하지 마세요. 실제 렌더링 JPEG, 아이들 보행에 따른 좌표 변화, 로봇 회전에 따른 카메라 변화, MJPEG 수신을 확인합니다.

기본 테스트와 이 검사는 역할이 다릅니다. 서버 테스트가 통과해도 브라우저의 WebGL 지원이나 실제 AI 모델 인식 성공까지 보장하지 않습니다.

## 수정할 위치

| 바꾸려는 것 | 위치 |
|---|---|
| 공통 관측·행동 | `simulator/contracts.py` |
| 제어기·학습용 단계 실행 | `simulator/controllers.py`, `simulator/environment.py` |
| 로봇 공통 운동 | `simulator/motion.py` |
| 시나리오·평가 | `simulator/scenarios.py`, `simulator/evaluate.py` |
| 세 게임의 행동·판정 | `simulator/games.py` |
| 술래잡기 이동 경로·자동 추격 | `simulator/games.py` |
| 기록·명시적 데이터 생성 | `simulator/recording.py`, `simulator/batch.py` |
| ChildACT 변환 | `tools/build_childact_motion.py`, [변환 설명](CHILDACT.md) |
| 관절 모션 보간 | `simulator/static/motion.js` |
| 세계 시간·명령·센서 | `engine.py`의 `tick`, `clearance`, `ray` |
| HTTP 계약 | `simulator/server.py` |
| AI용 Python 인터페이스 | `simulator/client.py` |
| 인물·로봇 3D 외형·카메라 | `simulator/static/app.js` |
| 화면 문구·레이아웃 | `index.html`, `style.css` |

[팀 작업 규약](TEAMWORK.md)에 따라 공통 환경 변경과 모델별 실험 코드를 분리합니다. 제어기 연결 예제는 `python3 -m simulator.examples.controller_client`이며 파일을 저장하지 않습니다. API와 물리 설정을 바꿀 때는 관측/행동 계약·재현성·기록 정합성 테스트를 함께 확인합니다.

규칙을 바꾸면 대응 테스트와 [게임 규칙 문서](SIMULATION.md)를 함께 수정합니다. API 변경 시 [API 문서](API.md)와 Python 클라이언트도 맞춥니다. 화면 문구는 짧고 기능 중심으로 유지합니다.

## Python 패키지

`pyproject.toml`로 선택적 편집 설치나 wheel 빌드가 가능합니다. 패키지에는 서버·클라이언트·예제와 정적 화면/Three.js 자산이 포함됩니다. 테스트·미리보기 스크린샷·문서는 저장소에 보관하지만 런타임 패키지에는 포함하지 않습니다.

```bash
python3 -m pip install -e .
serbot-sim --port 8770
```

## 저장소 관리

`artifacts/`는 영상 저장과 로컬 실행 결과용이며 Git에서 제외합니다. `.venv`, `__pycache__`, `.env`도 제외합니다. 로봇 비밀번호, 개인 실험 영상, 계정 토큰을 커밋하지 않습니다. `docs/assets/preview.jpg`는 가상 인물만 들어 있는 화면 예시입니다.

현재 저장소는 시뮬레이터만 독립적으로 담습니다. 원래 참고한 실제 로봇 제어 저장소의 Git 이력·SSH 설정·진단/배포 도구는 포함하지 않습니다.


## 공통 환경 기준과 자동 검증

공통 환경 작업 전 기존 비네트워크 테스트 92개가 통과한 상태를 기준으로 확인했습니다. 새 가감속 동작과 구분해 기존 이상적 운동의 단위·방향 회귀는 `physics.enabled=False`로 유지하고, 기본 가감속·단계 실행·제어기 교체·센서 관측·전이 정렬은 별도 테스트로 확인합니다. 패키지 버전은 0.2.0이며 저장 결과의 코드 SHA-256과 계약·규칙·시나리오 버전으로 실제 사용한 환경을 구분합니다.

`.github/workflows/tests.yml`은 Windows/macOS/Linux × Python 3.10/3.12와 Gymnasium·PPO 검사 작업을 정의합니다. PPO 검사는 임시 폴더에서 256단계만 학습해 저장·불러오기·기본 제어기와 비교 연결을 확인하며 성능 검증은 아닙니다. 로컬에서는 학습 패키지 설치 후 `python3 -m unittest simulator.tests.test_gym_env simulator.tests.test_ppo_example -v`로 실행합니다. 파일 추가만으로 원격 실행이나 다른 컴퓨터 검증이 완료된 것은 아닙니다. GitHub에 반영한 뒤 Actions 결과를 확인하세요. 로컬 포트가 제한된 환경에서는 TCP 기반 APITests와 실제 브라우저 검사가 별도로 필요합니다. 선택 패키지가 없으면 해당 Gymnasium·PPO 통합 검사를 건너뛰며 일반 시뮬레이터는 그대로 실행됩니다.
