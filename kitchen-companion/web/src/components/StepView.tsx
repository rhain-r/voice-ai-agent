import type { RecipeState } from "../lib/types";

type Props = { recipe: RecipeState; onGoto: (n: number) => void };

export function StepView({ recipe, onGoto }: Props) {
  if (recipe.total === 0) {
    return (
      <section className="step" aria-live="polite">
        <p className="step-text">This recipe has no steps. Ask Chef about the ingredients instead.</p>
      </section>
    );
  }
  return (
    <section className="step" aria-live="polite">
      <p className="step-count">
        Step {recipe.index + 1} of {recipe.total}
      </p>
      <p className="step-text" key={recipe.index}>
        {recipe.steps[recipe.index]}
      </p>
      <ol className="progress" aria-label="Steps">
        {recipe.steps.map((text, i) => (
          <li key={i}>
            <button
              type="button"
              className={i === recipe.index ? "dot current" : i < recipe.index ? "dot done" : "dot"}
              aria-current={i === recipe.index ? "step" : undefined}
              aria-label={`Go to step ${i + 1}: ${text}`}
              onClick={() => onGoto(i + 1)}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}
