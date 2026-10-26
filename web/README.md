# EvOffice web

This is the modern PixiJS frontend for EvOffice. It is a hobby research
project and a client for the FastAPI office server.

```bash
npm install
npm run dev
```

The Vite proxy targets `http://100.86.90.65:8710` by default. Override it for
local work with `OFFICE_URL=http://127.0.0.1:8710 npm run dev`.

The room is reconstructed from the EvOffice cover composition as interactive
2.5D scene objects. The PNG is not used as the room background.
