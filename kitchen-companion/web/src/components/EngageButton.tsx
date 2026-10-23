import { useEffect, useState } from "react";

type Props = { disabled: boolean; onEngage: () => void; heardCount: number };

// The big tap target: the next thing said goes to Chef, no wake word needed.
export function EngageButton({ disabled, onEngage, heardCount }: Props) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    setArmed(false); // Chef heard the line the button was for
  }, [heardCount]);

  useEffect(() => {
    if (!armed) return;
    const id = window.setTimeout(() => setArmed(false), 8000);
    return () => window.clearTimeout(id);
  }, [armed]);

  return (
    <button
      type="button"
      className={armed ? "engage armed" : "engage"}
      disabled={disabled}
      onClick={() => {
        setArmed(true);
        onEngage();
      }}
    >
      {armed ? "Listening…" : "Hey Chef"}
    </button>
  );
}
