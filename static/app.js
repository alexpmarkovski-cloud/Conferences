const state = { category: "", region: "" };
const CATEGORY_NAMES = { ai: "AI", tech: "Tech", finance: "Finance" };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function parseDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatRange(start, end) {
  const s = parseDate(start), e = parseDate(end);
  const opts = { month: "short", day: "numeric" };
  const year = { year: "numeric" };
  if (start === end) return s.toLocaleDateString(undefined, { ...opts, ...year });
  const sameYear = s.getFullYear() === e.getFullYear();
  return `${s.toLocaleDateString(undefined, sameYear ? opts : { ...opts, ...year })} – ${e.toLocaleDateString(undefined, { ...opts, ...year })}`;
}

function countdown(start, end) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((parseDate(start) - today) / 86400000);
  if (days <= 0 && parseDate(end) >= today) return "Happening now";
  if (days === 1) return "Tomorrow";
  if (days < 60) return `In ${days} days`;
  return `In ${Math.round(days / 30)} months`;
}

function place(c) {
  if (c.is_virtual) return "Virtual";
  const loc = [c.city, c.state].filter(Boolean).join(", ");
  const county = c.county ? ` · ${c.county} County` : "";
  return (c.venue ? `${c.venue}, ${loc}` : loc) + county;
}

function card(c) {
  const title = c.url
    ? el("a", { href: c.url, target: "_blank", rel: "noopener noreferrer" }, c.name)
    : c.name;
  return el("article", { class: "card" },
    el("button", { class: "hide", title: "Hide this conference", "aria-label": `Hide ${c.name}`,
                   onclick: () => hide(c.id) }, "×"),
    el("div", { class: "row" },
      el("span", { class: `badge ${c.category}` }, CATEGORY_NAMES[c.category] || c.category),
      el("span", { class: "countdown" }, countdown(c.start_date, c.end_date))),
    el("h3", {}, title),
    el("div", { class: "meta" }, `${formatRange(c.start_date, c.end_date)} · ${place(c)}`),
    c.description ? el("p", { class: "desc" }, c.description) : null);
}

async function load() {
  const params = new URLSearchParams();
  if (state.category) params.set("category", state.category);
  if (state.region) params.set("region", state.region);
  const res = await fetch(`/api/conferences?${params}`);
  const data = await res.json();

  document.getElementById("updated").textContent = data.last_updated
    ? `updated ${new Date(data.last_updated).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`
    : "not updated yet";

  const groups = document.getElementById("groups");
  groups.replaceChildren();
  for (const tier of [3, 2, 1]) {
    const items = data.conferences.filter((c) => c.tier === tier);
    if (!items.length) continue;
    groups.append(el("section", {},
      el("h2", {}, window.TIER_LABELS[tier], el("span", { class: "count" }, ` · ${items.length}`)),
      el("div", { class: "grid" }, ...items.map(card))));
  }
  document.getElementById("empty").hidden = data.conferences.length > 0;
}

async function hide(id) {
  await fetch(`/api/conferences/${id}/hide`, { method: "POST" });
  load();
}

document.querySelectorAll(".seg").forEach((seg) => {
  seg.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
    state[seg.dataset.filter] = btn.dataset.value;
    load();
  });
});

load();
