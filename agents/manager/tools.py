"""The manager's tools as LangChain tools (the `langchain` backend). Logic lives in ops.py."""
from __future__ import annotations

from langchain.tools import tool

from agents.common.office_client import Office
from agents.manager import ops


def make_tools(office: Office):
    @tool
    def say(text: str, to: str | None = None) -> str:
        """Speak in the office's public chat. `to` names who it is addressed to (e.g. 'trader-1', 'boss'), or None for everyone."""
        return ops.say(office, text, to)

    @tool
    def read_recent_chat(n: int = 30) -> str:
        """The last n chat messages, oldest first."""
        return ops.read_recent_chat(office, n)

    @tool
    def leaderboard() -> str:
        """Standings per trader and per strategy version (net of fees)."""
        return ops.leaderboard(office)

    @tool
    def employees() -> str:
        """Everyone employed or fired, with each trader's current parameters."""
        return ops.employees(office)

    @tool
    def trader_activity(trader: str, n: int = 10) -> str:
        """A trader's recent turns (with its own summaries), strategy versions, held-out evaluations, and what woke it in the last 24 h."""
        return ops.trader_activity(office, trader, n)

    @tool
    def trader_positions(trader: str) -> str:
        """A trader's positions, newest first (open ones have no closed_ts)."""
        return ops.trader_positions(office, trader)

    @tool
    def set_trader_params(trader: str, reason: str, heartbeat_min: int | None = None,
                          max_size: float | None = None, max_hold_min: int | None = None) -> str:
        """Change a trader's parameters: heartbeat_min (5-720), max_size in BTC (0.001-0.05), max_hold_min (1-1440). Give the reason; it is shown in the chat."""
        return ops.set_trader_params(office, trader, reason, heartbeat_min, max_size, max_hold_min)

    @tool
    def fire_trader(trader: str, reason: str) -> str:
        """Fire a trader. Its record stays; a new hire with an empty mind takes the seat. Use rarely, and say why."""
        return ops.fire_trader(office, trader, reason)

    @tool
    def save_notes(text: str) -> str:
        """Replace your private notes for your next wake-up (a few lines: what you are watching, what you asked for)."""
        return ops.save_notes(text)

    return [say, read_recent_chat, leaderboard, employees, trader_activity, trader_positions,
            set_trader_params, fire_trader, save_notes]
