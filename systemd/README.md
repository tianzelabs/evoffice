# systemd/ — one user unit per process

Planned: `office-server.service`, `office-trader.service`,
`office-manager.service`. User units (`systemctl --user`), like agent-world's.
Nothing here is installed until the phase that needs it.

`office-server.service` is installed (P0): `systemctl --user status office-server`.
It binds the Tailscale address only, port 8710; tokens live in `~/pixel-office/tokens.json` (mode 600, never in the repo).

`office-trader-1.service` (P1): trader-1's container, `docker run` under systemd. Its env file `~/pixel-office/trader-1.env` holds only trader-1's office token -- never the model key, never another employee's token. Objects persist in `~/pixel-office/trader-1-state/`.
