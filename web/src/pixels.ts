// Pixel art drawn from ASCII maps -- no external assets, nothing to license.
// Each map character is a palette key; "." is transparent. Textures are drawn
// at 1x into a canvas and registered with Phaser; sprites are scaled up with
// nearest-neighbour filtering (pixelArt: true), so they stay crisp.
import * as Phaser from "phaser";

export const SCALE = 3;

type Palette = Record<string, string>;

const PERSON = [
  "....HHHH....",
  "...HHHHHH...",
  "...HSSSSH...",
  "...SESSES...",
  "...SSSSSS...",
  "....SMMS....",
  "..CCCTTCCC..",
  ".CCCCTTCCCC.",
  ".SCCCTTCCCS.",
  ".SCCCCCCCCS.",
  "..CCCCCCCC..",
  "..PPPPPPPP..",
  "..PPP..PPP..",
  "..PPP..PPP..",
  "..BBB..BBB..",
  "..BBB..BBB..",
];
// second walking frame: legs apart
const PERSON_STEP = [...PERSON.slice(0, 12), ".PPP....PPP.", ".PPP....PPP.", ".BBB....BBB.", "............"];

export const PEOPLE: Record<string, Palette> = {
  trader:  { H: "#3b2a20", S: "#f1c7a0", E: "#202020", M: "#c47a6a", C: "#2f8f5b", T: "#2f8f5b", P: "#2d3550", B: "#1d1d1d" },
  manager: { H: "#9a9aa5", S: "#e8b98f", E: "#202020", M: "#b06a5a", C: "#2a3e78", T: "#c23b3b", P: "#22283d", B: "#111111" },
  boss:    { H: "#111111", S: "#d9a77c", E: "#202020", M: "#a85c4c", C: "#7a1f1f", T: "#e8c547", P: "#1a1a1a", B: "#0a0a0a" },
};

const MONITOR = [
  "KKKKKKKKKKKK",
  "KGGGGGGGGGGK",
  "KGGGGGGGGGGK",
  "KGGGGGGGGGGK",
  "KGGGGGGGGGGK",
  "KGGGGGGGGGGK",
  "KKKKKKKKKKKK",
  ".....KK.....",
  "...KKKKKK...",
];
const PLANT = [
  "...LL.L.....",
  "..LLLLLL.L..",
  ".LLlLLLlLL..",
  "LLLLlLLLLLL.",
  ".LlLLLLlLLL.",
  "..LLLLLLLL..",
  "....OOOO....",
  "...OOOOOO...",
  "...OOOOOO...",
  "....OOOO....",
];
const COFFEE = [
  "XXXXXXXXXX",
  "XssssssssX",
  "XsRsssssGX",
  "XssssssssX",
  "XXXXXXXXXX",
  "X..XXXX..X",
  "X..XwwX..X",
  "X...ww...X",
  "XXXXXXXXXX",
  "XXXXXXXXXX",
];
const COOLER = [
  "..bbbbbb..",
  ".bBBBBBBb.",
  ".bBBBBBBb.",
  "..bbbbbb..",
  ".XXXXXXXX.",
  ".XssssssX.",
  ".XsRssBsX.",
  ".XssssssX.",
  ".XXXXXXXX.",
  ".XX....XX.",
];
const BULB = ["..YYYY..", ".YYYYYY.", "YYYWYYYY", "YYYYYYYY", ".YYYYYY.", "..YYYY..", "..KKKK..", "..KKKK.."];
const ALERT = ["..RR..", "..RR..", "..RR..", "..RR..", "......", "..RR.."];

function draw(scene: Phaser.Scene, key: string, map: string[], pal: Palette) {
  if (scene.textures.exists(key)) return;
  const c = document.createElement("canvas");
  c.width = map[0].length;
  c.height = map.length;
  const ctx = c.getContext("2d")!;
  map.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === "." || !pal[ch]) return;
    ctx.fillStyle = pal[ch];
    ctx.fillRect(x, y, 1, 1);
  }));
  scene.textures.addCanvas(key, c);
}

export function makeTextures(scene: Phaser.Scene) {
  for (const [role, pal] of Object.entries(PEOPLE)) {
    draw(scene, `${role}-0`, PERSON, pal);
    draw(scene, `${role}-1`, PERSON_STEP, pal);
  }
  draw(scene, "monitor", MONITOR, { K: "#1b1b22", G: "#0f2a1c" });
  draw(scene, "plant", PLANT, { L: "#3f9a4a", l: "#2c6e35", O: "#a0582e" });
  draw(scene, "coffee", COFFEE, { X: "#4a4a52", s: "#77777f", R: "#d94040", G: "#40d970", w: "#f5f5f5" });
  draw(scene, "cooler", COOLER, { b: "#9fd3f5", B: "#5ab0e8", X: "#d8d8de", s: "#bdbdc6", R: "#d94040" });
  draw(scene, "bulb", BULB, { Y: "#ffd84a", W: "#ffffff", K: "#666666" });
  draw(scene, "alert", ALERT, { R: "#ff4d4d" });
}
