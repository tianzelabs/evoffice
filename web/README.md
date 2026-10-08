# web/ — the pixel office

Vite + TypeScript + Phaser 4, map drawn in Tiled, Kenney art (CC0). **A renderer of the event
stream, nothing more**: it holds no state the server does not have, and the
office looks the way it does because of events, never the other way round.

## Planned contents

| path | owns |
|---|---|
| `index.html`, `src/main.ts` | boot |
| `src/scenes/Office.ts` | the room: manager's glass office, trader's desk, wall screen = leaderboard |
| `src/net.ts` | SSE subscription + HTTP for the boss's chat input |
| `src/actors.ts` | event -> animation (thinking = typing, say = speech bubble, holding = watching the chart, idle = roaming) |
| `src/chat.ts` | the chat panel; the boss's input box |
| `assets/` | tiles and sprites (Kenney packs, CC0), the Tiled map JSON |

## Note

The server has no Node.js. Build on the Mac (`npm install && npm run build`) or
install Node on the server when the frontend phase starts; the server serves
`web/dist/` as static files either way.
