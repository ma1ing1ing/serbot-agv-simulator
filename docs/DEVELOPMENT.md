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
```

기본 테스트 30개는 다음을 확인합니다.

- 선속도·회전, 명령 완료·대체·정지, 가상 시간·배속·일시정지
- 벽/아이 충돌과 거리 가드, 입력 범위·유한값 검사
- 카메라 준비·오래된 프레임·초기화 epoch, 로컬 HTTP 요청 경계
- 1~8명 각각의 전체 게임 완료
- 로봇 전방 정지, 뒤쪽 접근, 돌아보면 다시 정지
- 이동한 로봇 기준의 상대 방향, 각도 감김·정확히 옆의 경계
- 터치한 한 명 때문에 정지 중인 참가자까지 전원 도망
- 터치 후에는 시선 규칙 무시, 중복 터치 방지, 재시작
- 실제 HTTP/Python 제어 명령으로 회전했을 때 아이들의 반응

이 테스트는 내부에 임시 로컬 서버를 열지만 브라우저나 실제 로봇은 필요하지 않습니다. 카메라 프로토콜의 단위 테스트는 JPEG 모양의 fixture를 사용하므로 실제 3D 렌더링 결과를 검증한 것으로 해석하면 안 됩니다.

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
| 시선·터치·도망 규칙 | `simulator/engine.py`의 `World` |
| 로봇 운동·충돌·센서 | `engine.py`의 `tick`, `clearance`, `ray` |
| HTTP 계약 | `simulator/server.py` |
| AI용 Python 인터페이스 | `simulator/client.py` |
| 인물·로봇 3D 외형·카메라 | `simulator/static/app.js` |
| 화면 문구·레이아웃 | `index.html`, `style.css` |

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
