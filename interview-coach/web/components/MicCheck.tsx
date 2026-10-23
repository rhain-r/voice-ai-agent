"use client";

import { useEffect, useRef, useState } from "react";

type Status = "idle" | "listening" | "blocked";

export function MicCheck() {
  const [status, setStatus] = useState<Status>("idle");
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState(false);
  const cleanup = useRef<() => void>(() => {});

  useEffect(() => () => cleanup.current(), []);

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      let frame = 0;
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let peak = 0;
        for (const v of data) peak = Math.max(peak, Math.abs(v - 128) / 128);
        setLevel(peak);
        if (peak > 0.12) setHeard(true);
        frame = requestAnimationFrame(tick);
      };
      tick();
      cleanup.current = () => {
        cancelAnimationFrame(frame);
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
      };
      setStatus("listening");
    } catch {
      setStatus("blocked");
    }
  }

  function stop() {
    cleanup.current();
    setStatus("idle");
    setLevel(0);
  }

  if (status === "blocked") {
    return (
      <p className="mic-meter" role="alert">
        Your browser blocked the microphone. Allow it from the icon in the address bar, then reload.
      </p>
    );
  }

  if (status === "idle") {
    return (
      <button type="button" className="button quiet" onClick={start}>
        Test my microphone
      </button>
    );
  }

  return (
    <div className="mic-meter">
      <div className="bar" aria-hidden>
        <div className="fill" style={{ transform: `scaleX(${Math.min(1, level * 2.5)})` }} />
      </div>
      <span aria-live="polite">{heard ? "Sounds good — we can hear you." : "Say something…"}</span>
      <button type="button" className="button quiet" onClick={stop}>
        Done
      </button>
    </div>
  );
}
