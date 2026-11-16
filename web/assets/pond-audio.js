// Short sound effects for the pond and game.
const PondAudio = (() => {
  const Audio = window.AudioContext || window.webkitAudioContext;
  const buttons = document.querySelectorAll("[data-pond-audio]");
  const key = "bf-pond-audio";
  let enabled = true;
  try { enabled = localStorage.getItem(key) !== "off"; } catch (_) {}

  let audio;
  let output;
  let water;
  let lastResume;
  let lastTap = -Infinity;
  let frogRecording;
  let croakBusy = false;

  // "Frog.ogg" by egomassive, from Craig Smith's field recording (CC0).
  // https://freesound.org/people/egomassive/sounds/536759/
  const frogFile = Audio && document.getElementById("pond-frog-touch")
    ? fetch("assets/frog-call.mp3").then(response => response.ok ? response.arrayBuffer() : null).catch(() => null)
    : null;

  function refreshButtons() {
    for (const button of buttons) {
      button.classList.toggle("hidden", !Audio);
      button.setAttribute("aria-pressed", String(enabled));
      button.title = enabled ? "关闭音效" : "开启音效";
      if (!button.querySelector("svg")) button.textContent = enabled ? "音效：开" : "音效：关";
    }
  }

  function unlock() {
    if (!Audio || !enabled) return;
    try {
      if (!audio) {
        audio = new Audio();
        output = audio.createGain();
        output.gain.value = .26;
        output.connect(audio.destination);
      }
      if (audio.state !== "running") lastResume = audio.resume().catch(() => {});
    } catch (_) { /* Audio may be unavailable in this browser session. */ }
  }

  for (const event of ["pointerdown", "pointerup", "click", "keydown"]) {
    document.addEventListener(event, () => {
      if (!audio || audio.state !== "running") unlock();
    }, { capture: true, passive: true });
  }

  for (const button of buttons) {
    button.addEventListener("click", () => {
      enabled = !enabled;
      try { localStorage.setItem(key, enabled ? "on" : "off"); } catch (_) {}
      if (output) {
        output.gain.cancelScheduledValues(audio.currentTime);
        output.gain.setTargetAtTime(enabled ? .26 : 0, audio.currentTime, .012);
      }
      if (enabled) {
        unlock();
        play("tap");
      }
      refreshButtons();
    });
  }

  function tone(at, duration, from, to, level) {
    const oscillator = audio.createOscillator();
    const envelope = audio.createGain();
    oscillator.frequency.setValueAtTime(from, at);
    oscillator.frequency.exponentialRampToValueAtTime(to, at + duration * .75);
    envelope.gain.setValueAtTime(.0001, at);
    envelope.gain.exponentialRampToValueAtTime(level, at + .009);
    envelope.gain.exponentialRampToValueAtTime(.0001, at + duration);
    oscillator.connect(envelope).connect(output);
    oscillator.start(at);
    oscillator.stop(at + duration + .01);
  }

  function splash(at) {
    if (!water) {
      water = audio.createBuffer(1, Math.ceil(audio.sampleRate * .12), audio.sampleRate);
      const samples = water.getChannelData(0);
      for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1;
    }
    const source = audio.createBufferSource();
    const filter = audio.createBiquadFilter();
    const gain = audio.createGain();
    source.buffer = water;
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(1550, at);
    filter.frequency.exponentialRampToValueAtTime(460, at + .10);
    gain.gain.setValueAtTime(.0001, at);
    gain.gain.exponentialRampToValueAtTime(.1, at + .01);
    gain.gain.exponentialRampToValueAtTime(.0001, at + .12);
    source.connect(filter).connect(gain).connect(output);
    source.start(at);
  }

  async function croak() {
    if (!frogFile || croakBusy) return;
    croakBusy = true;
    const requestedAt = performance.now();
    try {
      if (!frogRecording) {
        const bytes = await frogFile;
        if (bytes) frogRecording = await audio.decodeAudioData(bytes.slice(0));
      }
      if (frogRecording && enabled && !document.hidden && audio.state === "running" &&
          performance.now() - requestedAt < 800) {
        const source = audio.createBufferSource();
        source.buffer = frogRecording;
        source.connect(output);
        source.addEventListener("ended", () => { croakBusy = false; }, { once: true });
        source.start();
        return;
      }
    } catch (_) { /* A missing or unreadable recording should not interrupt the pond. */ }
    croakBusy = false;
  }

  function play(kind) {
    if (!enabled || !output || document.hidden) return;
    if (audio.state !== "running") {
      const requestedAt = performance.now();
      lastResume?.then(() => {
        if (audio.state === "running" && performance.now() - requestedAt < 180) play(kind);
      });
      return;
    }
    const now = audio.currentTime;
    if (kind === "tap") {
      if (now - lastTap < .16) return;
      lastTap = now;
      tone(now, .095, 680, 400, .097);
    } else if (kind === "jump") {
      tone(now, .13, 260, 550, .21);
      tone(now + .018, .11, 420, 780, .055);
    } else if (kind === "land") {
      tone(now, .14, 235, 125, .23);
      splash(now + .008);
    } else if (kind === "croak") {
      croak();
    }
  }

  refreshButtons();
  return { play, supported: Boolean(Audio) };
})();
