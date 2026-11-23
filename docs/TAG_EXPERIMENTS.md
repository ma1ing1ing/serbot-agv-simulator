# 술래잡기 제어기 실험 · 2026-11-22

이후 진행한 개발 10판의 첫 포획 거리 분석, 접근 속도 후보의 새 시드 평가, PPO 학습 중 포획 집계는 [후속 실험 기록](TAG_FOLLOWUP.md)에 있다.

## 평가 조건

기준 커밋은 `b693db0a680d0ca0c482d0f36066f831fad5eb07`이다. 모든 판은 `tag` 게임에서 장애물 없는 `open` 배치, `oracle` 관측, 기본 물리·게임 설정, 포획 거리 0.74m, 제한 시간 30초, 제어 간격 0.1초, 물리 간격 0.02초를 사용했다. 관측 계약은 v1, 게임 규칙은 `play-rules-2`이다.

- 재현 시드 10000, 10001, 10002. 기존 3판의 평균 포획 비율은 `rule` 20%, `idle` 0%로 재현됐다.
- 개발 시드 11000–11009 (양 끝 포함). 아이 5명으로 후보 선택에 사용했다.
- 최종 시드 21000–21009 (양 끝 포함). 실험 시작 시 따로 정하고, 후보와 보상 설정을 고정한 뒤 성능을 비교했다.

포획 비율은 잡힌 인원/참가 인원의 판별 평균이며, 전원 포획은 성공 판/전체 판이다. 근접은 가장 가까운 아이와 0.8m 미만이었던 물리 단계 수, 회전 변화는 시뮬레이터가 집계한 각속도 절대 변화량의 합(rad/s), 막힘은 로봇 이동이 충돌 방지로 새로 차단된 횟수다. 집계 행에서 이 세 지표는 판당 평균이다.

## 개발 시드 기준 평가

| 시드 | 제어기 | 포획 인원 | 포획 비율 | 전원 포획 | 근접 단계 | 회전 변화 | 막힘 |
|---|---|---:|---:|---:|---:|---:|---:|
| 11000 | rule | 1/5 | 20% | 0/1 | 96 | 32.93 | 0 |
| 11001 | rule | 1/5 | 20% | 0/1 | 87 | 14.66 | 0 |
| 11002 | rule | 1/5 | 20% | 0/1 | 386 | 32.62 | 2 |
| 11003 | rule | 1/5 | 20% | 0/1 | 70 | 32.62 | 0 |
| 11004 | rule | 1/5 | 20% | 0/1 | 39 | 29.05 | 0 |
| 11005 | rule | 1/5 | 20% | 0/1 | 86 | 32.19 | 0 |
| 11006 | rule | 1/5 | 20% | 0/1 | 254 | 23.53 | 3 |
| 11007 | rule | 1/5 | 20% | 0/1 | 100 | 18.79 | 1 |
| 11008 | rule | 2/5 | 40% | 0/1 | 106 | 38.14 | 0 |
| 11009 | rule | 1/5 | 20% | 0/1 | 93 | 31.27 | 1 |
| 11000 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11001 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11002 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11003 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11004 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11005 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11006 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11007 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11008 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| 11009 | idle | 0/5 | 0% | 0/1 | 0 | 0.00 | 0 |
| **10판 평균** | **idle** | 0.0/5 | **0%** | 0/10 | 0.0 | 0.00 | 0.0 |
| **10판 평균** | **rule** | 1.1/5 | **22%** | 0/10 | 131.7 | 28.58 | 0.7 |

## 첫 포획이 늦어진 두 판

`rule`에서 최소·최다 포획 판을 하나씩 골랐다. 동률이면 가장 작은 시드를 사용했다. 포획·표적 전환 시각은 이벤트의 물리 시간이며, 거리는 0.1초 간격의 기록에서 해당 시점에 추격한 표적까지의 중심 거리다.

| 시드 | 포획 시각 (대상 ID) | 시작→첫 포획 | 포획 사이 | 마지막 포획→종료 | 최장 무포획 구간의 표적 거리 |
|---|---|---:|---:|---:|---|
| 11000 (1명) | 25.04초 (0) | 25.04초 | 해당 없음 | 4.96초 | 0.1초에 3.696m, 7.1초에 최대 3.846m, 25.0초에 0.741m |
| 11008 (2명) | 23.30초 (0), 29.56초 (2) | 23.30초 | 6.26초 | 0.44초 | 0.1초에 3.672m, 3.9초에 최대 4.052m, 23.3초에 0.739m |

두 판 모두 시작부터 첫 포획까지가 가장 길었다. 시드 11000에서 표적은 2 → 1 (5.1초) → 0 (7.1초) → 1 (8.2초) → 0 (9.5초) 순이었다. 시드 11008에서도 같은 순서로 3.9, 6.0, 7.1, 9.1초에 바뀌었다. 두 판에서 초반 재전환이 반복되어, 먼저 표적을 바꾸는 데 필요한 거리 차이만 0.3m에서 0.9m로 높여 비교했다.

## 표적 선택과 예측 조준

| 제어기 (5명 × 개발 시드 10개) | 포획 비율 | 전원 포획 | 근접 단계 | 회전 변화 | 막힘 |
|---|---:|---:|---:|---:|---:|
| 기준 `rule` (전환 기준 0.3m, 현재 위치) | 22% | 0/10 | 131.7 | 28.58 | 0.7 |
| `SteadyTagController` (전환 기준 0.9m, 현재 위치) | 16% | 0/10 | 125.4 | 22.30 | 0.9 |
| `LeadTagController` (전환 기준 0.3m, 예측 0.6초) | 20% | 0/10 | 109.7 | 38.43 | 0.6 |

전환에 필요한 거리 차이를 키우자 회전 변화는 줄었지만 포획 비율도 6%p 낮아졌다. 두 번째 실험에서는 기준의 0.3m와 조향·회피 로직을 고정하고, 관측한 상대 위치에 로봇 좌표계의 상대 속도 × 0.6초를 더한 지점을 겨냥했다. 포획 비율이 2%p 낮고 회전 변화도 커서 기본 조준은 현재 위치로 유지한다. 두 개인 후보 중 개발 포획 비율이 높은 예측 조준을 인원별 비교 대상으로 고정했다.

## 인원별 최종 평가

각 인원과 제어기마다 최종 시드 10개를 모두 실행했다. 차이는 같은 인원의 `rule` 대비 백분율 포인트(%p)다.

| 인원 | 제어기 | 포획 비율 | 차이 | 전원 포획 | 차이 | 근접 단계 | 회전 변화 | 막힘 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2 | rule | 30% | — | 0/10 | — | 45.4 | 24.34 | 0.0 |
| 2 | 예측 조준 | 35% | +5%p | 0/10 | 0%p | 57.1 | 26.61 | 0.1 |
| 5 | rule | 20% | — | 0/10 | — | 166.7 | 26.03 | 1.1 |
| 5 | 예측 조준 | 20% | 0%p | 0/10 | 0%p | 159.0 | 32.31 | 0.8 |
| 8 | rule | 11.25% | — | 0/10 | — | 149.7 | 34.18 | 1.0 |
| 8 | 예측 조준 | 11.25% | 0%p | 0/10 | 0%p | 100.1 | 45.99 | 0.2 |

2명에서만 예측 조준이 5%p 높았다(20명 중 7명 대 6명). 5명과 8명에서는 동률이었고, 모든 조건에서 전원 포획은 0판이었다. 인원별로 10판의 결과다.

## PPO 저장·재로딩과 막힘 감점

기존 `MultiInputPolicy`는 `children` 관측 키를 PyTorch 하위 모듈 이름으로 등록하다 실패했다. PPO 예제에서 수치 관측을 관측 공간의 키 순서대로 펼쳐 연결하도록 수정했다. 시드 71로 256단계 학습해 저장한 모델(`cb598c4dcc65`, SHA-256 접두사)을 `PPOController`로 불러와 시드 31000으로 30초 한 판을 마쳤다. 포획은 0/5명이었다.

두 보상 모델 모두 CPU에서 학습 시드 72, 16,384단계(256단계 × 64회 수집), 배치 64, 수집당 4 에포크, 같은 초기화와 아이 5명으로 학습했다. 실제 사용한 에피소드 시드 55개가 서로 같고 최종 평가 시드 10개와 겹치지 않음을 확인했다. 두 모델 모두 같은 `tag` 보상에서 포획 1건에 +1, 초당 −0.01, 근접 단계당 −0.002를 적용했다. 막힘 1회당 감점만 0.05에서 0.10으로 바꿨다.

| 최종 평가 (5명 × 10판) | 모델 SHA-256 앞 12자리 | 학습 중 막힘 합계 | 포획 비율 | 전원 포획 | 근접 단계 | 회전 변화 | 막힘/판 |
|---|---|---:|---:|---:|---:|---:|---:|
| rule | — | — | 20% | 0/10 | 166.7 | 26.03 | 1.1 |
| PPO 감점 0.05 | fce0eadd90ca | 72 | 0% | 0/10 | 0.0 | 2.35 | 0.0 |
| PPO 감점 0.10 | 03eee03dd2e7 | 70 | 0% | 0/10 | 0.0 | 6.07 | 0.0 |

두 모델은 최종 평가에서 포획도 막힘도 0건이었다. 이 학습 예산과 학습 시드 한 개에서는 감점을 높여 얻은 포획 성능 개선이 없었다. 동일 시드의 규칙 제어기가 50명 중 10명을 포획해 술래잡기 기본값은 `rule`을 유지한다.

## 재현 방법

저장소 루트에서 실행한다. 측정 환경은 Python 3.13.12, Gymnasium 1.4.0, NumPy 2.5.5, Stable-Baselines3 2.9.2, PyTorch 2.15.0이다. 기준 측정의 시뮬레이터 코드 해시 접두사는 `ce5f4c8ff7a4`, 최종 코드에서는 `50fb2b0dafef`이다. 최종 코드로 다시 측정해 개발 시드에서 기준·개인 제어기 네 가지의 판별 결과가 앞선 측정과 모두 일치함을 확인했다. 로컬 실행 원본은 `artifacts/tag-backlog/`에 두었다. 각 모델 폴더의 `config.json`에 전체 모델 해시, 물리 설정과 실제 학습 시드 목록이 들어 있다.

**추격 실험.** 아래 명령은 zsh·bash 기준이다. `--output 새경로.json`을 추가하면 판별 결과와 지표가 저장된다.

```bash
python3 -m simulator.evaluate --controllers rule idle --seeds {11000..11009}
for policy in SteadyTagController LeadTagController; do
  python3 -m simulator.evaluate --controllers rule --controller "simulator.examples.tag_pursuit:$policy" --seeds {11000..11009}
done
for count in 2 5 8; do
  python3 -m simulator.evaluate --controllers rule --controller simulator.examples.tag_pursuit:LeadTagController --count "$count" --seeds {21000..21009}
done
```

**포획 지연.** 두 판의 `events.jsonl`에서 `catch`와 `target_change`를 시간순으로 확인한다. `steps.jsonl`에서 `robot_action.target_id`에 해당하는 아이와 로봇의 좌표로 중심 거리를 계산한다.

```python
from simulator.controllers import RuleController
from simulator.environment import PlayEnv

for seed in (11000, 11008):
    with PlayEnv(controller=RuleController()) as env:
        env.reset(seed=seed, count=5, settings={'time_limit': 30},
                  record=True, record_dir=f'artifacts/tag-reproduction/trace-{seed}')
        while env.active:
            env.step()
```

**PPO.** 학습 패키지를 설치하고 다음 코드를 가상환경의 Python에서 실행한다. 실행 시 `OMP_NUM_THREADS=1`을 사용했다. 저장 경로는 새 디렉터리를 지정한다. `run`은 각 평가 판마다 디스크에서 모델을 다시 불러온다. [학습 환경 설치](TRAINING.md)

```python
import json
from functools import partial
from pathlib import Path

from simulator.controllers import RuleController
from simulator.environment import default_reward
from simulator.evaluate import run
from simulator.examples.ppo_controller import PPOController
from simulator.examples.tag_reward import double_blocked_penalty
from simulator.examples.train_ppo import train

root = Path('artifacts/tag-reproduction')
smoke = train(steps=256, seed=71, output=root / 'smoke')
run(seeds=[31000], controllers={'ppo': partial(PPOController, smoke, 'tag')},
    output=root / 'smoke-eval.json')

seeds = range(21000, 21010)
controllers = {'rule': RuleController}
for label, reward in [('ppo-default', default_reward), ('ppo-double', double_blocked_penalty)]:
    model = train(steps=16384, seed=72, reward_fn=reward, output=root / label)
    config = json.loads((model.parent / 'config.json').read_text())
    assert set(seeds).isdisjoint(config['training_episode_seeds'])
    controllers[label] = partial(PPOController, model, 'tag')
run(seeds=seeds, controllers=controllers, output=root / 'ppo-final.json')
```
