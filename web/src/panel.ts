// The side panel: chat, the boss's input box, the leaderboard. Plain DOM --
// text, input and scrolling are what HTML is for; the canvas draws the room.
import { getJSON, OfficeEvent, sayAsBoss, whoami } from "./net";

const $ = <T extends HTMLElement>(s: string) => document.querySelector(s) as T;
const esc = (s: unknown) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const roleOf: Record<string, string> = {};
const nameOf: Record<string, string> = {};        // employee id -> the name it chose for itself

export const displayName = (id: string) => nameOf[id] ?? id;
export function learnNames(employees: { id: string; name?: string | null; role: string }[]) {
  employees.forEach((e) => { if (e.name) nameOf[e.id] = e.name; roleOf[e.id] = e.role; });
}

function who(actor: string) {
  const r = roleOf[actor] ?? (actor === "office" ? "office" : actor.startsWith("trader") ? "trader" : actor);
  return `<span class="who-${r}" title="${esc(actor)}">${esc(displayName(actor))}</span>`;
}

function line(e: OfficeEvent): string | null {
  const p = e.payload, a = who(e.actor);
  switch (e.kind) {
    case "say": return `${a}${p.to ? " → " + esc(displayName(p.to)) : ""}: ${esc(p.text)}`;
    case "name": return `<span class="sys">${esc(p.previous ?? e.actor)} is now called <b>${esc(p.name)}</b></span>`;
    case "award": return p.award ? `<span class="trophy">🏆 ${a} wins <b>${esc(p.title)}</b> for ${esc(p.season)}</span>`
                                 : `<span class="sys">${esc(p.season)}: ${esc(p.title)}</span>`;
    case "meeting": return `<span class="sys">— ${p.phase === "start" ? "daily stand-up begins at the meeting table" : "stand-up over"} —</span>`;
    case "alert": return `<span class="neg"><b>⚠ market alert:</b> ${esc(p.text)}</span>`;
    case "level": return `<span class="sys">${a} reached level ${p.level}: <b>${esc(p.title)}</b> — size cap ${p.max_size} BTC</span>`;
    case "badge": return `<span class="sys">${a} earned a badge: 🏅 ${esc(p.title)}</span>`;
    case "open": return `<span class="sys">${a} opened #${p.position} ${p.side} ${p.size} @ ${p.entry_px}${p.liquidity ? ` (${p.liquidity}, fee ${p.fee})` : ""}</span>`;
    case "close": return `<span class="sys">${a} closed #${p.position} (${p.reason}${p.liquidity ? ", " + p.liquidity : ""}) · net <span class="${p.pnl >= 0 ? "pos" : "neg"}">${p.pnl} (${p.pnl_bps} bps)</span>${p.funding ? ` incl. funding ${p.funding}` : ""}</span>`;
    case "order": {
      const what = p.status === "placed" ? `placed a ${p.post_only ? "post-only " : ""}limit ${p.side} ${p.size} @ ${p.price} (${p.intent})`
        : p.status === "filled" ? `limit ${p.side} @ ${p.price} FILLED as ${p.liquidity}`
        : p.status === "rejected" ? `limit ${p.side} @ ${p.price} rejected: ${esc(p.why ?? "")}`
        : `limit ${p.side} @ ${p.price} ${p.status}`;
      return `<span class="sys">${a} ${what}</span>`;
    }
    case "task": return `${a} → ${esc(displayName(p.to))} <b>TASK</b>: ${esc(p.text)}`;
    case "task_result": return `<span class="sys">${a} task #${p.task} ${p.error ? `<span class="neg">failed: ${esc(p.error)}</span>` : "done"}${p.summary ? ": " + esc(String(p.summary).slice(0, 600)) : ""}</span>`;
    case "trigger": return `<span class="sys">⚡ ${a} trigger: ${esc(p.text ?? "")}</span>`;
    case "hire": return `<span class="sys">${esc(p.employee)} joined as ${esc(p.role)}</span>`;
    case "wake": return `<span class="sys">${a} woke: ${esc((p.reasons || []).join("; "))}</span>`;
    case "version": return `<span class="sys">${a} new strategy version ${esc(p.version || "none")}</span>`;
    case "command": return `<span class="sys">${a} set ${esc(p.employee)} ${esc(JSON.stringify(p.changes))}${p.reason ? " — " + esc(p.reason) : ""}</span>`;
    case "fire": return `<span class="sys">${a} FIRED ${esc(p.employee)} → ${esc(p.successor)} — ${esc(p.reason)}</span>`;
    case "evaluation": return `<span class="sys">${a} held-out test: ${p.trades ?? 0} trades, ${p.net_bps_per_trade ?? "–"} bps/trade${p.ci95_net_bps_per_trade ? " [" + p.ci95_net_bps_per_trade.join(", ") + "]" : ""}</span>`;
    case "agent_state": return p.state === "asleep" ? `<span class="sys">${a} is asleep: ${esc(p.why ?? "")}</span>` : null;
    default: return null;   // spend, turn, other states: shown in the room, not the log
  }
}

export function addToLog(e: OfficeEvent) {
  if (e.kind === "hire") roleOf[e.payload.employee] = e.payload.role;
  if (e.kind === "name") nameOf[e.payload.employee] = e.payload.name;
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

export async function refreshSeason() {
  const s = await getJSON("/season");
  $("#season-name").textContent = `${s.season} · ends ${s.ends.slice(5, 16).replace("T", " ")} UTC`;
  const rows = s.standings.map((r: any) => {
    const cups = (s.trophies[r.employee] ?? []).length;
    return `<tr><td>${esc(displayName(r.employee))}${cups ? ` <span class="trophy">🏆×${cups}</span>` : ""}</td><td>${r.xp}</td><td>${r.evaluations}</td><td>${r.trades}</td><td class="${r.pnl >= 0 ? "pos" : "neg"}">${r.pnl}</td></tr>`;
  }).join("");
  $("#season").innerHTML = `<table><thead><tr><th>this week</th><th>XP</th><th>tests</th><th>trades</th><th>P&L</th></tr></thead><tbody>${rows}</tbody></table>`;
  return s;
}

let careerOf: Record<string, any> = {};
export function setCareers(prog: Record<string, any>) {
  careerOf = prog;
  refreshBoard().catch(() => {});
}

export async function refreshBoard() {
  const b = await getJSON("/leaderboard");
  const n = (x: unknown) => (x == null ? "–" : String(x));
  const sign = (x: number | null) => (x == null ? "" : x >= 0 ? "pos" : "neg");
  $("#board tbody").innerHTML = b.by_employee.map((r: any) =>
    `<tr><td title="${esc(r.employee)}${careerOf[r.employee] ? " · " + careerOf[r.employee].xp + " XP · badges: " + esc(careerOf[r.employee].badges.join(", ")) : ""}">${esc(displayName(r.employee))}${careerOf[r.employee] ? ` <span class="lv">Lv${careerOf[r.employee].level}${careerOf[r.employee].probation ? "⚠" : ""}</span>` : ""}${r.fired ? " ✝" : ""}</td><td>${r.trades}</td><td class="${sign(r.net_pnl)}">${n(r.net_pnl)}</td><td>${n(r.avg_net_bps)}</td><td>${r.open_positions}</td></tr>`).join("");
  $("#versions tbody").innerHTML = b.by_version.map((r: any) =>
    `<tr><td>${esc(displayName(r.employee))} · ${esc(String(r.strategy_version).slice(0, 8))}</td><td>${r.trades}</td><td class="${sign(r.net_pnl)}">${r.net_pnl}</td><td>${n(r.avg_net_bps)}</td></tr>`).join("") ||
    `<tr><td colspan="4" class="muted">no closed positions yet</td></tr>`;
  return b;
}

export async function refreshBudget() {
  try {
    const b = await getJSON("/budget");
    $("#budget").textContent = "budget " + b.map((x: any) => `${x.employee} $${x.spent_usd.toFixed(3)}/${x.cap_usd.toFixed(2)}`).join(" · ");
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

// ---------- did the change help? (/iterations) ----------
function chart(series: any[]): string {
  // one dot per held-out evaluation, whisker = 95% interval, dashed line = zero (the fee already paid)
  const W = 330, H = 110, pad = 26;
  if (!series.length) return `<div class="muted">no held-out evaluations yet</div>`;
  const vals = series.flatMap((s) => [s.net_bps_per_trade, ...(s.ci95 ?? [])]).filter((v) => v != null);
  const lo = Math.min(0, ...vals) - 2, hi = Math.max(0, ...vals) + 2;
  const y = (v: number) => pad / 2 + (H - pad) * (1 - (v - lo) / (hi - lo));
  const x = (i: number) => pad + (series.length === 1 ? (W - pad) / 2 : (i * (W - pad - 10)) / (series.length - 1));
  const marks = series.map((s, i) => {
    const c = s.ci95 && s.ci95[0] > 0 ? "var(--trader)" : "var(--boss)";
    const whisker = s.ci95 ? `<line x1="${x(i)}" x2="${x(i)}" y1="${y(s.ci95[0])}" y2="${y(s.ci95[1])}" stroke="${c}" stroke-width="2"/>` : "";
    return `${whisker}<circle cx="${x(i)}" cy="${y(s.net_bps_per_trade)}" r="4" fill="${c}"><title>${esc(s.ts.slice(5, 16))} · ${s.trades} trades · ${s.net_bps_per_trade} bps/trade${s.ci95 ? " [" + s.ci95.join(", ") + "]" : ""}${s.version ? " · version " + esc(s.version) : ""}</title></circle>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" class="iter-chart" role="img" aria-label="held-out results per evaluation">
    <line x1="${pad}" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="var(--muted)" stroke-dasharray="4 3"/>
    <text x="2" y="${y(0) + 4}" font-size="10" fill="var(--muted)">0</text>
    <text x="2" y="${y(hi) + 10}" font-size="10" fill="var(--muted)">${hi.toFixed(0)}</text>
    <text x="2" y="${y(lo)}" font-size="10" fill="var(--muted)">${lo.toFixed(0)}</text>${marks}</svg>`;
}

export async function refreshIterations() {
  const it = await getJSON("/iterations");
  $("#iterations").innerHTML = Object.entries(it).map(([trader, t]: [string, any]) => {
    const s = t.summary;
    const verdict = s.any_interval_above_zero ? `<span class="pos">an interval above zero</span>` : `<span class="muted">no edge shown yet</span>`;
    const rows = t.versions.slice().reverse().map((v: any) => {
      const ev = v.evaluations.map((e: any) => e.net_bps_per_trade == null ? "err" : `${e.net_bps_per_trade}`).join(", ");
      return `<tr><td>${esc(v.version ? v.version.slice(0, 8) : "(no strategy)")}</td><td>${v.since ? esc(v.since.slice(5, 16).replace("T", " ")) : ""}</td><td title="${esc(v.objects.join(", "))}">${v.objects.length}</td><td>${ev || "–"}</td><td>${v.live.trades ?? 0}</td></tr>`;
    }).join("");
    return `<div class="iter"><div><b title="${esc(trader)}">${esc(displayName(trader))}</b> · ${s.versions} versions · ${s.evaluations} held-out tests · ${verdict}</div>
      ${chart(t.evaluations)}
      <div class="scroll-x"><table><thead><tr><th>version</th><th>since</th><th>obj</th><th>held-out bps</th><th>live</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="muted">no versions yet</td></tr>`}</tbody></table></div></div>`;
  }).join("") || `<div class="muted">no traders</div>`;
  return it;
}

export async function refreshObjective() {
  const o = await getJSON("/objective");
  const fmt = (v: any) => (v === null || v === undefined ? "–" : typeof v === "number" ? (v > 0 ? "+" : "") + v : esc(String(v)));
  const best = (r: any) => {
    const b = r.best;
    if (r.rung === 1) return `train ${fmt(b.best_train_bps)} · recent ${fmt(b.best_recent_bps)} · both ${fmt(b.both_windows_min_bps)} bps (${b.candidates_tested} tested)`;
    if (r.rung === 2) return `best ${fmt(b.best_heldout_bps)} bps (${b.evaluations} exams)`;
    if (r.rung === 3) return `best low ${fmt(b.best_interval_low_bps)} bps`;
    return `${b.last_trades} trades · ${fmt(b.net_usd)} USD · ${fmt(b.avg_net_bps)} bps`;
  };
  $("#objective").innerHTML = `<table><tbody>${o.rungs.map((r: any) =>
    `<tr><td>${r.reached ? "✅" : r.rung === o.rung + 1 ? "▶" : "·"} ${r.rung}</td><td>${esc(r.goal)}<br><span class="muted">${best(r)}</span></td></tr>`).join("")}</tbody></table>`;
}
