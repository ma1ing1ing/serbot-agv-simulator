"""Render the original red-light game voice with the Python standard library."""

import array
import math
import sys
import wave
from pathlib import Path


RATE = 24000
OUTPUT = Path(__file__).resolve().parents[1] / "simulator" / "static" / "sounds"

# Each syllable has an onset, duration, sliding pitch (Hz), and a vowel colour.
# The approach call groups ten syllables like the Korean chant. The stop
# cadence is separate so the referee can interrupt it at the actual signal.
SCORES = {
    "hello": [(0, .18, 260, 395, "oo"), (.23, .38, 355, 550, "ah")],
    "chant": [(0, .18, 294, 345, "oo"), (.21, .13, 350, 326, "oo"),
              (.38, .22, 330, 445, "ah"), (.65, .14, 440, 396, "oh"),
              (.82, .23, 392, 348, "ee"), (1.17, .20, 350, 463, "ee"),
              (1.40, .15, 465, 413, "oh"), (1.58, .14, 413, 375, "oo"),
              (1.76, .16, 370, 423, "ee"), (1.95, .29, 420, 337, "ah")],
    "stop": [(0, .13, 510, 465, "ee"), (.15, .23, 325, 242, "oh")],
    "noticed": [(0, .10, 335, 410, "oo"), (.14, .27, 390, 525, "ee")],
    "chase": [(0, .16, 240, 335, "oh"), (.19, .13, 330, 415, "ah"),
              (.35, .33, 405, 592, "ee")],
    "tag": [(0, .12, 390, 468, "oh"), (.14, .17, 460, 395, "oo")],
    "finish": [(0, .20, 295, 354, "oo"), (.23, .16, 372, 425, "oh"),
               (.42, .23, 440, 558, "ah"), (.69, .40, 495, 365, "oo")],
    "hold": [(0, .25, 342, 252, "oh"), (.30, .19, 250, 214, "oo")],
    "resume": [(0, .13, 254, 315, "oo"), (.17, .22, 321, 389, "oh")],
}

FORMANTS = {"oo": (410, 850), "oh": (540, 1080), "ah": (760, 1440), "ee": (410, 1980)}


def render(score):
    length = max(onset + duration for onset, duration, *_ in score) + .045
    samples = [0.] * math.ceil(length * RATE)
    for onset, duration, first, last, vowel in score:
        f1, f2 = FORMANTS[vowel]
        pitch = math.sqrt(first * last)
        # A voiced resonator gives all calls the same small, buzzy body.
        weights = []
        for harmonic in range(1, 10):
            hz = pitch * harmonic
            resonance = (1.35 * math.exp(-.5 * ((hz - f1) / 235) ** 2)
                         + .85 * math.exp(-.5 * ((hz - f2) / 320) ** 2))
            weights.append((.42 + resonance) / harmonic)
        norm = sum(weights)
        phase = 0.
        start = round(onset * RATE)
        for i in range(round(duration * RATE)):
            t = i / RATE
            u = t / duration
            glide = u * u * (3 - 2 * u)
            vibrato = .014 * math.sin(math.tau * 7 * t) * min(1., t / .08)
            phase += math.tau / RATE * first * (last / first) ** glide * (1 + vibrato)
            buzz = phase + .12 * math.sin(phase * 1.51)
            voice = sum(w * math.sin(n * buzz) for n, w in enumerate(weights, 1)) / norm
            envelope = min(1., t / .014, (duration - t) / .045)
            samples[start + i] += .40 * envelope * voice
    # A quiet, short body reflection, including a tail for the last syllable.
    echo = round(.028 * RATE)
    pcm = array.array("h", (round(32767 * (v + (.10 * samples[i - echo] if i >= echo else 0.)))
                            for i, v in enumerate(samples)))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


if __name__ == "__main__":
    OUTPUT.mkdir(exist_ok=True)
    for name, score in SCORES.items():
        with wave.open(str(OUTPUT / (name + ".wav")), "wb") as out:
            out.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            out.writeframes(render(score))
