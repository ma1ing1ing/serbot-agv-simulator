"""Use the fitted timing and cue gain inside the real SerBot's cancellable cycle.

The caller owns the referee phase, live participant tracker and calibrated turn.
Importing this module opens no device. The real control package is loaded only by
run_cycle, which requires an explicit runtime supplied by the caller.
"""
from array import array
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

from simulator.friendly_policy import FriendlyPolicy, features


class CycleInterrupted(Exception):
    """The game stopped, changed phase, or lost fresh participant observations."""


def scaled_wav(source, destination, gain):
    with wave.open(str(source), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE':
            raise ValueError('expected PCM16 cue')
        params = wav.getparams()
        samples = array('h')
        samples.frombytes(wav.readframes(wav.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    samples = array('h', (round(s*gain) for s in samples))
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(destination), 'wb') as out:
        out.setparams(params)
        out.writeframes(samples.tobytes())


class AdaptiveSpeaker:
    """Speaker interface consumed by serbot_control.red_light.perform_cycle."""
    def __init__(self, base, sound_dir, scene, policy):
        self.base, self.sound_dir = base, Path(sound_dir)
        self.scene, self.policy = scene, policy

    def check_output(self):
        self.base.check_output()

    def play(self, cue, check):
        state = self.scene()
        decision = self.policy.decide(state['phase'], state['held'], state['tracks'])
        if decision is None:
            raise CycleInterrupted()
        dwell = decision['away_seconds' if cue == 'chant' else 'watch_seconds']
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / (cue + '.wav')
            scaled_wav(self.sound_dir / (cue + '.wav'), file, decision['cue_gain'])
            check()
            proc = subprocess.Popen(self.base.command + [str(file)], stdin=subprocess.DEVNULL)
            try:
                while proc.poll() is None:
                    check()
                    if time.monotonic() - started > self.base.durations[cue] + 3:
                        raise RuntimeError('speaker timed out')
                    time.sleep(.025)
                if proc.returncode:
                    raise RuntimeError('speaker failed to play '+cue)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
        while time.monotonic()-started < dwell:
            check()
            time.sleep(.025)
        check()


def run_cycle(runtime, direction_to_wheels, read_scene, cancel_check, *, turn_seconds,
              speed=8, audio_device='default', policy=None):
    """One turn-away/back cycle starting at the confirmed facing-players pose.

    read_scene returns mode, phase, held, escort, monotonic observed_at and
    tracks [(distance_m, last_go_speed_mps_or_None), ...]. The timestamp is
    the capture time, including game-state updates, on the same monotonic clock.
    On interruption the caller must re-establish the pose before a new cycle.
    """
    from serbot_control.red_light import SOUND_DIR, Speaker, perform_cycle, plan
    def scene():
        cancel_check()
        state = read_scene()
        if (state['mode'] != 'red_light' or state['phase'] != 'approaching' or
                state['held'] or state.get('escort') or not state['tracks'] or
                not 0 <= time.monotonic()-state['observed_at'] <= .5):
            raise CycleInterrupted()
        features(state['tracks'])  # Validate distances and speeds before any motor command.
        return state

    def check():
        scene()

    try:
        check()
        steps = plan(speed, turn_seconds)
        model = policy or FriendlyPolicy()
        speaker = AdaptiveSpeaker(Speaker(audio_device), SOUND_DIR, scene, model)
        perform_cycle(runtime, speaker, steps, direction_to_wheels, check)
        return True
    except CycleInterrupted:
        return False
    finally:
        runtime.stop()
