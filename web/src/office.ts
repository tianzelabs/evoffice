// The room. It renders the office's event stream and nothing else: the office
// looks the way it does because of events, never the other way round.
//
//   agent_state thinking -> walks to its desk, "..." over its head
//   agent_state idle     -> wanders (coffee, window, water cooler, plants)
//   say                  -> speech bubble; the boss walks in through the door to speak
//   wake / version / evaluation / open / close / command / fire -> small effects
import * as Phaser from "phaser";
import { makeTextures, SCALE } from "./pixels";
import type { OfficeEvent } from "./net";

export const W = 960, H = 600;
type Pt = { x: number; y: number };

const SPOTS: Record<string, Pt> = {
  traderDesk: { x: 210, y: 372 }, managerDesk: { x: 835, y: 300 }, door: { x: 480, y: 585 },
  bossStand: { x: 480, y: 470 }, coffee: { x: 470, y: 200 }, cooler: { x: 620, y: 200 },
  window: { x: 140, y: 175 }, plant: { x: 70, y: 210 }, sofa: { x: 330, y: 500 },
  managerWindow: { x: 760, y: 200 }, managerSide: { x: 900, y: 360 }, traderVisit: { x: 330, y: 372 },
};
const ROAM: Record<string, string[]> = {
  trader: ["coffee", "cooler", "window", "plant", "sofa", "traderDesk", "traderDesk"],
  manager: ["managerDesk", "managerWindow", "managerSide", "managerDesk", "coffee"],
};

class Actor {
  sprite: Phaser.GameObjects.Image;
  label: Phaser.GameObjects.Text;
  bubble?: Phaser.GameObjects.Container;
  dots?: Phaser.GameObjects.Text;
  walking = false;
  thinking = false;
  frame = 0;
  tween?: Phaser.Tweens.Tween;

  constructor(private scene: OfficeScene, public role: string, public name: string, at: Pt) {
    this.sprite = scene.add.image(at.x, at.y, `${role}-0`).setScale(SCALE).setOrigin(0.5, 1);
    this.label = scene.add.text(at.x, at.y + 4, name, { resolution: 3, fontFamily: "monospace", fontSize: "12px", color: "#1d1d1f",
      backgroundColor: "#ffffffcc", padding: { x: 3, y: 1 } }).setOrigin(0.5, 0);
    this.sync();
  }

  get pos(): Pt { return { x: this.sprite.x, y: this.sprite.y }; }

  sync() {
    const { x, y } = this.sprite;
    this.label.setPosition(x, y + 4).setDepth(y + 1);
    this.sprite.setDepth(y);
    this.bubble?.setPosition(x, y - 16 * SCALE - 8).setDepth(10_000);
    this.dots?.setPosition(x, y - 16 * SCALE - 6).setDepth(10_000);
  }

  walkTo(p: Pt, then?: () => void) {
    this.tween?.stop();
    const d = Phaser.Math.Distance.Between(this.sprite.x, this.sprite.y, p.x, p.y);
    if (d < 4) { then?.(); return; }
    this.sprite.setFlipX(p.x < this.sprite.x);
    this.walking = true;
    this.tween = this.scene.tweens.add({
      targets: this.sprite, x: p.x, y: p.y, duration: (d / 110) * 1000, ease: "Linear",
      onUpdate: () => this.sync(),
      onComplete: () => { this.walking = false; this.sprite.setTexture(`${this.role}-0`); this.sync(); then?.(); },
    });
  }

  step() {
    if (!this.walking) return;
    this.frame ^= 1;
    this.sprite.setTexture(`${this.role}-${this.frame}`);
  }

  say(text: string) {
    this.bubble?.destroy();
    const t = text.length > 220 ? text.slice(0, 217) + "…" : text;
    const body = this.scene.add.text(0, 0, t, { resolution: 3, fontFamily: "monospace", fontSize: "13px", color: "#111",
      wordWrap: { width: 230, useAdvancedWrap: true } }).setOrigin(0.5, 1);
    const bw = body.width + 16, bh = body.height + 12;
    const g = this.scene.add.graphics();
    g.fillStyle(0xffffff, 0.97).fillRoundedRect(-bw / 2, -bh - 6, bw, bh, 6);
    g.lineStyle(2, 0x1d1d1f, 1).strokeRoundedRect(-bw / 2, -bh - 6, bw, bh, 6);
    g.fillStyle(0xffffff, 1).fillTriangle(-6, -7, 6, -7, 0, 2);
    body.setPosition(0, -12);
    this.bubble = this.scene.add.container(0, 0, [g, body]);
    this.sync();
    const ms = Math.min(14_000, 3500 + t.length * 45);
    this.scene.time.delayedCall(ms, () => { this.bubble?.destroy(); this.bubble = undefined; });
  }

  setThinking(on: boolean) {
    this.thinking = on;
    if (on && !this.dots) {
      this.dots = this.scene.add.text(0, 0, "", { resolution: 3, fontFamily: "monospace", fontSize: "18px", color: "#1d1d1f",
        backgroundColor: "#ffffffdd", padding: { x: 4, y: 0 } }).setOrigin(0.5, 1);
      this.sync();
    } else if (!on) {
      this.dots?.destroy(); this.dots = undefined;
    }
  }

  tickDots(n: number) { this.dots?.setText(".".repeat((n % 3) + 1).padEnd(3, " ")); }

  rename(name: string) { this.name = name; this.label.setText(name); }

  fadeOut(then: () => void) {
    this.scene.tweens.add({ targets: [this.sprite, this.label], alpha: 0, duration: 600, onComplete: then });
  }
}

export class OfficeScene extends Phaser.Scene {
  actors: Record<string, Actor> = {};      // keyed by seat: "trader-1", "manager", "boss"
  seatOf: Record<string, string> = {};     // employee id -> seat
  screenText!: Phaser.GameObjects.Text;
  priceText!: Phaser.GameObjects.Text;
  chart!: Phaser.GameObjects.Graphics;
  sky!: Phaser.GameObjects.Graphics;
  clock!: Phaser.GameObjects.Text;
  tick = 0;
  ready!: Promise<void>;
  private resolveReady!: () => void;

  constructor() {
    super("office");
    this.ready = new Promise((r) => (this.resolveReady = r));
  }

  create() {
    makeTextures(this);
    this.drawRoom();
    this.time.addEvent({ delay: 170, loop: true, callback: () => Object.values(this.actors).forEach((a) => a.step()) });
    this.time.addEvent({ delay: 400, loop: true, callback: () => { this.tick++; Object.values(this.actors).forEach((a) => a.tickDots(this.tick)); } });
    this.time.addEvent({ delay: 7000, loop: true, callback: () => this.wander() });
    this.time.addEvent({ delay: 30_000, loop: true, callback: () => this.paintSky() });
    this.resolveReady();
  }

  // ---------- the room ----------
  drawRoom() {
    const g = this.add.graphics().setDepth(-10);
    g.fillStyle(0xb98a5b).fillRect(0, 120, W, H - 120);                  // floor
    g.lineStyle(2, 0xa47548, 1);
    for (let y = 144; y < H; y += 24) {
      g.lineBetween(0, y, W, y);
      for (let x = (y / 24) % 2 ? 0 : 60; x < W; x += 120) g.lineBetween(x, y - 24, x, y);
    }
    g.fillStyle(0xd9cbb4).fillRect(0, 0, W, 120);                        // wall
    g.fillStyle(0x8f7a5c).fillRect(0, 114, W, 8);                        // baseboard
    this.sky = this.add.graphics().setDepth(-9);
    this.paintSky();
    g.lineStyle(6, 0x5a4632, 1).strokeRect(40, 16, 200, 86);             // window frame
    g.lineBetween(140, 16, 140, 102);
    // the wall screen: the leaderboard
    g.fillStyle(0x222228).fillRect(296, 8, 338, 102);
    g.fillStyle(0x0d1a12).fillRect(304, 14, 322, 90);
    this.add.text(312, 18, "LEADERBOARD", { resolution: 3, fontFamily: "monospace", fontSize: "12px", color: "#5dff9a" }).setDepth(-8);
    this.screenText = this.add.text(312, 36, "", { resolution: 3, fontFamily: "monospace", fontSize: "12px", color: "#a8f0c0", lineSpacing: 3 }).setDepth(-8);
    this.clock = this.add.text(870, 30, "", { resolution: 3, fontFamily: "monospace", fontSize: "16px", color: "#3a2f22" }).setOrigin(0.5).setDepth(-8);
    // the manager's glass office, with a door gap on its left wall
    g.fillStyle(0x9fd3f5, 0.13).fillRect(690, 126, 264, 280);
    g.lineStyle(4, 0x7fb9de, 0.9);
    g.lineBetween(690, 126, 954, 126); g.lineBetween(954, 126, 954, 406); g.lineBetween(690, 406, 954, 406);
    g.lineBetween(690, 126, 690, 290); g.lineBetween(690, 360, 690, 406);
    this.add.text(822, 134, "MANAGER", { resolution: 3, fontFamily: "monospace", fontSize: "11px", color: "#3c6f92" }).setOrigin(0.5, 0).setDepth(-8);
    // desks
    this.desk(g, 120, 300, 180);
    this.desk(g, 760, 232, 150);
    this.add.image(185, 300, "monitor").setScale(SCALE).setOrigin(0.5, 1).setDepth(299);
    this.add.image(250, 300, "monitor").setScale(SCALE).setOrigin(0.5, 1).setDepth(299);
    this.add.image(835, 232, "monitor").setScale(SCALE).setOrigin(0.5, 1).setDepth(231);
    this.chart = this.add.graphics().setDepth(300);
    this.priceText = this.add.text(250, 250, "", { resolution: 3, fontFamily: "monospace", fontSize: "11px", color: "#5dff9a" }).setOrigin(0.5).setDepth(301);
    // the rest of the room
    this.add.image(30, 170, "plant").setScale(SCALE).setOrigin(0.5, 1).setDepth(170);
    this.add.image(930, 470, "plant").setScale(SCALE).setOrigin(0.5, 1).setDepth(470);
    this.add.image(470, 150, "coffee").setScale(SCALE).setOrigin(0.5, 1).setDepth(150);
    this.add.image(620, 150, "cooler").setScale(SCALE).setOrigin(0.5, 1).setDepth(150);
    g.fillStyle(0x6d5a8a).fillRoundedRect(270, 470, 130, 40, 8);         // sofa
    g.fillStyle(0x58486f).fillRoundedRect(270, 456, 130, 20, 8);
    g.fillStyle(0x3a2f22).fillRect(440, 592, 80, 8);                     // the door
  }

  desk(g: Phaser.GameObjects.Graphics, x: number, y: number, w: number) {
    g.fillStyle(0x6b4a2f).fillRect(x, y, w, 40);
    g.fillStyle(0x8a6240).fillRect(x, y - 6, w, 10);
    g.fillStyle(0x4e3622).fillRect(x + 6, y + 40, 8, 20).fillRect(x + w - 14, y + 40, 8, 20);
  }

  paintSky() {
    const h = new Date().getHours();
    const sky = h >= 7 && h < 18 ? 0x8ecdf0 : h >= 18 && h < 21 ? 0xf0a35e : h >= 5 && h < 7 ? 0xf3c38f : 0x14203a;
    this.sky.clear().fillStyle(sky).fillRect(40, 16, 200, 86);
    this.sky.fillStyle(h >= 21 || h < 5 ? 0x0b1222 : 0x6d7f8f);
    [[48, 60, 22, 42], [74, 46, 18, 56], [96, 70, 26, 32], [150, 52, 20, 50], [174, 64, 30, 38], [208, 40, 24, 62]]
      .forEach(([x, y, w, hh]) => this.sky.fillRect(x, y, w, hh));
    if (h >= 21 || h < 5) { this.sky.fillStyle(0xffffff); [[60, 26], [118, 34], [190, 22], [222, 30]].forEach(([x, y]) => this.sky.fillRect(x, y, 2, 2)); }
    this.clock?.setText(new Date().toTimeString().slice(0, 5));
  }

  // ---------- people ----------
  seat(employee: string): string {
    if (this.seatOf[employee]) return this.seatOf[employee];
    const s = employee.startsWith("trader") ? employee.split(".")[0] : employee;
    this.seatOf[employee] = s;
    return s;
  }

  actor(employee: string): Actor | undefined {
    const seat = this.seat(employee);
    if (this.actors[seat]) return this.actors[seat];
    if (seat === "manager") return (this.actors[seat] = new Actor(this, "manager", employee, SPOTS.managerDesk));
    if (seat.startsWith("trader")) return (this.actors[seat] = new Actor(this, "trader", employee, SPOTS.traderDesk));
    if (seat === "boss") {             // the boss is not in the office; it walks in only to speak
      const b = new Actor(this, "boss", "boss", SPOTS.door);
      b.sprite.setAlpha(0); b.label.setAlpha(0);
      return (this.actors[seat] = b);
    }
    return undefined;
  }

  wander() {
    for (const [seat, a] of Object.entries(this.actors)) {
      if (a.thinking || a.walking || seat === "boss" || Math.random() < 0.4) continue;
      const spots = ROAM[a.role] ?? [];
      a.walkTo(SPOTS[spots[Math.floor(Math.random() * spots.length)]]);
    }
  }

  float(at: Pt, text: string, color = "#1d1d1f", icon?: string) {
    const objs: Phaser.GameObjects.GameObject[] = [];
    const t = this.add.text(at.x, at.y, text, { resolution: 3, fontFamily: "monospace", fontSize: "14px", color, fontStyle: "bold",
      backgroundColor: "#ffffffcc", padding: { x: 4, y: 2 } }).setOrigin(0.5, 1).setDepth(10_001);
    objs.push(t);
    if (icon) objs.push(this.add.image(at.x - t.width / 2 - 14, at.y - 10, icon).setScale(SCALE).setDepth(10_001));
    this.tweens.add({ targets: objs, y: `-=40`, alpha: 0, delay: 2200, duration: 1800, onComplete: () => objs.forEach((o) => o.destroy()) });
  }

  head(a: Actor): Pt { return { x: a.pos.x, y: a.pos.y - 16 * SCALE - 30 }; }

  // ---------- events -> the room ----------
  apply(e: OfficeEvent, live: boolean) {
    const p = e.payload;
    if (e.kind === "hire") { this.seat(p.employee); if (p.role !== "boss") this.actor(p.employee); return; }
    if (e.kind === "fire") {
      this.seatOf[p.successor] = this.seat(p.employee);
      const a = this.actor(p.employee);
      if (!a) return;
      if (!live) { a.rename(p.successor); return; }
      a.say(`fired: ${p.reason}`);
      this.float(this.head(a), "FIRED", "#c62828");
      a.walkTo(SPOTS.door, () => a.fadeOut(() => {
        a.rename(p.successor);
        a.sprite.setPosition(SPOTS.door.x, SPOTS.door.y).setAlpha(1); a.label.setAlpha(1); a.sync();
        a.walkTo(SPOTS.traderDesk, () => a.say("Hi, I'm new here."));
      }));
      return;
    }
    if (e.actor === "office") return;
    const a = this.actor(e.actor);
    if (!a) return;
    if (e.kind === "agent_state") {
      if (p.state === "asleep" && live) a.say(`zZz — ${p.why ?? "asleep"}`);
      const on = p.state === "thinking";
      a.setThinking(on);
      if (on && live) a.walkTo(a.role === "manager" ? SPOTS.managerDesk : SPOTS.traderDesk);
      return;
    }
    if (!live) return;                          // replay restores state; only live events animate
    switch (e.kind) {
      case "say":
        if (a.role === "boss") {
          a.sprite.setAlpha(1); a.label.setAlpha(1);
          a.walkTo(SPOTS.bossStand, () => {
            a.say(p.text);
            this.time.delayedCall(16_000, () => a.walkTo(SPOTS.door, () => a.fadeOut(() => {})));
          });
        } else a.say(p.text);
        break;
      case "wake": this.float(this.head(a), "!", "#c62828", "alert"); break;
      case "version": this.float(this.head(a), `new strategy ${String(p.version ?? "").slice(0, 6)}`, "#7a5a00", "bulb"); break;
      case "evaluation":
        this.float(this.head(a), `held-out: ${p.net_bps_per_trade ?? "–"} bps/trade`, (p.net_bps_per_trade ?? -1) > 0 ? "#1b7a3d" : "#c62828");
        break;
      case "open": this.float({ x: 215, y: 250 }, `OPEN ${p.side} ${p.size}`, "#1d1d1f"); break;
      case "close": this.float({ x: 215, y: 250 }, `${p.pnl_bps >= 0 ? "+" : ""}${p.pnl_bps} bps`, p.pnl_bps >= 0 ? "#1b7a3d" : "#c62828"); break;
      case "command": {
        const back = a.pos;
        a.walkTo(SPOTS.traderVisit, () => { a.say(`New limits for ${p.employee}: ${JSON.stringify(p.changes)}`); this.time.delayedCall(6000, () => a.walkTo(back)); });
        break;
      }
    }
  }

  // ---------- the trader's monitor and the wall screen ----------
  setChart(bars: { c: number }[], price?: number) {
    this.chart.clear();
    if (bars.length < 2) return;
    const x0 = 235, y0 = 274, w = 30, h = 15;   // the right-hand monitor's screen, in room pixels
    const cs = bars.map((b) => b.c), lo = Math.min(...cs), hi = Math.max(...cs);
    const up = cs[cs.length - 1] >= cs[0];
    this.chart.lineStyle(1.5, up ? 0x5dff9a : 0xff6b6b, 1);
    this.chart.beginPath();
    cs.forEach((c, i) => {
      const x = x0 + (i / (cs.length - 1)) * w, y = y0 + h - ((c - lo) / Math.max(1e-9, hi - lo)) * h;
      i ? this.chart.lineTo(x, y) : this.chart.moveTo(x, y);
    });
    this.chart.strokePath();
    if (price) this.priceText.setText(price.toFixed(0));
  }

  setBoard(board: any) {
    const rows = board.by_employee.slice(0, 4).map((r: any) =>
      `${r.employee.padEnd(11)} ${String(r.trades).padStart(3)}t ${String(r.net_pnl ?? 0).padStart(9)} ${r.avg_net_bps == null ? "" : r.avg_net_bps + "bps"}`);
    this.screenText.setText(rows.join("\n") || "no traders");
  }
}
