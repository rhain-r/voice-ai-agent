import type { KitchenAction, KitchenState } from "../hooks/useKitchenState";
import type { RecipeState } from "../lib/types";
import { EngageButton } from "./EngageButton";
import { IngredientList } from "./IngredientList";
import { StatusOrb } from "./StatusOrb";
import { StepView } from "./StepView";
import { TimerRow } from "./TimerRow";

type Props = {
  state: KitchenState;
  recipe: RecipeState;
  dispatch: (action: KitchenAction) => void;
  send: (type: string, data?: unknown) => void;
  onChangeRecipe: () => void;
  onOpenTranscript: () => void;
};

export function CookMode({ state, recipe, dispatch, send, onChangeRecipe, onOpenTranscript }: Props) {
  const ready = state.connection === "ready";
  const heardCount = state.transcript.filter((l) => l.kind === "heard").length;
  return (
    <div className="cook">
      <header className="cook-head">
        <div className="cook-title">
          <h1>{recipe.title}</h1>
          <button type="button" className="text-button" onClick={onChangeRecipe}>
            Change recipe
          </button>
        </div>
        <StatusOrb activity={state.activity} connection={state.connection} />
      </header>

      <div className="cook-body">
        <div className="cook-main">
          <StepView recipe={recipe} onGoto={(n) => send("goto_step", { n })} />
          <div className="cook-controls">
            <TimerRow timers={state.timers} onAck={() => send("ack_timer")} />
            <EngageButton disabled={!ready} onEngage={() => send("engage")} heardCount={heardCount} />
          </div>
        </div>
        <IngredientList
          recipe={recipe}
          checked={state.checked}
          onToggle={(key) => dispatch({ kind: "toggleIngredient", key })}
        />
      </div>

      <footer className="cook-foot">
        {state.error && (
          <p className="error" role="alert">
            Chef couldn't answer: {state.error}{" "}
            <button type="button" className="text-button" onClick={() => dispatch({ kind: "dismissError" })}>
              Dismiss
            </button>
          </p>
        )}
        <button type="button" className="text-button" onClick={onOpenTranscript}>
          Transcript
        </button>
      </footer>
    </div>
  );
}
