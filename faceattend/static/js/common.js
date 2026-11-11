const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
));

const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

async function apiFetch(url, options = {}) {
  const headers = { Accept: "application/json", "X-CSRF-Token": csrfToken() };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  const method = options.method || (body !== undefined ? "POST" : "GET");
  const res = await fetch(url, { method, headers, body, credentials: "same-origin" });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Your session has expired. Please sign in again.");
  }
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON response */ }
  return { ok: res.ok, status: res.status, data };
}

function toast(message, kind = "info") {
  const wrap = document.getElementById("toasts");
  if (!wrap) return;
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  wrap.appendChild(node);
  setTimeout(() => node.remove(), 3500);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("menuToggle")?.addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });
});
