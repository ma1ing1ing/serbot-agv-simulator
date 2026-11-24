"""Fit a compact referee to counterfactual participant-response simulations."""
import argparse
import hashlib
import json
from pathlib import Path
import random
from statistics import mean

from simulator.friendly_policy import FEATURES, FIXED, LIMITS, MODEL_PATH, features, FriendlyPolicy

FAMILIES = ('steady', 'hesitant', 'quick', 'mixed', 'close_group', 'partly_hidden')
NOVEL = ('slow_and_quick_together', 'near_with_occlusion', 'staggered_start')
# Each grid includes the fixed policy, to allow direct comparison at training time.
CHOICES = ((2.4, 2.8, 3.2, 3.6, 4., 4.3, 4.6),
           (1.2, 1.5, 1.8, 2., 2.2, 2.4, 2.6), (.65, .72, .79, .86, .93, 1.))


def sample(rng, family):
    n = rng.randint(3 if family in ('close_group', 'near_with_occlusion') else 1, 8)
    center = rng.uniform(.9, 2.) if family in ('close_group', 'near_with_occlusion') else rng.uniform(1.2, 8.)
    base = {'hesitant': .3, 'quick': .95}.get(family, rng.uniform(.28, .95))
    hidden = rng.uniform(.25, .65) if family in ('partly_hidden', 'near_with_occlusion') else .08
    first_view = rng.random() < .25
    actors, tracks = [], []
    for i in range(n):
        speed = base * rng.uniform(.68, 1.32)
        if family == 'slow_and_quick_together':
            speed = rng.uniform(.18, .35) if i % 2 == 0 else rng.uniform(.88, 1.4)
        if family == 'mixed':
            speed *= rng.uniform(.5, 1.5)
        distance = max(.7, center + rng.uniform(-1.1, 1.1))
        delay = max(.1, 1.05-.75*speed + rng.uniform(-.25, .45))
        if family == 'staggered_start' and i % 2 == 0:
            delay += rng.uniform(.65, 1.35)
        settle = .45 + .75*speed + rng.uniform(.0, .45)
        actors.append((distance, speed, delay, settle))
        if rng.random() >= hidden:
            pace = None if first_view or rng.random() < .12 else max(0., speed + rng.gauss(0., .09))
            tracks.append((max(0., distance + rng.gauss(0., .12)), pace))
    return actors, tracks


def losses(actors, away, watch, gain):
    """Designer proxies: a meaningful stride, time to settle, and a gentle audible cue."""
    green, red, audio = [], [], []
    for distance, speed, delay, settle in actors:
        stride = speed * max(0., away-delay)
        target = min(1.45, max(.3, distance-.9))
        green.append(2.2 * max(0., target-stride)**2 +
                     .6 * max(0., min(stride, 3.)-max(.6, distance-.8))**2)
        # Budget a short beat after the slower player's stop response.
        red.append(max(0., settle+.5+.32*(distance < 2.)-watch)**2)
        ideal_gain = .65+.35*min(1., max(0., (distance-1.)/5.))
        audio.append((gain-ideal_gain)**2 * (1.6 if gain < ideal_gain else 1.))
    return (.55*max(green)+.45*mean(green)+.095*(away-2.4),
            .65*max(red)+.35*mean(red)+.13*(watch-1.2), mean(audio))


def dataset(seed, count, families):
    rng = random.Random(seed)
    rows = []
    while len(rows) < count:
        family = families[len(rows) % len(families)]
        actors, tracks = sample(rng, family)
        if not tracks:
            continue  # handled by the runtime quiet/hold gate
        labels = []
        for head, candidates in enumerate(CHOICES):
            def score(value):
                action = list(FIXED)
                action[head] = value
                return losses(actors, *action)[head]
            labels.append(min(candidates, key=score))
        rows.append((family, actors, tracks, labels))
    return rows


def evaluate(policy, rows):
    from collections import defaultdict
    by_family = defaultdict(list)
    for family, actors, tracks, labels in rows:
        p = policy.decide('approaching', False, tracks)
        pred = (p['away_seconds'], p['watch_seconds'], p['cue_gain'])
        learned, fixed = losses(actors, *pred), losses(actors, *FIXED)
        by_family[family].append([*learned, *fixed, *(abs(a-b) for a, b in zip(pred, labels))])
    def describe(values):
        names = ['stride_cost', 'settle_cost', 'gain_cost']
        cols = [round(mean(c), 6) for c in zip(*values)]
        return dict(n=len(values), model=dict(zip(names, cols[:3])), fixed=dict(zip(names, cols[3:6])),
                    mae=dict(zip(['away_seconds', 'watch_seconds', 'gain'], cols[6:])))
    return {k: describe(v) for k, v in by_family.items()} | {'overall': describe(sum(by_family.values(), []))}


def main():
    import numpy as np
    import torch
    from torch import nn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=MODEL_PATH)
    parser.add_argument('--report', type=Path, default=Path('artifacts/friendly/training.json'))
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20261124)
    train = dataset(41207, 9000, FAMILIES)
    validation = dataset(51308, 1200, FAMILIES)
    def tensors(rows):
        x = torch.tensor([features(r[2]) for r in rows], dtype=torch.float32)
        y = torch.tensor([[(a-lo)/(hi-lo) for a, (lo, hi) in zip(r[3], LIMITS)]
                          for r in rows], dtype=torch.float32)
        return x, y
    x, y = tensors(train)
    xv, yv = tensors(validation)
    model = nn.Sequential(nn.Linear(len(FEATURES), 32), nn.ReLU(), nn.Linear(32, 24),
                          nn.ReLU(), nn.Linear(24, 3))
    optimizer = torch.optim.Adam(model.parameters(), lr=.002)
    best_loss = float('inf')
    for epoch in range(100):
        for batch in torch.randperm(len(y)).split(192):
            loss = nn.functional.mse_loss(model(x[batch]), y[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            val = nn.functional.mse_loss(model(xv), yv).item()
        if val < best_loss:
            best_loss, best_epoch = val, epoch + 1
            layers = [dict(weight=m.weight.detach().tolist(), bias=m.bias.detach().tolist())
                      for m in model if isinstance(m, nn.Linear)]
    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.model.write_text(json.dumps(dict(format='serbot-friendly-1', features=FEATURES,
                                          limits=LIMITS, layers=layers), separators=(',', ':'))+'\n')
    policy = FriendlyPolicy(args.model)
    test = dataset(62409, 1800, NOVEL)
    report = dict(model_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),
                  seeds=dict(weights=20261124, train=41207, validation=51308, test=62409),
                  train_examples=len(train), train_families=FAMILIES, validation_examples=len(validation),
                  epochs=100, selected_epoch=best_epoch, validation_mse=best_loss,
                  torch_version=str(torch.__version__), numpy_version=np.__version__,
                  validation=evaluate(policy, validation), novel=evaluate(policy, test))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['novel']['overall'], indent=2))


if __name__ == '__main__':
    main()
