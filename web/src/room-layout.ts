import type { Place } from "./office";

export type Rect = { x: number; y: number; w: number; h: number };
export type FacilitySpec = { id: string; name: string; rect: Rect; detail: string };

export const ROOM = { width: 960, height: 600 };

// Coordinates are authored in the cover's composition: the back wall occupies
// the upper third, the floor opens toward the viewer, and the commons table is
// the visual centre of gravity.
export const FACILITIES: FacilitySpec[] = [
  { id: "windows", name: "OBSERVATORY WINDOWS", rect: { x: 0, y: 0, w: 230, h: 350 }, detail: "City view and the office's research horizon." },
  { id: "data-wall", name: "CENTRAL DATA WALL", rect: { x: 265, y: 36, w: 470, h: 210 }, detail: "Collective board, live signals and shared research state." },
  { id: "manager-office", name: "MANAGER GLASS OFFICE", rect: { x: 744, y: 30, w: 216, h: 350 }, detail: "Manager station, whiteboard and command point." },
  { id: "commons", name: "COMMONS TABLE", rect: { x: 295, y: 330, w: 390, h: 175 }, detail: "Shared table for stand-ups and collective decisions." },
  { id: "trader-1", name: "TRADER 1 WORKSTATION", rect: { x: 18, y: 370, w: 285, h: 190 }, detail: "Strategy terminal, code, chart, budget and XP." },
  { id: "trader-2", name: "TRADER 2 WORKSTATION", rect: { x: 322, y: 380, w: 285, h: 180 }, detail: "Strategy terminal, code, chart, budget and XP." },
  { id: "research-studio", name: "RESEARCH STUDIO", rect: { x: 745, y: 365, w: 215, h: 195 }, detail: "Books, notes and the secondary research surface." },
];

export const STATION_DEPTH = (p: Place) => p.desk.y + 20;
