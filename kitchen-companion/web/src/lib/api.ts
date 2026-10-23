import type { RecipeSummary } from "./types";

export async function listRecipes(): Promise<RecipeSummary[]> {
  const res = await fetch("/api/recipes");
  if (!res.ok) throw new Error("Couldn't load the recipe list.");
  return res.json();
}

// Imports a recipe from a web page. Rejects with the server's own explanation when it can't.
export async function importRecipe(url: string): Promise<RecipeSummary> {
  const res = await fetch("/api/recipes/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : "Couldn't import a recipe from that link.";
    throw new Error(detail);
  }
  return body as RecipeSummary;
}
