const KEY = "kitchen_id";
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

// This tablet's kitchen: the server keeps the recipe position and timers under this id,
// so they survive the tablet sleeping or the Wi-Fi dropping.
export function kitchenId(): string {
  const existing = readStored();
  if (existing) return existing;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const id = Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join("");
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // Private mode: this session still works, it just won't resume after a reload.
  }
  return id;
}

function readStored(): string | null {
  try {
    const value = localStorage.getItem(KEY);
    return value && /^[A-Za-z0-9_-]{16}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}
