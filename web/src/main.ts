const history_ = window.history;
// Boot: replay the office's history into the room without animation, then go live.
import * as Phaser from "phaser";
import { allEvents, getJSON, stream, type OfficeEvent } from "./net";
import { OfficeScene, W, H } from "./office";
import { addToLog, displayName, initPanel, learnNames, refreshBoard, refreshBudget, refreshIterations, refreshObjective, refreshSeason, setCareers, setPrice } from "./panel";
import "./style.css";

const scene = new OfficeScene();
(window as any).office = scene;   // for looking at the room from the browser console; it can only animate, never write
new Phaser.Game({
  type: Phaser.AUTO, parent: "room", width: W, height: H, backgroundColor: "#d9cbb4",
  pixelArt: true, scene, scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
});

let careerTimer: number | undefined;
async function careers() {
  clearTimeout(careerTimer);                  // spend events come in bursts; refresh once they settle
  careerTimer = window.setTimeout(async () => {
    try {
      const [prog, budgets] = await Promise.all([getJSON("/progress"), getJSON("/budget")]);
      scene.setProgress(prog, budgets);
      setCareers(prog);
    } catch { /* offline */ }
  }, 800);
}

async function season() {
  try { const s = await refreshSeason(); scene.setTrophies(s.trophies); } catch { /* offline */ }
}

async function board() { try { scene.setBoard(await refreshBoard()); } catch { /* offline */ } }

async function market() {
  try {
    const [p, bars] = await Promise.all([getJSON("/price"), getJSON("/bars?minutes=90")]);
    setPrice(`BTC-PERP ${p.bid.toFixed(0)}/${p.ask.toFixed(0)} · funding ${(p.funding_per_hour * 1e4).toFixed(3)} bp/h`);
    scene.setChart(bars, p.price);
  } catch { setPrice("BTC feed stale"); }
}

(async () => {
  await initPanel();
  await scene.ready;
  try { learnNames(await getJSON("/employees")); } catch { /* offline: ids until names arrive */ }
  scene.nameOf = displayName;
  const history = await allEvents();
  const params = new URLSearchParams(location.search);
  const day = params.get("replay");
  wireReplayControls(day);
  if (day) {
    history_.replaceState(null, "", location.pathname);    // a replay is one-shot: refreshing goes back to live
    replay(history, day, Number(params.get("speed") ?? 60)); board(); market(); season(); careers(); return;
  }
  for (const e of history) { scene.apply(e, false); addToLog(e); }
  const last = history.length ? history[history.length - 1].id : 0;
  stream(last, (e) => {
    scene.apply(e, true);
    addToLog(e);
    if (["open", "close", "fire", "hire"].includes(e.kind)) board();
    if (e.kind === "spend") refreshBudget();
    if (["version", "evaluation", "close", "fire"].includes(e.kind)) refreshIterations().catch(() => {});
    if (["level", "badge", "evaluation", "close", "version", "spend", "name"].includes(e.kind)) careers();
    if (["award", "evaluation", "close", "version"].includes(e.kind)) season();
    if (["backtest", "evaluation", "close"].includes(e.kind)) refreshObjective().catch(() => {});
  });
  board(); market(); refreshBudget(); refreshIterations().catch(() => {}); careers(); season();
  refreshObjective().catch(() => {});
  setInterval(season, 120_000);
  setInterval(careers, 60_000);
  setInterval(market, 15_000);
  setInterval(board, 60_000);
})();

// ---------- replay: a day of the office, compressed ----------
function wireReplayControls(day: string | null) {
  const input = document.querySelector<HTMLInputElement>("#replay-day")!;
  const speed = document.querySelector<HTMLSelectElement>("#replay-speed")!;
  input.value = day ?? new Date().toISOString().slice(0, 10);
  if (day) {
    speed.value = new URLSearchParams(location.search).get("speed") ?? "60";
    document.querySelector<HTMLElement>("#live-link")!.hidden = false;
  }
  document.querySelector("#replay-go")!.addEventListener("click", () => {
    location.search = `?replay=${input.value}&speed=${speed.value}`;
  });
}

function replay(history: OfficeEvent[], day: string, speed: number) {
  // the state before the day is restored silently; the day itself plays at `speed` x real time
  const before = history.filter((e) => e.ts.slice(0, 10) < day);
  const today = history.filter((e) => e.ts.slice(0, 10) === day);
  for (const e of before) scene.apply(e, false);
  const banner = document.createElement("div");
  banner.id = "replay-banner";
  document.body.appendChild(banner);
  if (!today.length) { banner.textContent = `REPLAY ${day}: nothing happened that day`; return; }
  const t0 = Date.parse(today[0].ts);
  today.forEach((e) => {
    const at = (Date.parse(e.ts) - t0) / speed;
    window.setTimeout(() => {
      scene.apply(e, true);
      addToLog(e);
      banner.textContent = `REPLAY ${day} ×${speed} · ${e.ts.slice(11, 19)} UTC`;
    }, at);
  });
  window.setTimeout(() => { banner.textContent = `REPLAY ${day}: end of the day`; }, (Date.parse(today[today.length - 1].ts) - t0) / speed + 2000);
}
