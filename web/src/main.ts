import { history, json, say, subscribe, type OfficeEvent } from "./api";
import { ModernOffice } from "./world";
import "./style.css";

const stage = document.querySelector<HTMLElement>("#stage")!;
const office = new ModernOffice(stage);
const selectedName = document.querySelector<HTMLElement>("#selected-name")!;
const selectedDetail = document.querySelector<HTMLElement>("#selected-detail")!;
const chatLog = document.querySelector<HTMLElement>("#chat-log")!;
const leaderboardRows = document.querySelector<HTMLElement>("#leaderboard-rows")!;

function addChat(event: OfficeEvent) {
  if (event.kind !== "say" && event.kind !== "alert") return;
  const line = document.createElement("div"); line.className = "chat-line";
  const who = event.actor === "manager" ? "manager" : event.actor === "boss" ? "boss" : event.actor;
  line.innerHTML = `<strong>${who}</strong> ${String(event.payload?.text ?? event.payload?.message ?? "")}`;
  chatLog.appendChild(line); while (chatLog.children.length > 80) chatLog.firstElementChild?.remove(); chatLog.scrollTop = chatLog.scrollHeight;
}

async function refresh() {
  try {
    const board = await json<any>("/leaderboard");
    const rows = board.by_employee ?? [];
    office.setBoard(rows);
    leaderboardRows.innerHTML = rows.slice(0, 6).map((r: any) => `<div class="leader-row"><span class="name">${r.name ?? r.employee}</span><span>${r.trades ?? 0}t</span><span class="${Number(r.net_pnl ?? 0) >= 0 ? "positive" : "negative"}">${r.net_pnl ?? 0}</span></div>`).join("");
    document.querySelector("#agents")!.textContent = String(rows.length);
  } catch { /* server may be offline during local visual work */ }
  try { const price = await json<any>("/price"); document.querySelector("#market")!.textContent = `BTC-PERP ${price.bid.toFixed(0)} / ${price.ask.toFixed(0)} · funding ${(price.funding_per_hour * 1e4).toFixed(3)} bp/h`; } catch { /* offline */ }
  try { const budget = await json<any>("/budget"); document.querySelector("#budget")!.textContent = `manager $${Number(budget.manager?.spent_usd ?? 0).toFixed(2)}`; } catch { /* offline */ }
}

(async () => {
  await office.init((facility) => { selectedName.textContent = facility.name; selectedDetail.textContent = facility.detail; });
  try {
    const employees = await json<any[]>("/employees"); office.setNames(Object.fromEntries(employees.map((e) => [e.employee ?? e.id, e.name ?? e.employee ?? e.id])));
  } catch { /* local visual mode */ }
  let events: OfficeEvent[] = [];
  try { events = await history(); for (const event of events) { office.apply(event, false); addChat(event); } } catch { /* local visual mode */ }
  const last = events.at(-1)?.id ?? 0;
  subscribe(last, (event) => { office.apply(event, true); addChat(event); });
  await refresh(); setInterval(refresh, 20_000);
})();

document.querySelector<HTMLFormElement>("#say")!.addEventListener("submit", async (event) => { event.preventDefault(); const input = document.querySelector<HTMLInputElement>("#say-text")!; const text = input.value.trim(); if (!text) return; if (await say(text)) input.value = ""; });
document.querySelector("#replay")!.addEventListener("click", () => { window.location.href = "/?replay=1"; });
