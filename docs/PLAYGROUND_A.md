# Playground A 위치 기록 재생

## 사용

서버를 켠 뒤 **놀이 선택 → Playground A · 위치 기록 재생 → 기록 재생**을 선택합니다. 4·8·16명 표시, 세 가지 구간 선택, 재생/일시정지, 시간 막대 이동, 0.5×~16× 배속을 지원합니다. 8×로 시작합니다. 위에서 보는 시점과 **이동 궤적**을 함께 켜면 각 참가자의 색으로 지나온 경로를 확인할 수 있습니다. 끝에서는 멈추며 자동으로 처음으로 순간이동하거나 반복하지 않습니다.

위치 기록은 공통 시간축에서 재생합니다. 참가자별 시간을 따로 0으로 맞추지 않습니다. 술래잡기 규칙·로봇 자동 추격·잡힘 판정·충돌 회피를 기록 좌표에 덧붙이지 않습니다. 로봇을 움직여도 기록된 아이는 반응하지 않습니다. 아이 모델과 팔다리 움직임은 시각화이며 원본에 전신 관절 데이터는 없습니다.

## 원본과 재생 파일 준비

원본: [GraphSD의 익명화 위치 CSV](https://github.com/centeio/GraphSD/blob/c8981a2cfbe5b522275dd29dde58f75afbeec5fe/graphsd/datasets/data/playground_a_position_data_anonymized.csv).

- Git commit: `c8981a2cfbe5b522275dd29dde58f75afbeec5fe`
- SHA-256: `5a87933b243a774f36a7cd28473df33f2e07aabfdda6ff3050d3d3d2e251f62c`
- 열: `id,time,x,y`. 이 배포 파일에는 ID 16개, 위치 64,604행이 있습니다. 논문 모집 인원 18명과 배포 파일의 ID 수를 혼동하지 않습니다.
- 참고: Atzmueller et al., *Mining exceptional social behavior on attributed interaction networks*, 2025, DOI [10.1007/s10994-025-06831-z](https://doi.org/10.1007/s10994-025-06831-z). 원래 수집 연구: Heravi et al., 2018, DOI [10.1145/3212721.3212818](https://doi.org/10.1145/3212721.3212818).

현재 작업 환경에는 원본과 변환 파일을 준비했습니다. 새 체크아웃에서는 다음처럼 다시 만듭니다.

```bash
mkdir -p data/playground_a
curl -fL 'https://raw.githubusercontent.com/centeio/GraphSD/c8981a2cfbe5b522275dd29dde58f75afbeec5fe/graphsd/datasets/data/playground_a_position_data_anonymized.csv' -o data/playground_a/positions.csv
python3 tools/build_playground_replay.py data/playground_a/positions.csv
python3 -m simulator.server
```

변환과 실행에는 Python 표준 라이브러리만 필요합니다. 원본·파생 데이터는 Git에서 제외합니다. 코드 저장소의 라이선스를 아동 데이터의 별도 배포 허용 조건으로 확대 해석하지 않으며, 외부 배포 전 제공 조건을 확인합니다.

## 해석과 처리

배포 CSV에는 좌표 단위와 시간 단위 설명이 없어 이를 실측 미터·초로 확정하지 않습니다. **원본 시간 1단위를 시뮬레이션 1초에 대응**시킨 후 선택한 배속을 적용합니다. 세 재생 구간은 각각 원본 시간값 `4380~4500`, `3780~3900`, `2430~2550`입니다. 화면의 2분은 이 재생 기준의 길이이며 실제 촬영 시간으로 검증된 값이 아닙니다.

선택한 참가자·구간 전체에 하나의 평행이동, 0° 또는 90° 회전, 균일 축척을 적용해 6.8×4.8 가상 미터 안에 맞춥니다. 축별로 따로 늘리거나 참가자별로 다른 배율을 쓰지 않습니다. 이때 가상 미터와 실제 미터의 대응은 검증되지 않았습니다. 아이 모델은 경로를 보기 쉽게 60% 크기로 표시합니다.

연속 표본 사이만 선형 보간합니다. 표본 시간차 중앙값은 1.0이며, 2.5배를 넘는 누락 또는 극단적 좌표 점프에서 경로를 나눕니다. 점프 기준은 원본 단위의 표본 속도에 대해 `max(중앙값 + 20×MAD, 99.5백분위수 × 2)`로 계산합니다. 이 배포본에서는 전이 38개가 나뉩니다. 이는 추적 이상치 후보를 제외하는 처리이며 실제 동작 복원으로 해석하지 않습니다. 분리 구간 사이는 보간하지 않고 해당 참가자를 숨기며 센서에서도 제외합니다. 다시 나타나면 이동선도 새로 시작합니다.

이 자료는 자유 놀이이므로 정지·느린 이동을 포함합니다. 술래/도망자 역할, 태그 시점, 어떤 아이를 쫓는지, 움직인 이유는 제공되지 않습니다. 이 기능으로 술래잡기 전략이나 로봇 대응 정책을 학습했다고 주장하지 않습니다.

## Python과 HTTP

```python
from simulator.client import SimRobot
robot = SimRobot()
robot.start_replay(count=16, clip_id='active')
robot.hold_children(True)
robot.seek_replay(30)
state = robot.status()
print(state['replay'], state['children'][0]['source_id'])
```

| 요청 | 내용 |
|---|---|
| `GET /api/replay` | 로컬 데이터 준비 상태, 참가자 수, 구간, 원본·가정 |
| `POST /api/game/start` | `mode=playground_a`, `replay_count=1~16`, `clip_id=active/group/early` |
| `POST /api/replay/seek` | `elapsed=0~120`, 재생 위치 이동 |
| `POST /api/game/hold` | `held=true/false`, 기록 재생 잠깐 멈춤/계속 |
| `POST /api/world/config` | 기록 재생 중 `rate=0.25~16`, `paused=true/false` |

`state.replay`에는 진행 위치, 원본 시간값, 축척, 구간, 원본 SHA-256과 seek revision이 있습니다. 아이에는 `source_id`, `visible`, `trail`이 추가됩니다. 화면 이동·보간 및 애니메이션 속도는 가상 축척에 따른 값입니다. 숨겨진 아이는 좌표 필드가 남더라도 현재 관측으로 사용하지 마세요.
