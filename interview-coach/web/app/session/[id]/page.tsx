"use client";

import {
  LiveKitRoom,
  RoomAudioRenderer,
  useLocalParticipant,
  useRoomContext,
  useTextStream,
  useTrackVolume,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import type { LocalAudioTrack } from "livekit-client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { LatencyStrip } from "@/components/LatencyStrip";
import { SpeakerRing } from "@/components/SpeakerRing";
import { Transcript } from "@/components/Transcript";
import { loadConnection } from "@/lib/api";
import type { Progress, TurnLatency } from "@/lib/types";

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [connection, setConnection] = useState<{ token: string; livekit_url: string } | null | undefined>();
  const [micError, setMicError] = useState(false);

  useEffect(() => setConnection(loadConnection(id)), [id]);

  if (connection === undefined) return null;
  if (connection === null) {
    return (
      <main className="page">
        <div className="notice">
          <h2>This interview link has expired</h2>
          <p>
            Interview links only work in the tab that started them. <Link href="/">Start a new interview</Link>, or{" "}
            <Link href={`/report/${id}`}>see this one&apos;s scorecard</Link>.
          </p>
        </div>
      </main>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={connection.livekit_url}
      token={connection.token}
      connect
      audio
      video={false}
      onDisconnected={() => router.push(`/report/${id}`)}
      onMediaDeviceFailure={() => setMicError(true)}
    >
      <RoomAudioRenderer />
      <InterviewRoom micError={micError} />
    </LiveKitRoom>
  );
}

function lastJson<T>(streams: { text: string }[]): T | null {
  const last = streams[streams.length - 1];
  try {
    return last ? (JSON.parse(last.text) as T) : null;
  } catch {
    return null;
  }
}

function InterviewRoom({ micError }: { micError: boolean }) {
  const { state, audioTrack, agent } = useVoiceAssistant();
  const room = useRoomContext();
  const { microphoneTrack } = useLocalParticipant();
  const agentVolume = useTrackVolume(audioTrack);
  const micVolume = useTrackVolume(microphoneTrack?.track as LocalAudioTrack | undefined);
  const transcriptions = useTranscriptions();
  const { textStreams: progressStreams } = useTextStream("coach.progress");
  const { textStreams: metricStreams } = useTextStream("coach.metrics");

  const progress = lastJson<Progress>(progressStreams);
  const turns = useMemo(
    () =>
      metricStreams.flatMap((s) => {
        try {
          return [JSON.parse(s.text) as TurnLatency];
        } catch {
          return [];
        }
      }),
    [metricStreams],
  );

  return (
    <main className="page">
      <header className="session-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 3vw, 2.2rem)" }}>
            {progress ? `Question ${progress.index + 1} of ${progress.total}` : "Getting started"}
          </h1>
          {progress && <p className="progress-line">About {progress.competency}</p>}
          {progress && (
            <div className="progress-steps" aria-hidden>
              {Array.from({ length: progress.total }, (_, i) => (
                <span key={i} data-state={i < progress.index ? "done" : i === progress.index ? "current" : "todo"} />
              ))}
            </div>
          )}
        </div>
        <button className="button end" type="button" onClick={() => void room.disconnect()}>
          End interview
        </button>
      </header>

      {micError && (
        <div className="notice" role="alert">
          <h2>We can&apos;t use your microphone</h2>
          <p>Allow microphone access from the icon in the address bar, then reload this page.</p>
        </div>
      )}

      <div className="stage">
        <div className="ring-wrap">
          <SpeakerRing state={state} agentVolume={agentVolume} micVolume={micVolume} />
          <LatencyStrip turns={turns} />
        </div>
        <Transcript entries={transcriptions} agentIdentity={agent?.identity} />
      </div>
    </main>
  );
}
