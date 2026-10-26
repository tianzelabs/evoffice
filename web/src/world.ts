import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import type { OfficeEvent } from "./api";

export type Facility = { id: string; name: string; detail: string; x: number; y: number; w: number; h: number };
type ActorView = { seat: string; employee: string; root: Container; label: Text; target: { x: number; y: number }; home: { x: number; y: number }; thinking: boolean };

export const WORLD = { width: 1600, height: 900 };
export const FACILITIES: Facility[] = [
  { id: "windows", name: "OBSERVATORY WINDOWS", detail: "The living office looks over the city and the research horizon.", x: 0, y: 0, w: 355, h: 580 },
  { id: "data-wall", name: "CENTRAL DATA WALL", detail: "A shared wall of signals, leaderboard state and collective memory.", x: 420, y: 95, w: 730, h: 300 },
  { id: "manager-office", name: "MANAGER GLASS OFFICE", detail: "The manager's command point and whiteboard.", x: 1200, y: 65, w: 390, h: 460 },
  { id: "commons", name: "COMMONS TABLE", detail: "The shared table where the office meets as one entity.", x: 480, y: 430, w: 720, h: 290 },
  { id: "trader-1", name: "TRADER 1 WORKSTATION", detail: "Strategy, code, charts, budget and XP.", x: 20, y: 570, w: 430, h: 300 },
  { id: "trader-2", name: "TRADER 2 WORKSTATION", detail: "Strategy, code, charts, budget and XP.", x: 430, y: 600, w: 430, h: 270 },
  { id: "studio", name: "RESEARCH STUDIO", detail: "Books, notes, plants and the secondary research surface.", x: 1190, y: 535, w: 410, h: 335 },
];

const palette = { ink: 0x071421, wall: 0x162b40, wall2: 0x263f50, wood: 0x8c5d3f, woodDark: 0x543521, teal: 0x54e1db, amber: 0xf4ae55, green: 0x7ee2a1, glass: 0x54e1db };
const textStyle = (size: number, color = "#e8f7f2", weight: "normal" | "bold" = "normal") => new TextStyle({ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: size, fill: color, fontWeight: weight });

export class ModernOffice {
  readonly app: Application;
  private readonly host: HTMLElement;
  private readonly root = new Container();
  private readonly world = new Container();
  private readonly actors = new Map<string, ActorView>();
  private readonly seats: Record<string, { x: number; y: number }> = {
    "trader-1": { x: 240, y: 745 }, "trader-2": { x: 660, y: 755 }, manager: { x: 1390, y: 690 }, boss: { x: 800, y: 850 },
  };
  private selected?: Facility;
  private facilityLayer!: Container;
  private selectedBox!: Graphics;
  private boardText!: Text;
  private whiteboardText!: Text;
  private clockText!: Text;
  private names = new Map<string, string>();
  private onFacility?: (facility: Facility) => void;

  constructor(host: HTMLElement) {
    this.host = host;
    this.app = new Application();
  }

  async init(onFacility: (facility: Facility) => void) {
    this.onFacility = onFacility;
    await this.app.init({ resizeTo: this.host, background: "#091a28", antialias: false, resolution: Math.min(2, window.devicePixelRatio || 1) });
    this.host.appendChild(this.app.canvas);
    this.root.sortableChildren = true;
    this.world.sortableChildren = true;
    this.root.addChild(this.world);
    this.app.stage.addChild(this.root);
    this.drawArchitecture();
    this.installFacilities();
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.app.ticker.add(() => this.tick());
  }

  private resize() {
    // Fill the stage like the cover composition. The side panel makes the
    // viewport narrower than the 16:9 room, so contain-scaling would leave
    // large dead bands above and below the actual office.
    const scale = Math.max(this.host.clientWidth / WORLD.width, this.host.clientHeight / WORLD.height);
    this.root.scale.set(scale);
    this.root.position.set((this.host.clientWidth - WORLD.width * scale) / 2, (this.host.clientHeight - WORLD.height * scale) / 2);
  }

  private drawArchitecture() {
    const back = new Graphics().rect(0, 0, WORLD.width, WORLD.height).fill(palette.ink); this.world.addChild(back);
    const wall = new Graphics().rect(0, 0, WORLD.width, 360).fill(palette.wall).rect(0, 320, WORLD.width, 40).fill(palette.wall2); this.world.addChild(wall);
    const floor = new Graphics().rect(0, 360, WORLD.width, 540).fill(palette.wood); for (let y = 380; y < 900; y += 38) floor.moveTo(0, y).lineTo(WORLD.width, y).stroke({ width: 2, color: palette.woodDark, alpha: .55 }); for (let x = -500; x < 2100; x += 180) floor.moveTo(x, 360).lineTo(x + 430, 900).stroke({ width: 2, color: palette.woodDark, alpha: .32 }); this.world.addChild(floor);
    this.drawWindows(); this.drawDataWall(); this.drawGlassOffice(); this.drawCommons(); this.drawStudio(); this.drawPlants(); this.drawHangingLights();
    this.boardText = new Text("", textStyle(18, "#b4f5e5")); this.boardText.position.set(475, 165); this.world.addChild(this.boardText);
    const boardTitle = new Text("COLLECTIVE BOARD", textStyle(20, "#54e1db", "bold")); boardTitle.position.set(475, 135); this.world.addChild(boardTitle);
    this.whiteboardText = new Text("", new TextStyle({ ...textStyle(15, "#e8f7f2"), wordWrap: true, wordWrapWidth: 240 })); this.whiteboardText.position.set(1250, 160); this.world.addChild(this.whiteboardText);
    const whiteTitle = new Text("MANAGER SAYS", textStyle(15, "#f4ae55", "bold")); whiteTitle.position.set(1250, 132); this.world.addChild(whiteTitle);
    this.clockText = new Text("--:--", textStyle(22, "#f4ae55", "bold")); this.clockText.position.set(1490, 28); this.world.addChild(this.clockText);
    this.selectedBox = new Graphics(); this.selectedBox.zIndex = 1000; this.world.addChild(this.selectedBox);
  }

  private drawWindows() {
    const g = new Graphics().rect(18, 28, 330, 285).fill(0x1f5579).rect(28, 38, 310, 265).fill(0x183d60).rect(28, 210, 310, 93).fill(0x0d2037); for (const [x, y, w, h] of [[45, 165, 48, 70], [112, 142, 40, 93], [180, 190, 70, 45], [275, 150, 42, 85]]) g.rect(x, y, w, h).fill(0x092039); for (const [x, y] of [[45, 235], [95, 255], [170, 235], [236, 260], [300, 230]]) g.rect(x, y, 5, 5).fill(palette.amber); g.rect(18, 28, 330, 285).stroke({ width: 8, color: 0x8b6043 }); g.moveTo(183, 28).lineTo(183, 313).stroke({ width: 7, color: 0x8b6043 }); this.world.addChild(g);
  }

  private drawDataWall() {
    const g = new Graphics().roundRect(430, 90, 730, 300, 12).fill(0x102d3d).roundRect(448, 108, 694, 264, 4).fill(0x061a22).roundRect(430, 90, 730, 300, 12).stroke({ width: 4, color: palette.teal, alpha: .9 });
    for (const x of [520, 680, 835, 1010]) g.moveTo(x, 130).lineTo(x, 350).stroke({ width: 1, color: palette.teal, alpha: .28 });
    for (const y of [185, 245, 305]) g.moveTo(465, y).lineTo(1125, y).stroke({ width: 1, color: palette.teal, alpha: .28 });
    g.circle(610, 220, 12).fill(palette.teal); g.circle(710, 175, 9).fill(palette.amber); g.circle(790, 270, 11).fill(palette.teal); g.moveTo(610, 220).lineTo(710, 175).lineTo(790, 270).stroke({ width: 3, color: palette.teal });
    for (let i = 0; i < 8; i++) { g.rect(885, 135 + i * 25, 175 - (i % 3) * 35, 6).fill(i % 2 ? palette.teal : palette.amber); g.rect(480, 145 + i * 25, 55 + (i % 4) * 20, 5).fill(palette.teal); }
    this.world.addChild(g);
  }

  private drawGlassOffice() { const g = new Graphics().rect(1210, 55, 370, 405).fill({ color: palette.glass, alpha: .08 }).rect(1210, 55, 370, 405).stroke({ width: 4, color: palette.glass, alpha: .85 }).moveTo(1395, 55).lineTo(1395, 460).stroke({ width: 3, color: palette.glass, alpha: .65 }).moveTo(1210, 220).lineTo(1580, 220).stroke({ width: 3, color: palette.glass, alpha: .65 }); this.world.addChild(g); }
  private drawCommons() { const g = new Graphics().ellipse(820, 570, 700, 105).fill({ color: palette.woodDark, alpha: .5 }).moveTo(485, 480).lineTo(1150, 480).lineTo(1200, 650).lineTo(430, 650).closePath().fill(0x6d432b).stroke({ width: 4, color: 0xb97c4d }); for (const x of [560, 720, 880, 1040]) g.roundRect(x, 638, 72, 48, 6).fill(0x132533); this.world.addChild(g); }
  private drawStudio() { const g = new Graphics().rect(1235, 610, 300, 42).fill(0x5b3826).rect(1270, 555, 55, 42).fill(0x071a22).rect(1340, 555, 55, 42).fill(0x071a22); for (let y = 490; y < 760; y += 50) g.rect(1165, y, 38, 8).fill(0x9b6338); this.world.addChild(g); }
  private drawPlants() { for (const [x, y, s] of [[380, 480, 1.3], [1180, 480, 1.6], [75, 555, 1.4], [1500, 720, 1.2]]) { const g = new Graphics().rect(x - 16 * s, y, 32 * s, 36 * s).fill(0x9b5d31).circle(x, y - 26 * s, 34 * s).fill(0x2b7044).circle(x - 24 * s, y - 10 * s, 20 * s).fill(0x3e9c5b).circle(x + 24 * s, y - 12 * s, 20 * s).fill(0x3e9c5b); this.world.addChild(g); } }
  private drawHangingLights() { for (const x of [520, 800, 1080]) { const g = new Graphics().moveTo(x, 0).lineTo(x, 60).stroke({ width: 3, color: 0x0b1722 }); g.roundRect(x - 13, 58, 26, 30, 5).fill(palette.amber); g.circle(x, 104, 50).fill({ color: 0xffd27a, alpha: .10 }); this.world.addChild(g); } }

  private installFacilities() { for (const facility of FACILITIES) { const hit = new Graphics().rect(facility.x, facility.y, facility.w, facility.h).fill({ color: palette.teal, alpha: .001 }); hit.eventMode = "static"; hit.cursor = "pointer"; hit.on("pointerover", () => this.highlight(facility)); hit.on("pointerout", () => this.highlight(undefined)); hit.on("pointertap", () => this.onFacility?.(facility)); this.facilityLayer ??= new Container(); this.facilityLayer.addChild(hit); } if (this.facilityLayer) { this.facilityLayer.zIndex = 900; this.world.addChild(this.facilityLayer); } }
  private highlight(facility?: Facility) { this.selectedBox.clear(); if (!facility) return; this.selectedBox.roundRect(facility.x, facility.y, facility.w, facility.h, 12).fill({ color: palette.teal, alpha: .08 }).stroke({ width: 3, color: palette.teal, alpha: .85 }); }
  private tick() { const now = new Date(); this.clockText.text = now.toTimeString().slice(0, 5); for (const actor of this.actors.values()) { const dx = actor.target.x - actor.root.x, dy = actor.target.y - actor.root.y; actor.root.x += dx * .08; actor.root.y += dy * .08; actor.label.position.set(actor.root.x - actor.label.width / 2, actor.root.y + 38); } }

  private ensureActor(employee: string, role = employee.startsWith("trader") ? "trader" : employee) {
    const seat = employee.startsWith("trader") ? employee.split(".")[0] : role;
    if (this.actors.has(seat)) return this.actors.get(seat)!;
    const home = this.seats[seat] ?? this.seats["trader-1"];
    const root = new Container(); root.position.set(home.x, home.y); root.zIndex = home.y;
    const shadow = new Graphics().ellipse(0, 35, 58, 14).fill({ color: 0x000000, alpha: .28 }); root.addChild(shadow);
    const body = new Graphics().roundRect(-20, 4, 40, 34, 8).fill(role === "manager" ? 0x315b94 : role === "boss" ? 0x7f3533 : 0x347d69);
    const head = new Graphics().circle(0, -10, 18).fill(role === "manager" ? 0xb9c9d5 : 0x302219); root.addChild(body, head);
    const label = new Text(this.names.get(employee) ?? employee, textStyle(13, "#d7fff5", "bold")); label.position.set(-label.width / 2, 46); root.addChild(label);
    this.world.addChild(root); const actor = { seat, employee, root, label, target: { ...home }, home: { ...home }, thinking: false }; this.actors.set(seat, actor); return actor;
  }

  apply(event: OfficeEvent, animate = true) {
    const p = event.payload ?? {};
    if (event.kind === "hire" && p.role !== "boss") { this.ensureActor(p.employee, p.role); return; }
    if (event.kind === "name") { this.names.set(p.employee, p.name); const actor = this.ensureActor(p.employee); actor.label.text = p.name; return; }
    if (event.kind === "fire") { const seat = event.payload?.employee?.startsWith("trader") ? event.payload.employee.split(".")[0] : event.payload.employee; this.actors.get(seat)?.root.destroy({ children: true }); this.actors.delete(seat); return; }
    if (!event.actor || event.actor === "office") return;
    const actor = this.ensureActor(event.actor);
    if (event.kind === "agent_state") actor.thinking = p.state === "thinking";
    if (event.kind === "meeting") for (const a of this.actors.values()) a.target = p.phase === "start" ? { x: 800 + (a.seat === "trader-1" ? -180 : a.seat === "trader-2" ? 180 : 0), y: 560 } : { ...a.home };
    if (event.kind === "say" && p.text) this.toast(actor, String(p.text));
  }

  private toast(actor: ActorView, message: string) { const bubble = new Text(message.length > 85 ? `${message.slice(0, 82)}…` : message, new TextStyle({ ...textStyle(13, "#e8f7f2"), wordWrap: true, wordWrapWidth: 280 })); bubble.position.set(actor.root.x - 140, actor.root.y - 100); bubble.zIndex = 1200; const bg = new Graphics().roundRect(-10, -8, 300, Math.max(42, bubble.height + 16), 10).fill({ color: 0x102b38, alpha: .96 }).stroke({ width: 2, color: palette.teal }); const box = new Container(); box.position.copyFrom(bubble.position); box.addChild(bg, bubble); this.world.addChild(box); window.setTimeout(() => box.destroy({ children: true }), 6000); }
  setNames(names: Record<string, string>) { for (const [id, name] of Object.entries(names)) this.names.set(id, name); }
  setBoard(rows: any[]) { this.boardText.text = rows.slice(0, 6).map((r) => `${String(r.name ?? r.employee).slice(0, 14).padEnd(14)} ${String(r.trades ?? 0).padStart(3)}t  ${String(r.net_pnl ?? 0).padStart(8)}`).join("\n") || "awaiting agents"; }
}
