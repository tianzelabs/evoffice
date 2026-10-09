// Boot: replay the office's history into the room without animation, then go live.
import * as Phaser from "phaser";
import { allEvents, getJSON, stream } from "./net";
import { OfficeScene, W, H } from "./office";
import { addToLog, displayName, initPanel, learnNames, refreshBoard, refreshBudget, refreshIterations, setPrice } from "./panel";
import "./style.css";

const scene = new OfficeScene();
(window as any).office = scene;   // for looking at the room from the browser console; it can only animate, never write
new Phaser.Game({
  type: Phaser.AUTO, parent: "room", width: W, height: H, backgroundColor: "#d9cbb4",
  pixelArt: true, scene, scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
});

async function board() { try { scene.setBoard(await refreshBoard()); } catch { /* offline */ } }

async function market() {
  try {
    const [p, bars] = await Promise.all([getJSON("/price"), getJSON("/bars?minutes=90")]);
    setPrice(`BTC ${p.price.toFixed(1)}`);
    scene.setChart(bars, p.price);
  } catch { setPrice("BTC feed stale"); }
}

(async () => {
  await initPanel();
  await scene.ready;
  try { learnNames(await getJSON("/employees")); } catch { /* offline: ids until names arrive */ }
  scene.nameOf = displayName;
  const history = await allEvents();
  for (const e of history) { scene.apply(e, false); addToLog(e); }
  const last = history.length ? history[history.length - 1].id : 0;
  stream(last, (e) => {
    scene.apply(e, true);
    addToLog(e);
    if (["open", "close", "fire", "hire"].includes(e.kind)) board();
    if (e.kind === "spend") refreshBudget();
    if (["version", "evaluation", "close", "fire"].includes(e.kind)) refreshIterations().catch(() => {});
  });
  board(); market(); refreshBudget(); refreshIterations().catch(() => {});
  setInterval(market, 15_000);
  setInterval(board, 60_000);
})();
