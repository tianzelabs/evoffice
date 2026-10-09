// The side panel: chat, the boss's input box, the leaderboard. Plain DOM --
// text, input and scrolling are what HTML is for; the canvas draws the room.
import { getJSON, OfficeEvent, sayAsBoss, whoami } from "./net";

const $ = <T extends HTMLElement>(s: string) => document.querySelector(s) as T;
const esc = (s: unknown) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const roleOf: Record<string, string> = {};

function who(actor: string) {
  const r = roleOf[actor] ?? (actor === "office" ? "office" : actor.startsWith("trader") ? "trader" : actor);
  return `<span class="who-${r}">${esc(actor)}</span>`;
}

function line(e: OfficeEvent): string | null {
  const p = e.payload, a = who(e.actor);
  switch (e.kind) {
    case "say": return `${a}${p.to ? " → " + esc(p.to) : ""}: ${esc(p.text)}`;
    case "open": return `<span class="sys">${a} opened #${p.position} ${p.side} ${p.size} @ ${p.entry_px}</span>`;
    case "close": return `<span class="sys">${a} closed #${p.position} (${p.reason}) · net <span class="${p.pnl >= 0 ? "pos" : "neg"}">${p.pnl} (${p.pnl_bps} bps)</span></span>`;
    case "hire": return `<span class="sys">${esc(p.employee)} joined as ${esc(p.role)}</span>`;
    case "wake": return `<span class="sys">${a} woke: ${esc((p.reasons || []).join("; "))}</span>`;
    case "version": return `<span class="sys">${a} new strategy version ${esc(p.version || "none")}</span>`;
    case "command": return `<span class="sys">${a} set ${esc(p.employee)} ${esc(JSON.stringify(p.changes))}${p.reason ? " — " + esc(p.reason) : ""}</span>`;
    case "fire": return `<span class="sys">${a} FIRED ${esc(p.employee)} → ${esc(p.successor)} — ${esc(p.reason)}</span>`;
    case "evaluation": return `<span class="sys">${a} held-out test: ${p.trades ?? 0} trades, ${p.net_bps_per_trade ?? "–"} bps/trade${p.ci95_net_bps_per_trade ? " [" + p.ci95_net_bps_per_trade.join(", ") + "]" : ""}</span>`;
    default: return null;   // spend, agent_state, turn: shown in the room, not the log
  }
}

export function addToLog(e: OfficeEvent) {
  if (e.kind === "hire") roleOf[e.payload.employee] = e.payload.role;
  if (e.kind === "say" && e.payload.role) roleOf[e.actor] = e.payload.role;
  const html = line(e);
  if (html === null) return;
  const log = $("#log"), atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const d = document.createElement("div");
  d.className = "ev";
  d.innerHTML = `<span class="t">${e.ts.slice(11, 16)}</span>${html}`;
  log.appendChild(d);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

export async function refreshBoard() {
  const b = await getJSON("/leaderboard");
  const n = (x: unknown) => (x == null ? "–" : String(x));
  const sign = (x: number | null) => (x == null ? "" : x >= 0 ? "pos" : "neg");
  $("#board tbody").innerHTML = b.by_employee.map((r: any) =>
    `<tr><td>${esc(r.employee)}${r.fired ? " ✝" : ""}</td><td>${r.trades}</td><td class="${sign(r.net_pnl)}">${n(r.net_pnl)}</td><td>${n(r.avg_net_bps)}</td><td>${r.open_positions}</td></tr>`).join("");
  $("#versions tbody").innerHTML = b.by_version.map((r: any) =>
    `<tr><td>${esc(r.employee)} · ${esc(String(r.strategy_version).slice(0, 8))}</td><td>${r.trades}</td><td class="${sign(r.net_pnl)}">${r.net_pnl}</td><td>${n(r.avg_net_bps)}</td></tr>`).join("") ||
    `<tr><td colspan="4" class="muted">no closed positions yet</td></tr>`;
  return b;
}

export async function refreshBudget() {
  try {
    const b = await getJSON("/budget");
    $("#budget").textContent = b.map((x: any) => `${x.role} $${x.spent_usd.toFixed(3)}/${x.cap_usd.toFixed(2)}`).join(" · ");
  } catch { /* office offline */ }
}

export function setPrice(text: string) { $("#price").textContent = text; }

export async function initPanel() {
  const me = await whoami();
  $("#me").textContent = me ? `you: ${me}` : "";
  $("#say").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $<HTMLInputElement>("#text");
    const text = input.value.trim();
    if (text && (await sayAsBoss(text))) input.value = "";
    const who = await whoami();
    $("#me").textContent = who ? `you: ${who}` : "";
  });
}
