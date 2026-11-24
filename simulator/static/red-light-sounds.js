// Select cues from the same game state as the on-screen referee signal.
export function redLightCues(previous, state) {
  const game = state.game;
  if (game.mode !== 'red_light' || state.execution_mode === 'stepped' || !previous) return [];
  const friendly = game.gaze_timing === 'friendly';
  if (friendly && (game.phase === 'finished' || game.phase === 'ready' || game.held || state.paused ||
      game.tracking_lost || previous.epoch !== state.epoch)) return [];
  if (previous.epoch !== state.epoch) {
    return game.phase === 'approaching' && game.elapsed < 1 && !state.paused && !game.held ? ['hello'] : [];
  }
  const before = previous.game;
  if (game.phase === 'finished') {
    if (before.phase === 'finished') return [];
    const completed = ['all_eliminated', 'pursuit_complete', 'time_limit'].includes(game.end_reason);
    return [completed ? 'finish' : 'hold'];
  }
  if (game.phase === 'ready') return [];
  const held = state.paused || game.held;
  const wasHeld = previous.paused || before.held;
  const newEvent = name => (state.episode?.events?.[name] || 0) > (previous.episode?.events?.[name] || 0);
  if (held) return wasHeld ? [] : ['hold'];
  if (newEvent('robot_stop')) return ['hold'];
  if (wasHeld) return [game.phase === 'approaching' && !game.escort && !game.watching ? 'chant' : 'resume'];
  if (game.phase === 'escaping') {
    if (before.phase !== 'escaping') return ['chase'];
    return newEvent('catch') ? ['tag'] : [];
  }
  const cues = [];
  if (!before.escort && game.watching !== before.watching) cues.push(game.watching ? 'stop' : 'chant');
  if (newEvent('movement_detected')) cues.push('noticed');
  return cues;
}

export class RedLightVoice {
  constructor() {
    this.context = null;
    this.buffers = new Map();
    this.sources = [];
    this.generation = 0;
    this.stopEndsAt = 0;
  }

  async enable() {
    if (!this.context) {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) throw new Error('Web Audio unavailable');
      this.context = new Context();
      // Warm the time-sensitive cues before the first referee turn.
      for (const name of ['hello', 'chant', 'stop']) this.buffer(name).catch(() => {});
    }
    if (this.context.state !== 'running') await this.context.resume();
  }

  buffer(name) {
    if (!this.buffers.has(name)) {
      const load = async () => {
        const response = await fetch(new URL(`./sounds/${name}.wav`, import.meta.url));
        if (!response.ok) throw new Error(`Sound unavailable: ${name}`);
        return this.context.decodeAudioData(await response.arrayBuffer());
      };
      this.buffers.set(name, load().catch(error => {
        this.buffers.delete(name);
        throw error;
      }));
    }
    return this.buffers.get(name);
  }

  stop() {
    this.generation++;
    for (const {source, gain} of this.sources) {
      const now = this.context.currentTime;
      gain.gain.setTargetAtTime(0, now, .002);
      source.stop(now + .01);
    }
    this.sources = [];
    this.stopEndsAt = 0;
  }

  async play(names, cueGain = 1) {
    if (!names.length || !this.context || this.context.state === 'closed') return;
    // Keep the stop cadence audible if a detection follows on the next poll.
    const append = names[0] === 'noticed' && this.stopEndsAt > this.context.currentTime;
    if (!append) this.stop();
    const generation = this.generation;
    const requestedAt = performance.now();
    const clips = await Promise.all(names.map(name => this.buffer(name)));
    if (generation !== this.generation || this.context.state !== 'running' || performance.now() - requestedAt > 750) return;
    let at = append ? Math.max(this.context.currentTime, this.stopEndsAt) : this.context.currentTime;
    for (const [index, clip] of clips.entries()) {
      const source = this.context.createBufferSource();
      source.buffer = clip;
      const gain = this.context.createGain();
      gain.gain.value = cueGain;
      source.connect(gain);
      gain.connect(this.context.destination);
      source.onended = () => {
        source.disconnect();
        gain.disconnect();
        this.sources = this.sources.filter(active => active.source !== source);
      };
      this.sources.push({source, gain});
      source.start(at);
      at += clip.duration;
      if (names[index] === 'stop') this.stopEndsAt = at;
    }
  }
}
