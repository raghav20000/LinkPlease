const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  getStats: () => request("/stats"),
  listRules: () => request("/rules"),
  createRule: (keyword, dm_message) =>
    request("/rules", { method: "POST", body: JSON.stringify({ keyword, dm_message }) }),
};
