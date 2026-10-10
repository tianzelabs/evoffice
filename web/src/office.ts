// The room. It renders the office's event stream and nothing else: the office
// looks the way it does because of events, never the other way round.
//
// The user's rules for the room:
//   - people work or talk about work; nobody wanders.
//   - talking follows physics: to speak to someone, walk over to them, talk face
//     to face, walk back. Speaking to everyone happens at one's own desk. The boss
//     is not in the office; speaking to the boss from inside is a phone call, and
//     the boss walks in through the door to speak.
//
//   agent_state thinking -> typing at the desk, the screen scrolls, "..." overhead
//   agent_state idle     -> sitting at the desk
//   agent_state asleep   -> "zZz" and the reason
//   wake / version / evaluation / open / close / command / fire -> effects at the desk
//
// Art: Kenney's Roguelike Indoors and Roguelike Characters (CC0, kenney.nl) -- see
// public/kenney/README.txt. Monitors, coffee machine, water cooler, keyboards, lamps,
// rugs and the floor are drawn in code (pixels.ts and below): the packs have none.
import * as Phaser from "phaser";
import { makeTextures, SCALE } from "./pixels";
import type { OfficeEvent } from "./net";

export const W = 960, H = 600;
type Pt = { x: number; y: number };
const T = 16 * SCALE;                                        // one Kenney tile on screen: 48 px
const IN = (c: number, r: number) => r * 27 + c;             // frame in the indoor sheet (27 columns)
const PEOPLE_FRAME: Record<string, number> = { "trader-1": 0, "trader-2": 1, manager: 2, boss: 3 };
const TXT = (size: number, color: string, extra: object = {}) =>
  ({ resolution: 3, fontFamily: "monospace", fontSize: `${size}px`, color, ...extra });

// A workplace: where the desk is (centre x, front edge y), where its owner sits,
// and where a visitor stands to talk to them face to face.
type Place = { desk: Pt; seat: Pt; visit: Pt; plate: string };
const placeAt = (x: number, y: number, plate: string): Place =>
  ({ desk: { x, y }, seat: { x, y: y - 22 }, visit: { x: x + 128, y: y - 4 }, plate });
const TRADER_PLACES: Place[] = [placeAt(220, 360, "TRADER 1"), placeAt(500, 360, "TRADER 2")];
const MANAGER_PLACE: Place = { ...placeAt(822, 300, "MANAGER"), visit: { x: 726, y: 296 } };
const DOOR: Pt = { x: 660, y: 592 }, BOSS_SPOT: Pt = { x: 640, y: 470 };
// seats around the meeting table (table spans x 378-522, y 468-564): the chair, then the sides
const MEETING_SEATS: Record<string, Pt> = {
  manager: { x: 450, y: 470 }, "trader-1": { x: 352, y: 540 }, "trader-2": { x: 548, y: 540 }, boss: { x: 450, y: 590 },
};

class Actor {
  sprite: Phaser.GameObjects.Image;
  shadow: Phaser.GameObjects.Ellipse;
  label: Phaser.GameObjects.Text;
  bubble?: Phaser.GameObjects.Container;
  dots?: Phaser.GameObjects.Text;
  walking = false;
  thinking = false;
  frame = 0;
  private queue: Promise<void> = Promise.resolve();

  constructor(private scene: OfficeScene, public role: string, public name: string, public place: Place | null, frame: number, at: Pt) {
    this.shadow = scene.add.ellipse(at.x, at.y, 34, 10, 0x000000, 0.18);
    this.sprite = scene.add.image(at.x, at.y, "people", frame).setScale(SCALE).setOrigin(0.5, 1);
    this.label = scene.add.text(at.x, at.y + 4, name, TXT(11, "#1d1d1f", { backgroundColor: "#ffffffcc", padding: { x: 3, y: 1 } }))
      .setOrigin(0.5, 0).setVisible(false);              // names live on the desk plates; shown only while away
    this.sync();
  }

  get pos(): Pt { return { x: this.sprite.x, y: this.sprite.y }; }
  get home(): Pt { return this.meetingSeat ?? (this.place ? this.place.seat : DOOR); }
  meetingSeat: Pt | null = null;
  get atHome(): boolean { return Math.abs(this.sprite.x - this.home.x) < 3 && Math.abs(this.sprite.y - this.home.y) < 3; }

  sync() {
    const { x, y } = this.sprite;
    this.sprite.setDepth(y);
    this.shadow.setPosition(x, y - 2).setDepth(y - 1);
    this.label.setPosition(x, y + 4).setDepth(y + 1).setVisible(!this.atHome && this.sprite.alpha > 0);
    this.bubble?.setPosition(x, y - 16 * SCALE - 8).setDepth(10_000);
    this.dots?.setPosition(x, y - 16 * SCALE - 6).setDepth(10_000);
  }

  /** run steps one after another, so two messages in a row never tear the actor in two */
  then(step: () => Promise<void>) { this.queue = this.queue.then(step).catch(() => {}); return this.queue; }

  walkTo(p: Pt): Promise<void> {
    return new Promise((done) => {
      const d = Phaser.Math.Distance.Between(this.sprite.x, this.sprite.y, p.x, p.y);
      if (d < 4) { this.sync(); return done(); }
      this.sprite.setFlipX(p.x < this.sprite.x);
      this.walking = true;
      this.scene.tweens.add({
        targets: this.sprite, x: p.x, y: p.y, duration: (d / 120) * 1000, ease: "Sine.easeInOut",
        onUpdate: () => this.sync(),
        onComplete: () => { this.walking = false; this.sprite.setScale(SCALE); this.sync(); done(); },
      });
    });
  }

  face(p: Pt) { this.sprite.setFlipX(p.x < this.sprite.x); }

  step() {
    if (this.walking) { this.frame ^= 1; this.sprite.setScale(SCALE, this.frame ? SCALE * 0.94 : SCALE); return; }
    if (this.thinking && this.atHome) {                 // typing: a small, quick nod over the keyboard
      this.frame ^= 1; this.sprite.setScale(SCALE, this.frame ? SCALE * 0.97 : SCALE);
    } else this.sprite.setScale(SCALE);
  }

  say(text: string, icon = ""): Promise<void> {
    this.bubble?.destroy();
    const t = (icon ? icon + " " : "") + (text.length > 220 ? text.slice(0, 217) + "…" : text);
    const body = this.scene.add.text(0, 0, t, TXT(13, "#111", { wordWrap: { width: 240, useAdvancedWrap: true } })).setOrigin(0.5, 1);
    const bw = body.width + 16, bh = body.height + 12;
    const g = this.scene.add.graphics();
    g.fillStyle(0xffffff, 0.97).fillRoundedRect(-bw / 2, -bh - 6, bw, bh, 6);
    g.lineStyle(2, 0x1d1d1f, 1).strokeRoundedRect(-bw / 2, -bh - 6, bw, bh, 6);
    g.fillStyle(0xffffff, 1).fillTriangle(-6, -7, 6, -7, 0, 2);
    body.setPosition(0, -12);
    const bubble = this.scene.add.container(0, 0, [g, body]);
    this.bubble = bubble;
    this.sync();
    const ms = Math.min(14_000, 3500 + t.length * 45);
    return new Promise((done) => this.scene.time.delayedCall(ms, () => {
      bubble.destroy();
      if (this.bubble === bubble) this.bubble = undefined;
      done();
    }));
  }

  setThinking(on: boolean) {
    this.thinking = on;
    if (on && !this.dots) {
      this.dots = this.scene.add.text(0, 0, "", TXT(18, "#1d1d1f", { backgroundColor: "#ffffffdd", padding: { x: 4, y: 0 } })).setOrigin(0.5, 1);
      this.sync();
    } else if (!on) {
      this.dots?.destroy(); this.dots = undefined;
    }
  }

  tickDots(n: number) { this.dots?.setText(".".repeat((n % 3) + 1).padEnd(3, " ")); }
  rename(name: string) { this.name = name; this.label.setText(name); }

  fade(to: number): Promise<void> {
    return new Promise((done) => this.scene.tweens.add({ targets: [this.sprite, this.shadow], alpha: to, duration: 500,
      onComplete: () => { this.sync(); done(); } }));
  }
}

export class OfficeScene extends Phaser.Scene {
  actors: Record<string, Actor | undefined> = {};      // keyed by seat: "trader-1", "trader-2", "manager", "boss"
  seatOf: Record<string, string> = {};     // employee id -> seat
  // who sits there NOW. Found live: the fired trader-1's progress kept writing "KESTREL" onto the
  // plate its successor had taken -- only the current occupant may touch a seat's plate, bars, cups.
  occupant: Record<string, string> = {};
  plates: Record<string, Phaser.GameObjects.Text> = {};
  bars: Record<string, Phaser.GameObjects.Graphics> = {};      // per plate: XP (gold) and budget left (green)
  levels: Record<string, string> = {};                        // employee id -> "Lv2"
  cups: Record<string, Phaser.GameObjects.Text> = {};         // per plate: trophies on the desk
  screens: { chart: Phaser.GameObjects.Graphics; code: Phaser.GameObjects.Graphics; price: Phaser.GameObjects.Text; place: Place }[] = [];
  screenText!: Phaser.GameObjects.Text;
  whiteboard!: Phaser.GameObjects.Text;
  sky!: Phaser.GameObjects.Graphics;
  night!: Phaser.GameObjects.Graphics;
  lamps: Phaser.GameObjects.Ellipse[] = [];
  clock!: Phaser.GameObjects.Text;
  tick = 0;
  meeting = false;
  alarm!: Phaser.GameObjects.Graphics;
  alarmText?: Phaser.GameObjects.Text;
  nameOf: (id: string) => string = (id) => id;
  ready!: Promise<void>;
  private resolveReady!: () => void;

  constructor() {
    super("office");
    this.ready = new Promise((r) => (this.resolveReady = r));
  }

  preload() {
    this.load.spritesheet("indoor", "/kenney/indoor.png", { frameWidth: 16, frameHeight: 16, spacing: 1 });
    this.load.spritesheet("people", "/kenney/people.png", { frameWidth: 16, frameHeight: 16 });
  }

  create() {
    makeTextures(this);
    this.drawRoom();
    this.time.addEvent({ delay: 160, loop: true, callback: () => Object.values(this.actors).forEach((a) => a?.step()) });
    this.time.addEvent({ delay: 400, loop: true, callback: () => { this.tick++; Object.values(this.actors).forEach((a) => a?.tickDots(this.tick)); this.drawCode(); } });
    this.time.addEvent({ delay: 30_000, loop: true, callback: () => this.paintSky() });
    this.resolveReady();
  }

  // ---------- the room ----------
  tile(c: number, r: number, x: number, y: number, depth = y) {
    return this.add.image(x, y, "indoor", IN(c, r)).setScale(SCALE).setOrigin(0, 1).setDepth(depth);
  }

  drawRoom() {
    const g = this.add.graphics().setDepth(-20);
    for (let y = 130; y < H; y += 22) {                                     // floor: warm planks
      g.fillStyle(((y / 22) | 0) % 2 ? 0xc89f72 : 0xd2ab7f).fillRect(0, y, W, 22);
      g.fillStyle(0xb8905f);
      g.fillRect(0, y, W, 2);
      for (let x = (((y / 22) | 0) % 3) * 50; x < W; x += 150) g.fillRect(x, y, 2, 22);
    }
    g.fillStyle(0xe6dccb).fillRect(0, 0, W, 130);                         // wall
    g.fillStyle(0xd8ccb7).fillRect(0, 96, W, 34);                          // wainscot
    g.fillStyle(0x8f7a5c).fillRect(0, 124, W, 8);                          // skirting
    this.sky = this.add.graphics().setDepth(-19);
    for (const x0 of [24, 152]) {                                          // two windows with sills
      g.lineStyle(6, 0x6b5638, 1);
      g.fillStyle(0x6b5638).fillRect(x0 - 6, 90, 122, 7);
    }
    const frames = this.add.graphics().setDepth(-18);
    for (const x0 of [24, 152]) {
      frames.lineStyle(6, 0x6b5638, 1).strokeRect(x0, 14, 110, 76);
      frames.lineBetween(x0 + 55, 14, x0 + 55, 90);
    }
    // the leaderboard screen
    g.fillStyle(0x24242b).fillRoundedRect(292, 8, 330, 106, 6);
    g.fillStyle(0x0d1a12).fillRect(300, 15, 314, 92);
    this.add.text(310, 19, "LEADERBOARD", TXT(12, "#5dff9a")).setDepth(-8);
    this.screenText = this.add.text(310, 38, "", TXT(12, "#a8f0c0", { lineSpacing: 3 })).setDepth(-8);
    // the manager's whiteboard: the latest instruction in the room
    g.fillStyle(0x9a9aa2).fillRoundedRect(640, 10, 220, 104, 4);
    g.fillStyle(0xfbfbf8).fillRect(646, 16, 208, 92);
    this.add.text(652, 19, "MANAGER SAYS", TXT(10, "#1a5fb4")).setDepth(-8);
    this.whiteboard = this.add.text(652, 34, "", TXT(10, "#2a2a2a", { wordWrap: { width: 196, useAdvancedWrap: true }, lineSpacing: 1, maxLines: 6 })).setDepth(-8);
    this.clock = this.add.text(910, 40, "", TXT(15, "#3a2f22")).setOrigin(0.5).setDepth(-8);
    // rugs under the work areas
    g.fillStyle(0x6f8fae, 0.30).fillRoundedRect(110, 300, 520, 88, 12);
    g.fillStyle(0x7e9e7a, 0.26).fillRoundedRect(712, 236, 220, 92, 12);
    g.fillStyle(0xa0645a, 0.28).fillRoundedRect(300, 470, 300, 96, 12);   // under the meeting table
    // the manager's glass office
    g.fillStyle(0xbfe3f7, 0.10).fillRect(690, 136, 264, 270);
    const glass = this.add.graphics().setDepth(420);
    glass.lineStyle(4, 0x8cc3e4, 0.9);
    glass.lineBetween(690, 136, 954, 136); glass.lineBetween(954, 136, 954, 406); glass.lineBetween(690, 406, 954, 406);
    glass.lineBetween(690, 136, 690, 270); glass.lineBetween(690, 340, 690, 406);
    this.tile(4, 13, 890, 196, 196);                                       // a cabinet in the manager's office
    this.tile(17, 0, 905, 400, 400);
    // workplaces
    [...TRADER_PLACES, MANAGER_PLACE].forEach((p) => this.workplace(p));
    // the meeting table: where the office sits down together
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) this.tile(i, 9 + j, 378 + i * T, 516 + j * T, 516 + j * T);
    [[2, 2, 330, 548], [3, 2, 528, 548]].forEach(([c, r, x, y]) => this.tile(c, r, x, y));
    this.add.text(450, 568, "MEETING", TXT(9, "#6b5638")).setOrigin(0.5, 0).setDepth(-8);
    // a bookshelf wall on the right
    [[0, 15], [1, 15], [4, 15]].forEach(([c, r], i) => this.tile(c, r, 708 + i * T, 470, 470));
    // the coffee corner and the back wall
    [[4, 13], [7, 13], [1, 13]].forEach(([c, r], i) => this.tile(c, r, 300 + i * T, 180, 180));
    this.add.image(470, 168, "coffee").setScale(SCALE).setOrigin(0.5, 1).setDepth(168);
    this.add.image(560, 168, "cooler").setScale(SCALE).setOrigin(0.5, 1).setDepth(168);
    this.tile(16, 0, 20, 186); this.tile(17, 0, 236, 186); this.tile(16, 0, 250, 580); this.tile(17, 0, 20, 580);
    this.tile(16, 0, 880, 580);
    g.fillStyle(0x4a3a28).fillRect(620, 594, 80, 6);                       // the door
    this.add.text(660, 586, "ENTRANCE", TXT(9, "#6b5638")).setOrigin(0.5, 1).setDepth(-8);
    // night: the room darkens and desk lamps glow
    this.night = this.add.graphics().setDepth(9_000);
    this.alarm = this.add.graphics().setDepth(9_002);
    this.paintSky();
  }

  workplace(p: Place) {
    const { x, y } = p.desk;
    const g = this.add.graphics().setDepth(y - 60);
    g.fillStyle(0x000000, 0.16).fillEllipse(x, y + 4, 210, 18);           // shadow under the desk
    for (let i = 0; i < 4; i++) this.tile(i === 0 ? 4 : i === 3 ? 7 : 5 + (i % 2), 6, x - 96 + i * T, y, y);
    this.tile(1, 8, x - 24, y - 30, y - 60);                               // the chair, behind the desk
    // two monitors on the desk corners, a keyboard and a mug in between, a lamp
    this.add.image(x - 62, y - 26, "monitor").setScale(SCALE).setOrigin(0.5, 1).setDepth(y + 2);
    const right = this.add.image(x + 62, y - 26, "monitor").setScale(SCALE).setOrigin(0.5, 1).setDepth(y + 2);
    const d = this.add.graphics().setDepth(y + 3);
    d.fillStyle(0x2b2b33).fillRoundedRect(x - 22, y - 40, 44, 9, 2);       // keyboard
    d.fillStyle(0x4a4a55);
    for (let k = 0; k < 6; k++) d.fillRect(x - 19 + k * 7, y - 38, 5, 2);
    d.fillStyle(0xf2f2f2).fillRect(x + 28, y - 44, 9, 10);                 // mug
    d.fillStyle(0x6b4a2f).fillRect(x + 29, y - 43, 7, 3);
    d.fillStyle(0x3a3a3a).fillRect(x - 98, y - 58, 3, 18);                 // lamp
    d.fillStyle(0xe8c547).fillTriangle(x - 104, y - 58, x - 88, y - 58, x - 96, y - 66);
    this.lamps.push(this.add.ellipse(x - 96, y - 52, 120, 60, 0xffd27a, 0).setDepth(9_001));
    // the name plate on the desk front, and under it the XP and energy bars
    this.plates[p.plate] = this.add.text(x, y - 6, p.plate, TXT(9, "#3a2f22", { backgroundColor: "#f4e6c8", padding: { x: 4, y: 1 } }))
      .setOrigin(0.5, 1).setDepth(y + 4);
    this.bars[p.plate] = this.add.graphics().setDepth(y + 4);
    if (p !== MANAGER_PLACE) {
      const code = this.add.graphics().setDepth(y + 3);
      const chart = this.add.graphics().setDepth(y + 3);
      const price = this.add.text(right.x, y - 84, "", TXT(10, "#5dff9a")).setOrigin(0.5).setDepth(y + 4);
      this.screens.push({ chart, code, price, place: p });
    }
  }

  paintSky() {
    const h = new Date().getHours();
    const dark = h >= 21 || h < 6, dusk = (h >= 18 && h < 21) || (h >= 6 && h < 8);
    const sky = dark ? 0x14203a : dusk ? 0xf0a35e : 0x8ecdf0;
    if (!this.sky) return;
    this.sky.clear();
    for (const x0 of [24, 152]) {
      this.sky.fillStyle(sky).fillRect(x0, 14, 110, 76);
      this.sky.fillStyle(dark ? 0x0b1222 : 0x6d7f8f);
      [[8, 46, 18, 30], [30, 36, 16, 40], [50, 54, 22, 22], [76, 40, 18, 36], [96, 50, 14, 26]]
        .forEach(([dx, y, w, hh]) => this.sky.fillRect(x0 + dx, y, w, hh));
      if (dark) { this.sky.fillStyle(0xfff4c2); [[12, 24], [62, 20], [92, 30]].forEach(([dx, y]) => this.sky.fillRect(x0 + dx, y, 2, 2)); }
    }
    this.night?.clear();
    if (dark) this.night?.fillStyle(0x0a1030, 0.28).fillRect(0, 0, W, H);
    else if (dusk) this.night?.fillStyle(0x3a1d00, 0.08).fillRect(0, 0, W, H);
    this.lamps.forEach((l) => l.setFillStyle(0xffd27a, dark ? 0.22 : dusk ? 0.1 : 0));
    this.clock?.setText(new Date().toTimeString().slice(0, 5));
  }

  // ---------- people ----------
  seat(employee: string): string {
    if (this.seatOf[employee]) return this.seatOf[employee];
    const s = employee.startsWith("trader") ? employee.split(".")[0] : employee;
    this.seatOf[employee] = s;
    return s;
  }

  placeOf(seat: string): Place | null {
    if (seat === "manager") return MANAGER_PLACE;
    if (seat.startsWith("trader")) return TRADER_PLACES[Math.min(TRADER_PLACES.length - 1, Math.max(0, parseInt(seat.split("-")[1] ?? "1", 10) - 1))];
    return null;
  }

  actor(employee: string): Actor | undefined {
    const seat = this.seat(employee);
    if (this.actors[seat]) return this.actors[seat];
    if (seat === "boss") {                    // not in the office until it comes in to speak
      const b = new Actor(this, "boss", "boss", null, PEOPLE_FRAME.boss, DOOR);
      b.sprite.setAlpha(0); b.shadow.setAlpha(0); b.sync();
      return (this.actors[seat] = b);
    }
    const place = this.placeOf(seat);
    if (!place) return undefined;
    const role = seat === "manager" ? "manager" : "trader";
    this.occupant[seat] ??= employee;
    const a = new Actor(this, role, this.nameOf(employee), place, PEOPLE_FRAME[seat] ?? 0, place.seat);
    this.plates[place.plate]?.setText(this.nameOf(employee).toUpperCase());
    return (this.actors[seat] = a);
  }

  plateText(employee: string) {
    const lv = this.levels[employee];
    return (this.nameOf(employee) + (lv ? " · " + lv : "")).toUpperCase();
  }

  /** XP toward the next level (gold) and today's budget left (green) under each trader's plate */
  setProgress(progress: Record<string, any>, budgets: any[]) {
    for (const [id, p] of Object.entries(progress)) {
      this.levels[id] = `Lv${p.level}${p.probation ? " (probation)" : ""}`;
      if (this.occupant[this.seat(id)] !== id) continue;
      const a = this.actors[this.seat(id)];
      if (!a?.place) continue;
      this.plates[a.place.plate]?.setText(this.plateText(id));
      const b = budgets.find((x) => x.employee === id);
      const lvls = [0, 60, 150, 300, 600], cur = lvls[p.level - 1] ?? 0, nxt = p.next_level_xp;
      const xpFrac = nxt ? Math.min(1, (p.xp - cur) / (nxt - cur)) : 1;
      const energy = b ? Math.max(0, b.left_usd / Math.max(1e-9, b.cap_usd)) : 1;
      const { x, y } = a.place.desk;
      const g = this.bars[a.place.plate];
      g.clear();
      g.fillStyle(0x000000, 0.35).fillRect(x - 40, y + 2, 80, 4).fillRect(x - 40, y + 8, 80, 4);
      g.fillStyle(0xe8c547).fillRect(x - 40, y + 2, 80 * xpFrac, 4);
      g.fillStyle(energy > 0.25 ? 0x5dcf7a : 0xd9534f).fillRect(x - 40, y + 8, 80 * energy, 4);
    }
  }

  /** trophies won so far, on each winner's desk */
  setTrophies(trophies: Record<string, any[]>) {
    for (const [id, list] of Object.entries(trophies)) {
      if (this.occupant[this.seat(id)] !== id) continue;
      const a = this.actors[this.seat(id)];
      if (!a?.place) continue;
      const key = a.place.plate, { x, y } = a.place.desk;
      this.cups[key]?.destroy();
      const n = list.length;
      this.cups[key] = this.add.text(x + 88, y - 44, n > 3 ? `🏆×${n}` : "🏆".repeat(n), TXT(12, "#b8860b")).setOrigin(1, 1).setDepth(y + 5);
    }
  }

  bossPresent(): boolean { return (this.actors.boss?.sprite.alpha ?? 0) > 0.5; }

  float(at: Pt, text: string, color = "#1d1d1f", icon?: string) {
    const objs: Phaser.GameObjects.GameObject[] = [];
    const t = this.add.text(at.x, at.y, text, TXT(13, color, { fontStyle: "bold", backgroundColor: "#ffffffd9", padding: { x: 4, y: 2 } }))
      .setOrigin(0.5, 1).setDepth(10_001);
    objs.push(t);
    if (icon) objs.push(this.add.image(at.x - t.width / 2 - 14, at.y - 10, icon).setScale(SCALE).setDepth(10_001));
    this.tweens.add({ targets: objs, y: "-=36", alpha: 0, delay: 2400, duration: 1600, onComplete: () => objs.forEach((o) => o.destroy()) });
  }

  over(a: Actor): Pt { return { x: a.pos.x, y: a.pos.y - 16 * SCALE - 28 }; }

  // ---------- talking, by the rules of the room ----------
  converse(speaker: Actor, to: string | null, text: string) {
    const target = to ? this.actors[this.seat(to)] : undefined;
    if (this.meeting && speaker.role !== "boss") {          // already face to face at the table
      speaker.then(async () => { if (target) speaker.face(target.pos); await speaker.say(text); });
      return;
    }
    if (this.meeting && speaker.role === "boss") {
      speaker.then(async () => {
        if (!this.bossPresent()) { speaker.sprite.setPosition(DOOR.x, DOOR.y); await speaker.fade(1); }
        speaker.meetingSeat = MEETING_SEATS.boss;
        await speaker.walkTo(MEETING_SEATS.boss);
        await speaker.say(text);
      });
      return;
    }
    if (speaker.role === "boss") {
      speaker.then(async () => {
        if (!this.bossPresent()) { speaker.sprite.setPosition(DOOR.x, DOOR.y); await speaker.fade(1); }
        await speaker.walkTo(target?.place ? { x: target.place.seat.x - 110, y: target.place.seat.y + 18 } : BOSS_SPOT);
        if (target) speaker.face(target.pos);
        await speaker.say(text);
        this.time.delayedCall(12_000, () => speaker.then(async () => { await speaker.walkTo(DOOR); await speaker.fade(0); }));
      });
      return;
    }
    if (!to) { speaker.then(() => speaker.say(text)); return; }            // to everyone: from one's own desk
    if (to === "boss" && !this.bossPresent()) { speaker.then(() => speaker.say(text, "☎")); return; }   // a phone call
    if (!target) { speaker.then(() => speaker.say(text)); return; }
    speaker.then(async () => {
      const where = target.role === "boss" ? { x: target.pos.x + 70, y: target.pos.y } : target.place!.visit;
      await speaker.walkTo(where);
      speaker.face(target.pos);
      target.face(speaker.pos);
      await speaker.say(text);
      await speaker.walkTo(speaker.home);
      speaker.face({ x: speaker.pos.x + 1, y: 0 });
    });
  }

  // ---------- events -> the room ----------
  apply(e: OfficeEvent, live: boolean) {
    const p = e.payload;
    if (e.kind === "hire") { this.seat(p.employee); if (p.role !== "boss") this.actor(p.employee); return; }
    if (e.kind === "name") {
      const a = this.actor(p.employee);
      if (a) {
        a.rename(p.name);
        if (a.place) this.plates[a.place.plate]?.setText(this.plateText(p.employee));
        if (live) this.float(this.over(a), `I'm ${p.name}`, "#1a5fb4");
      }
      return;
    }
    if (e.kind === "fire") {
      const seat = this.seat(p.employee);
      const a = this.actor(p.employee);
      if (!a) return;
      const plate = a.place?.plate;
      if (!p.successor) {                       // the boss closed the seat: the desk is left empty
        this.occupant[seat] = "";
        const clear = () => {
          if (plate) { this.plates[plate]?.setText(""); this.bars[plate]?.clear(); this.cups[plate]?.destroy(); }
          delete this.actors[seat];
        };
        if (!live) { a.sprite.setAlpha(0); a.shadow.setAlpha(0); a.sync(); clear(); return; }
        a.then(async () => {
          this.float(this.over(a), "LEFT THE OFFICE", "#5a5a6e");
          await a.walkTo(DOOR); await a.fade(0); clear();
        });
        return;
      }
      this.seatOf[p.successor] = seat;
      this.occupant[seat] = p.successor;
      if (plate) this.cups[plate]?.destroy();
      if (!live) { a.rename(this.nameOf(p.successor)); if (plate) this.plates[plate]?.setText(this.nameOf(p.successor).toUpperCase()); return; }
      a.then(async () => {
        this.float(this.over(a), "FIRED", "#c62828");
        await a.say(`fired: ${p.reason}`);
        await a.walkTo(DOOR); await a.fade(0);
        a.rename(this.nameOf(p.successor));
        if (plate) this.plates[plate]?.setText(this.nameOf(p.successor).toUpperCase());
        await a.fade(1);
        await a.walkTo(a.home);
        await a.say("Hi, I'm new here.");
      });
      return;
    }
    if (e.actor === "office") return;
    const a = this.actor(e.actor);
    if (!a) return;
    if (e.kind === "meeting") { this.setMeeting(p.phase === "start", live); return; }
    if (e.kind === "alert") { if (live) this.soundAlarm(p.text ?? "MARKET ALERT"); return; }
    if (e.kind === "agent_state") {
      a.setThinking(p.state === "thinking");
      if (p.state === "asleep" && live) a.then(() => a.say(`zZz — ${p.why ?? "asleep"}`));
      return;
    }
    if (e.kind === "say" && e.actor === "manager") {
      const t = String(p.text);
      this.whiteboard.setText((p.to ? `→ ${p.to}: ` : "") + (t.length > 170 ? t.slice(0, 167) + "…" : t));
    }
    if (!live) return;                          // replay restores state; only live events animate
    switch (e.kind) {
      case "say": this.converse(a, p.to ?? null, p.text); break;
      case "wake": this.float(this.over(a), "!", "#c62828", "alert"); break;
      case "level": this.float(this.over(a), `LEVEL UP! ${p.title}`, "#b8860b", "bulb"); break;
      case "award": if (p.award) this.float(this.over(a), `🏆 ${p.title}`, "#b8860b"); break;
      case "badge": this.float(this.over(a), `🏅 ${p.title}`, "#7a5a00"); break;
      case "version": this.float(this.over(a), `new strategy ${String(p.version ?? "").slice(0, 6)}`, "#7a5a00", "bulb"); break;
      case "evaluation":
        this.float(this.over(a), `held-out: ${p.net_bps_per_trade ?? "–"} bps/trade`, (p.net_bps_per_trade ?? -1) > 0 ? "#1b7a3d" : "#c62828");
        break;
      case "task": this.converse(a, p.to ?? null, `TASK: ${String(p.text)}`); break;
      case "task_result":
        this.float(this.over(a), p.error ? "✗ task failed" : "✓ task done", p.error ? "#c62828" : "#1b7a3d");
        break;
      case "repl": this.float(this.over(a), `⌨ shared REPL · ${p.lines} lines`, "#5a5a6e"); break;
      case "trigger": this.float(this.over(a), "⚡ trigger → manager", "#b8860b", "alert"); break;
      case "backtest":
        this.float(this.over(a), `🔬 ${p.error ? "bug" : (p.net_bps_per_trade ?? "–") + " bps"}`, "#5a5a6e");
        break;
      case "open": this.float({ x: a.home.x, y: a.home.y - 90 }, `OPEN ${p.side} ${p.size}${p.liquidity === "maker" ? " (maker)" : ""}`, "#1d1d1f"); break;
      case "order":
        if (p.status === "placed") this.float({ x: a.home.x, y: a.home.y - 90 }, `LIMIT ${String(p.side).toUpperCase()} @ ${p.price}`, "#1a5fb4");
        else if (p.status === "filled") this.float({ x: a.home.x, y: a.home.y - 90 }, `${String(p.liquidity).toUpperCase()} FILL @ ${p.price}`, "#1b7a3d");
        else if (p.status === "rejected") this.float({ x: a.home.x, y: a.home.y - 90 }, "post-only rejected", "#c62828");
        break;
      case "close": this.float({ x: a.home.x, y: a.home.y - 90 }, `${p.pnl_bps >= 0 ? "+" : ""}${p.pnl_bps} bps`, p.pnl_bps >= 0 ? "#1b7a3d" : "#c62828"); break;
      case "command": {
        const target = this.actors[this.seat(p.employee)];
        a.then(async () => {
          if (target?.place) { await a.walkTo(target.place.visit); a.face(target.pos); }
          await a.say(`New limits for ${this.nameOf(p.employee)}: ${JSON.stringify(p.changes)}${p.reason ? " — " + p.reason : ""}`);
          await a.walkTo(a.home);
        });
        break;
      }
    }
  }

  // ---------- the stand-up and the alarm ----------
  setMeeting(on: boolean, live: boolean) {
    this.meeting = on;
    for (const [seat, a] of Object.entries(this.actors)) {
      if (!a || seat === "boss") continue;
      a.meetingSeat = on ? (MEETING_SEATS[seat] ?? MEETING_SEATS["trader-1"]) : null;
      if (live) a.then(() => a.walkTo(a.home));
      else { a.sprite.setPosition(a.home.x, a.home.y); a.sync(); }
    }
    const boss = this.actors.boss;
    if (!on && boss && this.bossPresent()) {
      boss.meetingSeat = null;
      if (live) boss.then(async () => { await boss.walkTo(DOOR); await boss.fade(0); });
    }
    if (live && on) this.float({ x: 450, y: 440 }, "DAILY STAND-UP", "#1a5fb4");
  }

  soundAlarm(text: string) {
    this.alarmText?.destroy();
    this.alarmText = this.add.text(457, 100, `⚠ ${text}`, TXT(12, "#ffffff", { backgroundColor: "#c62828", padding: { x: 6, y: 3 } }))
      .setOrigin(0.5, 1).setDepth(9_003);
    let n = 0;
    const flash = this.time.addEvent({ delay: 400, repeat: 40, callback: () => {
      n++;
      this.alarm.clear();
      if (n % 2) this.alarm.fillStyle(0xff2020, 0.12).fillRect(0, 0, W, H).fillStyle(0xff3030, 0.9).fillCircle(940, 18, 7);
      if (n >= 40) { this.alarm.clear(); this.alarmText?.destroy(); this.alarmText = undefined; flash.remove(); }
    } });
  }

  // ---------- screens ----------
  drawCode() {
    // a thinking trader's left screen scrolls with code; an idle one shows a blinking cursor
    this.screens.forEach((s) => {
      const owner = Object.values(this.actors).find((a) => a?.place === s.place);
      const x0 = s.place.desk.x - 62 - 15, y0 = s.place.desk.y - 52;
      s.code.clear();
      if (owner?.thinking) {
        for (let i = 0; i < 4; i++) {
          const w = 6 + ((this.tick * 7 + i * 13) % 20);
          s.code.fillStyle(i % 2 ? 0x8ab4f8 : 0x5dff9a, 0.9).fillRect(x0 + 2, y0 + 1 + i * 4, w, 2);
        }
      } else if (this.tick % 2) s.code.fillStyle(0x5dff9a, 0.8).fillRect(x0 + 2, y0 + 1, 3, 3);
    });
  }

  setChart(bars: { c: number }[], price?: number) {
    if (bars.length < 2) return;
    const cs = bars.map((b) => b.c), lo = Math.min(...cs), hi = Math.max(...cs);
    const up = cs[cs.length - 1] >= cs[0];
    this.screens.forEach((s) => {
      const x0 = s.place.desk.x + 62 - 15, y0 = s.place.desk.y - 52, w = 30, h = 15;
      s.chart.clear().lineStyle(1.5, up ? 0x5dff9a : 0xff6b6b, 1).beginPath();
      cs.forEach((c, i) => {
        const x = x0 + (i / (cs.length - 1)) * w, y = y0 + h - ((c - lo) / Math.max(1e-9, hi - lo)) * h;
        i ? s.chart.lineTo(x, y) : s.chart.moveTo(x, y);
      });
      s.chart.strokePath();
      if (price) s.price.setText(price.toFixed(0));
    });
  }

  setBoard(board: any) {
    const rows = board.by_employee.slice(0, 5).map((r: any) =>
      `${String(r.name ?? r.employee).slice(0, 11).padEnd(11)} ${String(r.trades).padStart(3)}t ${String(r.net_pnl ?? 0).padStart(9)} ${r.avg_net_bps == null ? "" : r.avg_net_bps + "bps"}`);
    this.screenText.setText(rows.join("\n") || "no traders");
  }
}
