import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import type { OfficeEvent } from "./api";

export type Facility = { id: string; name: string; detail: string; x: number; y: number; w: number; h: number };
type Point = { x: number; y: number };
type ActorView = { seat: string; employee: string; root: Container; label: Text; target: Point; home: Point; thinking: boolean };

// Coordinates follow the cover's 1672 × 941 composition. The scene is drawn
// as layered objects, never as a cover image, so every workstation and person
// can still react to the event stream.
export const WORLD = { width: 1672, height: 941 };
export const FACILITIES: Facility[] = [
  { id: "windows", name: "OBSERVATORY WINDOWS", detail: "The full-height west glass looks over the city and mountain horizon.", x: 0, y: 0, w: 390, h: 700 },
  { id: "data-wall", name: "CENTRAL DATA WALL", detail: "The shared wall of signals, collective memory and research state.", x: 525, y: 205, w: 875, h: 380 },
  { id: "commons", name: "COMMONS TABLE", detail: "The central four-seat table where the office meets as one entity.", x: 590, y: 555, w: 780, h: 260 },
  { id: "manager-office", name: "MANAGER GLASS OFFICE", detail: "The manager's command point above the research floor.", x: 1140, y: 0, w: 430, h: 210 },
  { id: "trader-1", name: "TRADER 1 WORKSTATION", detail: "West workstation: strategy, code, charts and budget.", x: 80, y: 565, w: 430, h: 260 },
  { id: "trader-2", name: "TRADER 2 WORKSTATION", detail: "East workstation: live research and execution surface.", x: 1360, y: 550, w: 300, h: 300 },
  { id: "lounge", name: "RESEARCH LOUNGE", detail: "The foreground lounge for decompression, reading and synthesis.", x: 300, y: 760, w: 600, h: 181 },
];

const C = { sky: 0x071d35, sky2: 0x163552, wall: 0x3b2928, wood: 0xa86a3e, wood2: 0x6b402c, darkWood: 0x2a1b1a, blue: 0x082436, panel: 0x0b2d40, cyan: 0x37d6e1, amber: 0xffb45c, gold: 0xf4d27c, green: 0x3c9f67, leaf: 0x246b45, ink: 0x06131f };
const mono = (size: number, fill = "#e9f5ee", fontWeight: "normal" | "bold" = "normal") => new TextStyle({ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: size, fill, fontWeight });

export class ModernOffice {
  readonly app = new Application();
  private readonly host: HTMLElement; private readonly root = new Container(); private readonly world = new Container(); private readonly actors = new Map<string, ActorView>();
  private readonly seats: Record<string, Point> = { "trader-1": { x: 250, y: 690 }, "trader-2": { x: 1530, y: 710 }, manager: { x: 1175, y: 160 }, boss: { x: 920, y: 735 } };
  private facilityLayer!: Container; private selectedBox!: Graphics; private boardText!: Text; private whiteboardText!: Text; private clockText!: Text; private names = new Map<string, string>(); private onFacility?: (facility: Facility) => void;

  constructor(host: HTMLElement) { this.host = host; }
  async init(onFacility: (facility: Facility) => void) {
    this.onFacility = onFacility; await this.app.init({ resizeTo: this.host, background: "#06131f", antialias: false, resolution: Math.min(2, window.devicePixelRatio || 1) }); this.host.appendChild(this.app.canvas); this.root.sortableChildren = true; this.world.sortableChildren = true; this.root.addChild(this.world); this.app.stage.addChild(this.root); this.drawArchitecture(); this.installFacilities(); this.resize(); window.addEventListener("resize", () => this.resize()); this.app.ticker.add(() => this.tick());
  }
  private resize() { const scale = Math.max(this.host.clientWidth / WORLD.width, this.host.clientHeight / WORLD.height); this.root.scale.set(scale); this.root.position.set((this.host.clientWidth - WORLD.width * scale) / 2, (this.host.clientHeight - WORLD.height * scale) / 2); }

  private drawArchitecture() {
    this.world.addChild(new Graphics().rect(0, 0, WORLD.width, WORLD.height).fill(C.ink)); this.drawWindows(); this.drawRearWall(); this.drawBalcony(); this.drawDataWall(); this.drawSideFurniture(); this.drawCommons(); this.drawLounge(); this.drawPlants(); this.drawLights(); this.drawClock();
    this.boardText = new Text("", mono(13, "#bafcf1")); this.boardText.position.set(600, 270); this.world.addChild(this.boardText); this.whiteboardText = new Text("", new TextStyle({ ...mono(12, "#dceae3"), wordWrap: true, wordWrapWidth: 250 })); this.whiteboardText.position.set(1325, 68); this.world.addChild(this.whiteboardText); this.selectedBox = new Graphics(); this.selectedBox.zIndex = 2000; this.world.addChild(this.selectedBox);
  }

  private drawWindows() {
    const g = new Graphics().rect(0, 0, 382, 700).fill(C.sky2).rect(0, 175, 382, 105).fill(0x354d72).rect(0, 280, 382, 130).fill(0x29496d).rect(0, 410, 382, 290).fill(0x102d4b);
    g.moveTo(0, 400).lineTo(90, 315).lineTo(145, 375).lineTo(220, 290).lineTo(315, 390).lineTo(382, 335).lineTo(382, 520).lineTo(0, 520).closePath().fill(0x1a3558); for (let x = 18; x < 380; x += 31) for (let y = 465 + ((x * 7) % 42); y < 620; y += 28) g.rect(x, y, 4, 4).fill(C.gold); for (const x of [84, 182, 282]) g.rect(x, 0, 7, 690).fill(C.darkWood); g.rect(0, 0, 382, 690).stroke({ width: 9, color: C.wood2 }).rect(0, 665, 382, 28).fill(C.darkWood); this.world.addChild(g);
  }

  private drawRearWall() {
    const g = new Graphics().rect(382, 0, 1290, 600).fill(C.wall).rect(382, 178, 1290, 20).fill(C.darkWood).rect(382, 548, 1290, 26).fill(C.wood2); for (const x of [405, 493, 1455, 1594]) g.rect(x, 0, 17, 600).fill(C.darkWood); this.drawShelf(g, 395, 28, 95, 520); this.drawShelf(g, 1458, 28, 105, 520); this.world.addChild(g);
    const floor = new Graphics().rect(0, 574, WORLD.width, 367).fill(C.wood); for (let y = 595; y < 950; y += 34) floor.moveTo(0, y).lineTo(WORLD.width, y).stroke({ width: 2, color: C.wood2, alpha: .6 }); for (let x = -500; x < 2200; x += 150) floor.moveTo(x, 574).lineTo(x + 420, 941).stroke({ width: 2, color: C.wood2, alpha: .28 }); this.world.addChild(floor);
  }
  private drawShelf(g: Graphics, x: number, y: number, w: number, h: number) { g.rect(x, y, w, h).fill(0x4b2e25); for (let yy = y + 90; yy < y + h; yy += 82) { g.rect(x + 5, yy, w - 10, 7).fill(C.wood2); for (let xx = x + 12; xx < x + w - 10; xx += 22) g.rect(xx, yy - 48 - ((xx + yy) % 20), 11, 44 + ((xx * 3) % 20)).fill([0x31576a, 0xb0663e, 0x8e9b62, 0x4d3b5a][Math.floor((xx + yy) / 22) % 4]); } }

  private drawBalcony() {
    const g = new Graphics().rect(395, 0, 1160, 184).fill(0x182f45).rect(395, 160, 1160, 27).fill(C.darkWood).moveTo(395, 145).lineTo(1555, 145).stroke({ width: 7, color: 0x0a1722 }); for (let x = 430; x < 1540; x += 74) g.rect(x, 100, 5, 48).fill(0x0a1722);
    g.arc(1120, 128, 150, Math.PI, Math.PI * 2).stroke({ width: 18, color: 0x334d67 }); g.rect(1180, 35, 130, 95).fill(0x243d57).stroke({ width: 8, color: 0x0b1d2b }); g.rect(1150, 72, 210, 28).fill(0x53677b); g.roundRect(1090, 56, 120, 34, 15).fill(0xb0803d); g.circle(1085, 73, 25).fill(0x1b2937); this.world.addChild(g); this.drawPerson(new Container(), 980, 122, "human", false); this.drawPerson(new Container(), 1060, 122, "robot", false);
  }

  private drawDataWall() {
    const outer = new Graphics().rect(535, 214, 865, 365).fill(C.panel).stroke({ width: 7, color: C.wood2 }); outer.rect(555, 234, 515, 205).fill(C.blue).stroke({ width: 3, color: C.cyan }); outer.rect(1088, 234, 292, 205).fill(0x0c2940).stroke({ width: 3, color: C.cyan }); outer.rect(555, 452, 825, 105).fill(0x092d3b).stroke({ width: 3, color: C.cyan });
    const nodes = [[665, 330], [735, 285], [810, 350], [875, 300], [945, 370], [760, 405], [1000, 310]]; for (let i = 0; i < nodes.length - 1; i++) outer.moveTo(nodes[i][0], nodes[i][1]).lineTo(nodes[i + 1][0], nodes[i + 1][1]).stroke({ width: 2, color: i % 2 ? C.amber : C.cyan }); for (const [x, y] of nodes) { outer.circle(x, y, 9).fill(C.cyan); outer.circle(x, y, 4).fill(C.gold); } for (let i = 0; i < 8; i++) { outer.rect(1120, 255 + i * 21, 160 + (i % 3) * 24, 7).fill(i % 2 ? C.cyan : C.amber); outer.circle(1100, 258 + i * 21, 5).fill(C.gold); outer.rect(1315, 255 + i * 21, 30, 7).fill(0x456b7e); } for (let i = 0; i < 8; i++) { outer.rect(575 + i * 98, 475, 60, 53).fill(0x0d4b54); for (let j = 0; j < 4; j++) outer.rect(585 + i * 98, 486 + j * 9, 42 + (j % 2) * 12, 4).fill(C.cyan); } this.world.addChild(outer);
  }

  private drawSideFurniture() {
    const g = new Graphics(); g.rect(65, 630, 405, 27).fill(C.darkWood).rect(90, 657, 14, 82).fill(C.darkWood).rect(420, 657, 14, 82).fill(C.darkWood); g.rect(205, 573, 92, 58).fill(C.blue).stroke({ width: 4, color: C.cyan }); g.rect(229, 588, 44, 6).fill(C.cyan); g.rect(229, 602, 57, 6).fill(C.amber); g.rect(330, 575, 8, 55).fill(C.gold).circle(334, 570, 25).fill({ color: C.gold, alpha: .14 }); g.rect(1332, 695, 315, 26).fill(C.darkWood).rect(1360, 721, 13, 100).fill(C.darkWood).rect(1610, 721, 13, 100).fill(C.darkWood); g.rect(1420, 625, 110, 68).fill(C.blue).stroke({ width: 4, color: C.cyan }); g.rect(1440, 642, 65, 6).fill(C.cyan); g.rect(1440, 657, 45, 6).fill(C.amber); g.moveTo(1510, 175).lineTo(1665, 175).lineTo(1665, 620).lineTo(1510, 620).stroke({ width: 16, color: C.darkWood }); for (let i = 0; i < 7; i++) g.moveTo(1515 + i * 24, 175 + i * 55).lineTo(1660, 175 + i * 55).stroke({ width: 9, color: C.wood2 }); for (const [x, y] of [[1550, 310], [1580, 435], [1515, 515]]) g.rect(x, y, 65, 52).fill(0x6c4938).stroke({ width: 4, color: C.gold }); this.world.addChild(g);
  }

  private drawCommons() { const g = new Graphics().rect(555, 590, 825, 265).fill(0x254e51).stroke({ width: 5, color: 0xc99d63 }).rect(580, 610, 775, 225).fill(0x315f5b).stroke({ width: 3, color: 0xa88357 }); g.moveTo(635, 575).lineTo(1285, 575).lineTo(1355, 780).lineTo(565, 780).closePath().fill(0x5b3527).stroke({ width: 7, color: 0x2f201c }); g.rect(785, 600, 95, 60).fill(C.blue).stroke({ width: 4, color: C.cyan }); g.rect(1000, 600, 95, 60).fill(C.blue).stroke({ width: 4, color: C.cyan }); g.circle(940, 635, 45).fill({ color: C.cyan, alpha: .16 }).stroke({ width: 3, color: C.cyan }); for (const [x, y] of [[690, 705], [815, 735], [1070, 735], [1200, 705]]) g.roundRect(x, y, 62, 68, 8).fill(0x152d3b).stroke({ width: 3, color: 0x0b1a27 }); this.world.addChild(g); }
  private drawLounge() { const g = new Graphics().rect(310, 790, 470, 125).fill(0x254c43).stroke({ width: 7, color: 0x172d2e }).rect(390, 748, 90, 105).fill(0x2f5b50).rect(520, 748, 90, 105).fill(0x2f5b50).rect(650, 790, 130, 110).fill(0x2f5b50); g.rect(565, 830, 180, 70).fill(C.wood2).stroke({ width: 5, color: C.darkWood }); g.rect(595, 845, 65, 22).fill(C.blue); g.rect(680, 845, 45, 22).fill(0x7e4e36); this.world.addChild(g); }
  private drawPlants() { for (const [x, y, s] of [[430, 620, 1], [1420, 610, 1.3], [55, 850, 1.7], [820, 540, .8], [1260, 550, .9], [1600, 820, 1.1]] as [number, number, number][]) { const g = new Graphics().rect(x - 18 * s, y, 36 * s, 42 * s).fill(C.wood2).circle(x, y - 45 * s, 38 * s).fill(C.leaf).circle(x - 28 * s, y - 22 * s, 24 * s).fill(C.green).circle(x + 28 * s, y - 18 * s, 24 * s).fill(C.green); this.world.addChild(g); } }
  private drawLights() { const g = new Graphics(); for (const x of [520, 690, 900, 1130, 1350]) { g.moveTo(x, 0).lineTo(x, 45).stroke({ width: 3, color: C.darkWood }); g.rect(x - 10, 44, 20, 24).fill(C.gold); g.circle(x, 72, 27).fill({ color: C.gold, alpha: .12 }); } this.world.addChild(g); }
  private drawClock() { this.clockText = new Text("--:--", mono(18, "#f4ae55", "bold")); this.clockText.position.set(1560, 35); this.world.addChild(this.clockText); }

  private installFacilities() { this.facilityLayer = new Container(); for (const facility of FACILITIES) { const hit = new Graphics().rect(facility.x, facility.y, facility.w, facility.h).fill({ color: C.cyan, alpha: .001 }); hit.eventMode = "static"; hit.cursor = "pointer"; hit.on("pointerover", () => this.highlight(facility)); hit.on("pointerout", () => this.highlight()); hit.on("pointertap", () => this.onFacility?.(facility)); this.facilityLayer.addChild(hit); } this.facilityLayer.zIndex = 1900; this.world.addChild(this.facilityLayer); }
  private highlight(facility?: Facility) { this.selectedBox.clear(); if (facility) this.selectedBox.roundRect(facility.x, facility.y, facility.w, facility.h, 8).fill({ color: C.cyan, alpha: .07 }).stroke({ width: 3, color: C.cyan, alpha: .8 }); }
  private tick() { this.clockText.text = new Date().toTimeString().slice(0, 5); for (const actor of this.actors.values()) { actor.root.x += (actor.target.x - actor.root.x) * .08; actor.root.y += (actor.target.y - actor.root.y) * .08; actor.label.position.set(actor.root.x - actor.label.width / 2, actor.root.y + 42); } }
  private drawPerson(parent: Container, x: number, y: number, role: string, add = true) { const root = new Container(); root.position.set(x, y); const body = new Graphics().ellipse(0, 35, 18, 7).fill({ color: 0x000000, alpha: .4 }).roundRect(-13, 0, 26, 34, 7).fill(role === "robot" ? 0xd3e5e6 : 0x2d596d).circle(0, -12, 13).fill(role === "robot" ? 0xdbe7e5 : 0x3b241b); if (role === "robot") { body.rect(-7, -14, 14, 7).fill(C.blue); body.circle(-4, -11, 2).fill(C.cyan); body.circle(4, -11, 2).fill(C.cyan); } root.addChild(body); if (add) parent.addChild(root); else this.world.addChild(root); return root; }
  private ensureActor(employee: string, role = employee.startsWith("trader") ? "trader" : employee) { const seat = employee.startsWith("trader") ? employee.split(".")[0] : role; if (this.actors.has(seat)) return this.actors.get(seat)!; const home = this.seats[seat] ?? this.seats["trader-1"]; const root = this.drawPerson(new Container(), home.x, home.y, role === "manager" ? "human" : role === "robot" ? "robot" : "human"); root.zIndex = home.y; const label = new Text(this.names.get(employee) ?? employee, mono(12, "#e9fff4", "bold")); label.position.set(-label.width / 2, 42); root.addChild(label); const actor = { seat, employee, root, label, target: { ...home }, home: { ...home }, thinking: false }; this.actors.set(seat, actor); return actor; }
  apply(event: OfficeEvent, _animate = true) { const p = event.payload ?? {}; if (event.kind === "hire" && p.role !== "boss") { this.ensureActor(p.employee, p.role); return; } if (event.kind === "name") { this.names.set(p.employee, p.name); this.ensureActor(p.employee).label.text = p.name; return; } if (event.kind === "fire") { const seat = event.payload?.employee?.startsWith("trader") ? event.payload.employee.split(".")[0] : event.payload.employee; this.actors.get(seat)?.root.destroy({ children: true }); this.actors.delete(seat); return; } if (!event.actor || event.actor === "office") return; const actor = this.ensureActor(event.actor); if (event.kind === "meeting") for (const a of this.actors.values()) a.target = p.phase === "start" ? { x: 920 + (a.seat === "trader-1" ? -170 : a.seat === "trader-2" ? 170 : 0), y: 690 } : { ...a.home }; if (event.kind === "say" && p.text) this.toast(actor, String(p.text)); }
  private toast(actor: ActorView, message: string) { const bubble = new Text(message.length > 85 ? `${message.slice(0, 82)}…` : message, new TextStyle({ ...mono(12, "#e9fff4"), wordWrap: true, wordWrapWidth: 270 })); bubble.position.set(actor.root.x - 135, actor.root.y - 80); const box = new Container(); box.position.copyFrom(bubble.position); box.addChild(new Graphics().roundRect(-10, -8, 290, Math.max(38, bubble.height + 16), 8).fill({ color: C.blue, alpha: .96 }).stroke({ width: 2, color: C.cyan }), bubble); this.world.addChild(box); window.setTimeout(() => box.destroy({ children: true }), 6000); }
  setNames(names: Record<string, string>) { for (const [id, name] of Object.entries(names)) this.names.set(id, name); }
  setBoard(rows: any[]) { this.boardText.text = rows.slice(0, 7).map((r) => `${String(r.name ?? r.employee).slice(0, 13).padEnd(13)} ${String(r.trades ?? 0).padStart(3)}t ${String(r.net_pnl ?? 0).padStart(8)}`).join("\n") || "awaiting agents"; }
}
