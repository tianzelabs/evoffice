import * as Phaser from "phaser";
import type { Place } from "./office";
import { FACILITIES, ROOM, STATION_DEPTH, type FacilitySpec } from "./room-layout";

type ScreenRef = { chart: Phaser.GameObjects.Graphics; code: Phaser.GameObjects.Graphics; price: Phaser.GameObjects.Text; place: Place };
export type RoomRefs = {
  screenText: Phaser.GameObjects.Text;
  whiteboard: Phaser.GameObjects.Text;
  clock: Phaser.GameObjects.Text;
  night: Phaser.GameObjects.Graphics;
  alarm: Phaser.GameObjects.Graphics;
  lamps: Phaser.GameObjects.Ellipse[];
  screens: ScreenRef[];
  plates: Record<string, Phaser.GameObjects.Text>;
  bars: Record<string, Phaser.GameObjects.Graphics>;
};

export class RoomRenderer {
  constructor(private scene: Phaser.Scene) {}

  draw(traderPlaces: Place[], managerPlace: Place): RoomRefs {
    const layers = {
      back: this.scene.add.graphics().setDepth(-1000),
      architecture: this.scene.add.graphics().setDepth(-900),
      furniture: this.scene.add.graphics().setDepth(200),
      foreground: this.scene.add.graphics().setDepth(600),
    };
    this.drawBackWall(layers.back, layers.architecture);
    this.drawDataWall(layers.architecture);
    this.drawGlassOffice(layers.architecture, layers.furniture);
    this.drawFloor(layers.back);
    this.drawWindowWall(layers.architecture);
    this.drawCommonTable(layers.furniture);
    this.drawBookshelves(layers.furniture);
    this.drawPlants(layers.foreground);
    this.drawLamps(layers.foreground);

    const screenText = this.scene.add.text(318, 92, "", this.txt(12, "#b4f5e5", { lineSpacing: 3 })).setDepth(640);
    this.scene.add.text(318, 70, "COLLECTIVE BOARD", this.txt(12, "#54e1db")).setDepth(640);
    const whiteboard = this.scene.add.text(780, 92, "", this.txt(10, "#e6f3ef", { wordWrap: { width: 150, useAdvancedWrap: true }, lineSpacing: 1, maxLines: 7 })).setDepth(640);
    this.scene.add.text(780, 70, "MANAGER SAYS", this.txt(10, "#f4ae55")).setDepth(640);
    const clock = this.scene.add.text(912, 24, "", this.txt(15, "#f4ae55")).setOrigin(0.5).setDepth(640);
    const screens: ScreenRef[] = [];
    const plates: Record<string, Phaser.GameObjects.Text> = {};
    const bars: Record<string, Phaser.GameObjects.Graphics> = {};
    const lamps: Phaser.GameObjects.Ellipse[] = [];
    for (const p of [...traderPlaces, managerPlace]) {
      const station = this.drawStation(p, screens, plates, bars);
      lamps.push(station.lamp);
    }
    this.drawResearchStudio(layers.furniture);
    const night = this.scene.add.graphics().setDepth(9_000);
    const alarm = this.scene.add.graphics().setDepth(9_002);
    return { screenText, whiteboard, clock, night, alarm, lamps, screens, plates, bars };
  }

  installInteractions(onSelect: (facility: FacilitySpec) => void, onHover: (facility?: FacilitySpec, alpha?: number) => void) {
    for (const facility of FACILITIES) {
      const { x, y, w, h } = facility.rect;
      this.scene.add.zone(x + w / 2, y + h / 2, w, h).setSize(w, h).setInteractive({ useHandCursor: true })
        .on("pointerover", () => onHover(facility, 0.10))
        .on("pointerout", () => onHover(undefined, 0))
        .on("pointerdown", () => onSelect(facility));
    }
  }

  private txt(size: number, color: string, extra: object = {}) {
    return { resolution: 3, fontFamily: "monospace", fontSize: `${size}px`, color, ...extra };
  }

  private drawBackWall(back: Phaser.GameObjects.Graphics, arch: Phaser.GameObjects.Graphics) {
    back.fillStyle(0x152b40).fillRect(0, 0, ROOM.width, 270);
    back.fillStyle(0x263f51).fillRect(0, 226, ROOM.width, 44);
    back.fillStyle(0x0a1723).fillRect(0, 262, ROOM.width, 9);
    arch.fillStyle(0x3a271e).fillRect(0, 270, ROOM.width, 10);
    arch.lineStyle(4, 0x07121d, 0.95).lineBetween(0, 268, ROOM.width, 268);
  }

  private drawFloor(back: Phaser.GameObjects.Graphics) {
    back.fillStyle(0x8f6043).fillRect(0, 280, ROOM.width, ROOM.height - 280);
    for (let y = 290; y < ROOM.height; y += 24) {
      back.lineStyle(2, y % 48 ? 0x674534 : 0xb17a4e, 0.82).lineBetween(0, y, ROOM.width, y);
      for (let x = -80 + (y % 72); x < ROOM.width; x += 150) back.lineStyle(2, 0x674534, 0.42).lineBetween(x, y, x + 72, y + 24);
    }
    back.fillStyle(0x244b51, 0.55).fillPoints([{ x: 275, y: 340 }, { x: 700, y: 340 }, { x: 755, y: 520 }, { x: 215, y: 520 }] as any, true);
  }

  private drawWindowWall(arch: Phaser.GameObjects.Graphics) {
    arch.fillStyle(0x244d70).fillRect(14, 12, 218, 208);
    arch.fillStyle(0x183858).fillRect(20, 18, 206, 196);
    arch.fillStyle(0x0d2037).fillRect(20, 152, 206, 62);
    for (const [x, y, w, h] of [[28, 104, 36, 48], [78, 78, 28, 74], [122, 120, 48, 32], [180, 92, 32, 60]]) arch.fillRect(x, y, w, h);
    arch.fillStyle(0xffd17f, 0.8);
    for (const [x, y] of [[34, 166], [58, 178], [94, 166], [140, 180], [188, 166]]) arch.fillRect(x, y, 3, 3);
    arch.lineStyle(7, 0x8a6042, 1).strokeRect(14, 12, 218, 208);
    arch.lineBetween(122, 12, 122, 220); arch.lineBetween(14, 116, 232, 116);
    arch.fillStyle(0x8a6042).fillRect(8, 218, 230, 10);
  }

  private drawDataWall(arch: Phaser.GameObjects.Graphics) {
    arch.fillStyle(0x1a2b39).fillRoundedRect(270, 30, 470, 220, 8);
    arch.fillStyle(0x071a20).fillRect(282, 45, 446, 194);
    arch.lineStyle(3, 0x54e1db, 0.8).strokeRoundedRect(270, 30, 470, 220, 8);
    arch.lineStyle(1, 0x2c7682, 0.8);
    for (const x of [300, 440, 575, 680]) arch.lineBetween(x, 55, x, 225);
    for (const y of [95, 142, 189]) arch.lineBetween(288, y, 720, y);
    arch.fillStyle(0x54e1db, 0.8).fillCircle(380, 130, 7).fillCircle(444, 100, 5).fillCircle(520, 155, 6);
    arch.lineStyle(2, 0x54e1db, 0.8).lineBetween(380, 130, 444, 100).lineBetween(444, 100, 520, 155);
    arch.fillStyle(0xf4ae55, 0.9).fillCircle(418, 170, 6).fillCircle(565, 108, 5);
    for (let i = 0; i < 7; i++) {
      arch.fillStyle(i % 2 ? 0x54e1db : 0xf4ae55, 0.9).fillRect(600, 66 + i * 20, 82 - (i % 3) * 14, 5);
      arch.fillStyle(0x54e1db, 0.35).fillRect(300, 72 + i * 20, 42 + (i % 4) * 13, 4);
    }
  }

  private drawGlassOffice(arch: Phaser.GameObjects.Graphics, furniture: Phaser.GameObjects.Graphics) {
    furniture.fillStyle(0x0b2230, 0.45).fillRect(750, 28, 204, 340);
    arch.lineStyle(4, 0x54e1db, 0.75).strokeRect(750, 28, 204, 340);
    arch.lineBetween(750, 180, 954, 180); arch.lineBetween(850, 28, 850, 368);
    furniture.fillStyle(0x533923).fillRect(790, 300, 120, 34);
    furniture.fillStyle(0x0d1f2a).fillRect(802, 272, 42, 28).fillRect(858, 272, 42, 28);
  }

  private drawCommonTable(furniture: Phaser.GameObjects.Graphics) {
    furniture.fillStyle(0x3f281d, 0.55).fillEllipse(485, 437, 430, 74);
    furniture.fillStyle(0x71472d).fillPoints([{ x: 320, y: 375 }, { x: 670, y: 375 }, { x: 700, y: 470 }, { x: 290, y: 470 }] as any, true);
    furniture.lineStyle(3, 0xc0834d, 0.9).strokePoints([{ x: 320, y: 375 }, { x: 670, y: 375 }, { x: 700, y: 470 }, { x: 290, y: 470 }] as any, true);
    furniture.fillStyle(0x102b38).fillRect(450, 390, 74, 36);
    furniture.lineStyle(2, 0x54e1db, 0.8).strokeRect(450, 390, 74, 36);
    for (const x of [320, 430, 540, 650]) furniture.fillStyle(0x17232d).fillRoundedRect(x, 462, 48, 34, 4);
  }

  private drawBookshelves(furniture: Phaser.GameObjects.Graphics) {
    for (const [x, y, h] of [[238, 300, 150], [725, 285, 130], [920, 395, 150]]) {
      furniture.fillStyle(0x4a2d20).fillRect(x, y, 30, h);
      for (let row = y + 12; row < y + h - 10; row += 28) {
        furniture.fillStyle(0x8d5a34).fillRect(x - 4, row, 38, 4);
        for (let i = 0; i < 5; i++) furniture.fillStyle([0x54a6a0, 0xd08b4b, 0x7b8fc5, 0xa65d4d][i % 4]).fillRect(x + 2 + i * 6, row - 12, 4, 12);
      }
    }
  }

  private drawPlants(furniture: Phaser.GameObjects.Graphics) {
    for (const [x, y, s] of [[250, 310, 1], [720, 340, 1.2], [80, 325, 1.4], [900, 420, 1]]) {
      furniture.fillStyle(0x9b5d31).fillRect(x - 8 * s, y, 16 * s, 18 * s);
      furniture.fillStyle(0x2c7044).fillCircle(x, y - 15 * s, 18 * s).fillCircle(x - 14 * s, y - 8 * s, 11 * s).fillCircle(x + 13 * s, y - 7 * s, 12 * s);
      furniture.fillStyle(0x4ca567).fillCircle(x - 4 * s, y - 20 * s, 7 * s).fillCircle(x + 8 * s, y - 14 * s, 6 * s);
    }
  }

  private drawLamps(foreground: Phaser.GameObjects.Graphics) {
    for (const x of [320, 470, 620]) {
      foreground.lineStyle(2, 0x0b1722, 0.95).lineBetween(x, 0, x, 24);
      foreground.fillStyle(0xf4ae55, 0.95).fillRoundedRect(x - 8, 24, 16, 18, 3);
      foreground.fillStyle(0xffd27a, 0.16).fillCircle(x, 49, 32);
    }
  }

  private drawResearchStudio(furniture: Phaser.GameObjects.Graphics) {
    furniture.fillStyle(0x583825).fillRect(780, 455, 160, 42);
    furniture.fillStyle(0x0d1e2a).fillRect(810, 420, 42, 30).fillRect(860, 420, 42, 30);
    furniture.fillStyle(0x9b5d31).fillRect(800, 498, 9, 38).fillRect(910, 498, 9, 38);
  }

  private drawStation(p: Place, screens: ScreenRef[], plates: Record<string, Phaser.GameObjects.Text>, bars: Record<string, Phaser.GameObjects.Graphics>) {
    const { x, y } = p.desk;
    const g = this.scene.add.graphics().setDepth(STATION_DEPTH(p));
    g.fillStyle(0x3f281d, 0.6).fillEllipse(x, y + 12, 210, 24);
    g.fillStyle(0x633e29).fillPoints([{ x: x - 105, y: y - 16 }, { x: x + 105, y: y - 16 }, { x: x + 86, y: y + 13 }, { x: x - 86, y: y + 13 }] as any, true);
    g.lineStyle(2, 0xb17a4e, 0.9).strokePoints([{ x: x - 105, y: y - 16 }, { x: x + 105, y: y - 16 }, { x: x + 86, y: y + 13 }, { x: x - 86, y: y + 13 }] as any, true);
    const screen = this.scene.add.graphics().setDepth(STATION_DEPTH(p) + 8);
    screen.fillStyle(0x071a20).fillRoundedRect(x - 64, y - 68, 52, 30, 3).fillRoundedRect(x + 12, y - 68, 52, 30, 3);
    screen.lineStyle(1, 0x54e1db, 0.9).strokeRoundedRect(x - 64, y - 68, 52, 30, 3).strokeRoundedRect(x + 12, y - 68, 52, 30, 3);
    const code = this.scene.add.graphics().setDepth(STATION_DEPTH(p) + 9);
    const chart = this.scene.add.graphics().setDepth(STATION_DEPTH(p) + 9);
    const price = this.scene.add.text(x + 38, y - 76, "", this.txt(8, "#7ee2a1")).setOrigin(0.5).setDepth(STATION_DEPTH(p) + 10);
    if (p.plate !== "MANAGER") screens.push({ chart, code, price, place: p });
    plates[p.plate] = this.scene.add.text(x, y + 23, p.plate, this.txt(9, "#d7fff5", { backgroundColor: "#173846", padding: { x: 5, y: 2 } })).setOrigin(0.5, 1).setDepth(STATION_DEPTH(p) + 12);
    bars[p.plate] = this.scene.add.graphics().setDepth(STATION_DEPTH(p) + 12);
    return { lamp: this.scene.add.ellipse(x - 82, y - 54, 140, 70, 0xffd27a, 0).setDepth(9_001) };
  }
}
