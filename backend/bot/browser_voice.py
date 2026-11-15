"""An isolated Web Audio microphone: remote meeting sound cannot feed it."""
SCRIPT = r"""
(() => {
  if (!navigator.mediaDevices || window.__wilcoMic) return;
  const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  const context = new AudioContext({sampleRate: 48000});
  const microphone = context.createMediaStreamDestination();
  // Keep a silent, live track even between replies. Never connect to speakers.
  const silence = context.createConstantSource();
  silence.offset.value = 0;
  silence.connect(microphone);
  silence.start();
  let source = null;
  window.__wilcoMic = {
    playing: false,
    stop() {
      if (source) { source.onended = null; try { source.stop(); } catch {} source.disconnect(); source = null; }
      this.playing = false;
      window.__charchaSpeaking = false;
    },
    async play(encoded) {
      this.stop();
      await context.resume();
      const bytes = Uint8Array.from(atob(encoded), character => character.charCodeAt(0));
      const buffer = await context.decodeAudioData(bytes.buffer);
      if (!buffer.length || buffer.duration > 45) throw new Error('Invalid speech duration');
      source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(microphone);
      source.onended = () => this.stop();
      this.playing = true;
      window.__charchaSpeaking = true;
      source.start();
      return {duration: buffer.duration, sample_rate: buffer.sampleRate};
    },
  };
  navigator.mediaDevices.getUserMedia = async constraints => {
    if (!constraints?.audio) return original(constraints);
    const stream = constraints.video ? await original({...constraints, audio: false}) : new MediaStream();
    stream.addTrack(microphone.stream.getAudioTracks()[0].clone());
    return stream;
  };
})();
"""
