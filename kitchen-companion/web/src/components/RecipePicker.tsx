import { type FormEvent, useEffect, useState } from "react";
import { importRecipe, listRecipes } from "../lib/api";
import type { RecipeSummary } from "../lib/types";

type Props = {
  ready: boolean;
  currentTitle: string | null;
  onPick: (id: string) => void;
  onBack: (() => void) | null;
};

export function RecipePicker({ ready, currentTitle, onPick, onBack }: Props) {
  const [recipes, setRecipes] = useState<RecipeSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  useEffect(() => {
    listRecipes().then(setRecipes, (e: Error) => setLoadError(e.message));
  }, []);

  async function onImport(event: FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setImporting(true);
    setImportError(null);
    try {
      const recipe = await importRecipe(url.trim());
      setRecipes((list) => [recipe, ...(list ?? []).filter((r) => r.id !== recipe.id)]);
      setUrl("");
      if (ready) onPick(recipe.id);
    } catch (e) {
      setImportError((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

  return (
    <main className="picker">
      <header className="picker-head">
        <h1>What are we cooking?</h1>
        {onBack && currentTitle && (
          <button type="button" className="text-button" onClick={onBack}>
            Back to {currentTitle}
          </button>
        )}
      </header>

      <form className="import" onSubmit={onImport}>
        <label htmlFor="import-url">Cook from a recipe link</label>
        <div className="import-row">
          <input
            id="import-url"
            type="url"
            inputMode="url"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-describedby={importError ? "import-error" : undefined}
          />
          <button type="submit" disabled={importing || !url.trim()}>
            {importing ? "Importing…" : "Import"}
          </button>
        </div>
        {importError && (
          <p id="import-error" className="import-error" role="alert">
            {importError}
          </p>
        )}
      </form>

      {!ready && <p className="picker-note">Connecting to Chef… you can pick a recipe once it's listening.</p>}
      {loadError && <p className="import-error">{loadError} Check that the bot server is running.</p>}

      <ul className="recipe-list">
        {recipes?.map((r) => (
          <li key={r.id}>
            <button type="button" className="recipe-row" disabled={!ready} onClick={() => onPick(r.id)}>
              <span className="recipe-title">{r.title}</span>
              <span className="recipe-meta">
                Serves {r.servings}
                {r.total_time_min ? `, about ${r.total_time_min} min` : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
