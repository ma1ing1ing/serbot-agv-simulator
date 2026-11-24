import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {redLightCues, RedLightVoice} from '../static/red-light-sounds.js';

function snapshot(game = {}, events = {}, other = {}) {
  return {epoch: 'round', execution_mode: 'realtime', paused: false,
    game: {mode: 'red_light', phase: 'approaching', watching: true, elapsed: 0, ...game},
    episode: {events}, ...other};
}

test('start once, chant on actual permission to move, stop on actual watch', () => {
  const ready = snapshot({phase: 'ready'}, {}, {epoch: 'lobby'});
  const watch = snapshot();
  const turning = snapshot({looking: false});
  const away = snapshot({watching: false});
  assert.deepEqual(redLightCues(ready, watch), ['hello']);
  assert.deepEqual(redLightCues(watch, turning), []);
  assert.deepEqual(redLightCues(turning, away), ['chant']);
  assert.deepEqual(redLightCues(away, away), []);
  assert.deepEqual(redLightCues(away, watch), ['stop']);
  assert.deepEqual(redLightCues(null, away), []);
});

test('referee and pursuit events play once, with interruption and finish taking precedence', () => {
  const away = snapshot({watching: false});
  const detection = snapshot({escort: {stage: 'pickup'}}, {movement_detected: 1});
  const chase = snapshot({phase: 'escaping'});
  const caught = snapshot({phase: 'escaping'}, {catch: 1});
  const finished = snapshot({phase: 'finished', end_reason: 'pursuit_complete'}, {catch: 2});
  const held = snapshot({held: true, watching: false});
  assert.deepEqual(redLightCues(away, detection), ['stop', 'noticed']);
  assert.deepEqual(redLightCues(detection, detection), []);
  assert.deepEqual(redLightCues(away, chase), ['chase']);
  assert.deepEqual(redLightCues(chase, caught), ['tag']);
  assert.deepEqual(redLightCues(caught, finished), ['finish']);
  assert.deepEqual(redLightCues(finished, finished), []);
  assert.deepEqual(redLightCues(away, held), ['hold']);
  assert.deepEqual(redLightCues(held, held), []);
  assert.deepEqual(redLightCues(held, away), ['chant']);
  assert.deepEqual(redLightCues(away, snapshot({}, {robot_stop: 1})), ['hold']);
  assert.deepEqual(redLightCues(away, snapshot({phase: 'finished', end_reason: 'user_stopped'})), ['hold']);
  for (const mode of ['freeze_tag', 'tag', 'playground_a']) {
    assert.deepEqual(redLightCues(away, snapshot({mode})), []);
  }
  assert.deepEqual(redLightCues(away, snapshot({}, {}, {execution_mode: 'stepped'})), []);
});

test('reset or mute cancels a cue even while its WAV is loading', async () => {
  const voice = new RedLightVoice();
  voice.context = {state: 'running', currentTime: 0,
    createBufferSource() { throw new Error('a stale cue reached the speaker'); }};
  let deliver;
  voice.buffer = () => new Promise(resolve => { deliver = resolve; });
  const pending = voice.play(['chant']);
  voice.stop();
  deliver({duration: 2});
  await pending;
});

test('each cue ships as non-silent, unclipped PCM', async () => {
  for (const name of ['hello', 'chant', 'stop', 'noticed', 'chase', 'tag', 'finish', 'hold', 'resume']) {
    const wav = await readFile(new URL(`../static/sounds/${name}.wav`, import.meta.url));
    assert.equal(wav.toString('ascii', 8, 12), 'WAVE');
    assert.equal(wav.readUInt16LE(20), 1);
    assert.equal(wav.readUInt32LE(24), 24000);
    let peak = 0;
    for (let i = 44; i < wav.length; i += 2) peak = Math.max(peak, Math.abs(wav.readInt16LE(i)));
    assert(peak > 3000 && peak < 32000, name);
  }
});

test('learned referee stays quiet outside play and follows the actual gaze cue', () => {
  const active = snapshot({gaze_timing: 'friendly'});
  const away = snapshot({gaze_timing: 'friendly', watching: false});
  assert.deepEqual(redLightCues(snapshot({}, {}, {epoch: 'lobby'}), active), []);
  assert.deepEqual(redLightCues(active, away), ['chant']);
  assert.deepEqual(redLightCues(away, active), ['stop']);
  for (const end of [{phase: 'finished'}, {phase: 'ready'}, {held: true}, {tracking_lost: true}]) {
    assert.deepEqual(redLightCues(away, snapshot({gaze_timing: 'friendly', ...end})), []);
  }
});
