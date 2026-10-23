import type { RecipeState } from "../lib/types";

type Props = {
  recipe: RecipeState;
  checked: Record<string, boolean>;
  onToggle: (key: string) => void;
};

export function IngredientList({ recipe, checked, onToggle }: Props) {
  return (
    <section className="ingredients" aria-labelledby="ingredients-heading">
      <h2 id="ingredients-heading">
        Ingredients{recipe.servings ? `, for ${recipe.servings}` : ""}
      </h2>
      <ul>
        {recipe.ingredients.map((ing, i) => {
          const key = `${recipe.id}:${i}`;
          return (
            <li key={key}>
              <label className={checked[key] ? "ingredient ticked" : "ingredient"}>
                <input type="checkbox" checked={!!checked[key]} onChange={() => onToggle(key)} />
                <span>{ing.text}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
