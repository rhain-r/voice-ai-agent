// Browser speech recognition and speech synthesis, shared by both demo sites.

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const tts = window.speechSynthesis;

export const now = () => performance.now() / 1000;
export const canListen = Boolean(Recognition);
export const canSpeak = Boolean(tts);

const MIC_ERRORS = {
  "not-allowed": "Microphone access is blocked. Allow it from the address bar, or type instead.",
  "service-not-allowed": "This browser won't run speech recognition here. Type instead.",
  "audio-capture": "No microphone was found. Connect one, or type instead.",
  network: "Speech recognition in this browser needs a network connection. Check it, or type instead.",
};

const wordsOf = (text) => new Set(text.toLowerCase().match(/[a-z0-9']+/g) ?? []);

export function createVoice({ onNotice = () => {}, onState = () => {} } = {}) {
  const voice = {
    handler: null, // {final(seg), interim(text)} of the page using it
    speakEnabled: canSpeak,
    wanted: false,
    speaking: false,
    utteranceStart: null,
    startedWhileSpeaking: false,
    lastHeardAt: -Infinity,
    recent: [], // [{words, end}] of recent replies, to drop our own voice coming back through the mic
    rec: null,

    start() {
      if (!Recognition) return;
      this.wanted = true;
      if (!this.rec) this.rec = this.build();
      this.safeStart();
      onState();
    },

    build() {
      const rec = new Recognition();
      rec.lang = "en-US";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (e) => {
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const text = e.results[i][0].transcript.trim();
          if (this.utteranceStart == null) {
            this.utteranceStart = now();
            this.startedWhileSpeaking = this.speaking;
          }
          this.lastHeardAt = now();
          if (e.results[i].isFinal) {
            const seg = { text, start: this.utteranceStart, end: now(), startedWhileSpeaking: this.startedWhileSpeaking };
            this.utteranceStart = null;
            if (text) this.handler?.final(seg);
          } else {
            this.handler?.interim?.(text);
          }
        }
      };
      rec.onerror = (e) => {
        if (MIC_ERRORS[e.error]) {
          this.wanted = false;
          onNotice(MIC_ERRORS[e.error]);
          onState();
        }
      };
      rec.onend = () => {
        if (this.wanted) setTimeout(() => this.wanted && this.safeStart(), 250);
      };
      return rec;
    },

    safeStart() {
      try { this.rec.start(); } catch { /* already running */ }
    },

    stop() {
      this.wanted = false;
      this.rec?.stop();
      onState();
    },

    // Our own reply picked up by the microphone: mostly the same words, heard during or just after it.
    isEcho(seg) {
      const heard = [...wordsOf(seg.text)];
      if (!heard.length) return false;
      return this.recent.some((r) => seg.start <= r.end + 4 &&
        heard.filter((w) => r.words.has(w)).length / heard.length >= 0.7);
    },

    // Speaks and resolves with when speech started and ended (seconds on the page clock).
    speak(text, onStart) {
      return new Promise((resolve) => {
        const asked = now();
        const words = wordsOf(text);
        if (!this.speakEnabled || !tts) {
          onStart?.(now());
          this.recent = [{ words, end: now() }];
          resolve({ start: asked, end: now() });
          return;
        }
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-US";
        u.rate = 1.05;
        u.voice = tts.getVoices().find((v) => v.lang === "en-US" && v.localService) ?? null;
        let started = null;
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          clearTimeout(fallback);
          this.speaking = false;
          this.recent = [{ words, end: now() }];
          onState();
          resolve({ start: started ?? asked, end: now() });
        };
        u.onstart = () => {
          started = now();
          this.speaking = true;
          this.recent = [{ words, end: Infinity }];
          onState();
          onStart?.(started);
        };
        u.onend = finish;
        u.onerror = finish;
        // Some browsers never fire onend without an audio device; don't wait on them forever.
        const fallback = setTimeout(() => { if (started == null) onStart?.(now()); finish(); }, 2500 + text.length * 90);
        tts.cancel();
        tts.speak(u);
      });
    },

    cancel() {
      tts?.cancel();
    },
  };
  return voice;
}
