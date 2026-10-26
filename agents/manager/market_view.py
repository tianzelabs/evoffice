"""Observed multi-hour market context, computed without a model or trade signal."""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")
HORIZONS_H = (1, 4, 8, 24)
LOOKBACK_MIN = 24 * 60 + 2  # include the close anchoring a full 24-hour change


def market_view(bars: list[dict], now: datetime | None = None) -> dict:
    """Use completed candles only; expose gaps and the actual endpoint spacing.

    Returns are price changes, not conditional forecasts or executable PnL.
    Rebounds/drawdowns use ordered minute closes, never unknown OHLC ordering.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rows = []
    for bar in bars:
        at = datetime.fromisoformat(bar["m"])
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
        if at + timedelta(minutes=1) > now:
            continue
        close = float(bar["c"])
        if not 0 < close < float("inf"):
            raise ValueError("invalid close")
        rows.append((at, close))
    rows.sort()
    times = [r[0] for r in rows]
    if len(set(times)) != len(times):
        raise ValueError("duplicate minute candles")
    result = {"schema_version": 1, "instrument": "PF_XBTUSD",
              "as_of_utc": now.astimezone(timezone.utc).isoformat(),
              "timezone": str(TZ), "kind": "observed context, not a forecast or a trading signal"}
    if not rows:
        return {**result, "available": False, "reason": "no completed candles"}

    def observed_at(at):
        return (at + timedelta(minutes=1)).astimezone(TZ).isoformat()

    end, latest = rows[-1]
    age = max(0, (now - end - timedelta(minutes=1)).total_seconds())
    result.update({"available": True, "latest_close": latest, "latest_close_available_at": observed_at(end),
                   "latest_close_age_s": round(age, 1), "stale": age >= 120, "horizons": {}})
    for hours in HORIZONS_H:
        target = end - timedelta(hours=hours)
        index = bisect_right(times, target) - 1
        if index < 0:
            result["horizons"][str(hours)] = {"available": False, "reason": "insufficient history"}
            continue
        start, first = rows[index]
        window = rows[index:]
        actual_min = int((end - start).total_seconds() // 60)
        missing = actual_min + 1 - len(window)
        low = high = first
        rebound = drawdown = 0.0
        for _, close in window:
            low, high = min(low, close), max(high, close)
            rebound = max(rebound, close / low - 1)
            drawdown = max(drawdown, 1 - close / high)
        result["horizons"][str(hours)] = {
            "available": True, "from_close_available_at": observed_at(start),
            "start_close": first, "actual_minutes": actual_min,
            "anchor_gap_minutes": int((target - start).total_seconds() // 60),
            "observed_closes": len(window), "missing_minutes": missing,
            "continuous": missing == 0, "change_bps": round((latest / first - 1) * 1e4, 2),
            "min_close": min(x[1] for x in window), "max_close": max(x[1] for x in window),
            "largest_close_rebound_bps": round(rebound * 1e4, 2),
            "largest_close_drawdown_bps": round(drawdown * 1e4, 2),
        }
    return result


def report_changes(view: dict, previous: dict | None) -> None:
    """Compare observations; rolling-window deltas are not forecast revisions."""
    if not view.get("available") or not previous or not previous.get("available"):
        return
    if not isinstance(previous.get("horizons"), dict) or not isinstance(previous.get("latest_close"), (int,float)):
        return
    if previous["latest_close"] <= 0 or not previous.get("latest_close_available_at"):
        return
    view["since_previous_report"] = {
        "previous_close_available_at": previous["latest_close_available_at"],
        "price_change_bps": round((view["latest_close"] / previous["latest_close"] - 1) * 1e4, 2),
        "rolling_change_delta_bps": {
            h: round(v["change_bps"] - previous["horizons"][h]["change_bps"], 2)
            for h, v in view["horizons"].items()
            if v.get("available") and isinstance(previous["horizons"].get(h),dict)
            and previous["horizons"][h].get("available")
            and isinstance(previous["horizons"][h].get("change_bps"),(int,float))},
    }


def render_report(view: dict) -> str:
    lines = ["MULTI-HOUR MARKET REPORT — observed context, not a forecast", ""]
    if not view.get("available"):
        return "\n".join(lines + ["UNAVAILABLE: " + view.get("reason", "unknown")])
    lines += [f"PF_XBTUSD | {view['latest_close']:,.2f} | close available {view['latest_close_available_at']}",
              f"Europe/Budapest | data age {view['latest_close_age_s']}s | stale: {view['stale']}", "",
              "| Horizon | Change bps | Close range | Largest rebound bps | Largest drawdown bps | Missing min | Anchor lag min |",
              "|---|---:|---|---:|---:|---:|---:|"]
    for h, row in view["horizons"].items():
        if not row.get("available"):
            lines.append(f"| {h}h | unavailable: {row['reason']} | — | — | — | — | — |")
        else:
            lines.append(f"| {h}h | {row['change_bps']:+.2f} | {row['min_close']:,.0f}–{row['max_close']:,.0f} | "
                         f"{row['largest_close_rebound_bps']:.2f} | {row['largest_close_drawdown_bps']:.2f} | "
                         f"{row['missing_minutes']} | {row['anchor_gap_minutes']} |")
    changes = view.get("since_previous_report")
    if changes:
        lines += ["", f"Since prior observed close ({changes['previous_close_available_at']}): "
                  f"price {changes['price_change_bps']:+.2f} bps; rolling-change deltas bps "
                  + json.dumps(changes["rolling_change_delta_bps"]) + ". These are observation changes, not forecast changes."]
    lines += ["", "Ranges/reversals use observed minute closes; gaps may hide extremes. "
              "Changes are before trading costs. Compare with the existing plan, risk and invalidation; "
              "a short rebound alone does not establish a trend reversal."]
    return "\n".join(lines)


def save_report(view: dict, state_dir: Path) -> None:
    """Keep a latest structured model/readable report and append-only observations."""
    import os
    import tempfile
    state_dir.mkdir(parents=True, exist_ok=True)
    for name, content in [("market-report.json", json.dumps(view, ensure_ascii=False, indent=2)),
                          ("market-report.md", render_report(view))]:
        with tempfile.NamedTemporaryFile("w", dir=state_dir, encoding="utf-8", delete=False) as handle:
            handle.write(content + "\n")
            temporary = handle.name
        os.replace(temporary, state_dir / name)
    with (state_dir / "market-report-history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(view, ensure_ascii=False) + "\n")


def market_briefing(office, state_dir: Path | None = None, now: datetime | None = None) -> str:
    """Code reads raw data; the manager receives only the report. No model calls.

    Reuse a report for up to 60 seconds. A missing feed/cache must not prevent
    handling other events, and an old report is never silently presented as fresh.
    """
    now = now or datetime.now(timezone.utc)
    previous = None
    cache_error = None
    if state_dir is not None:
        try:
            previous = json.loads((state_dir / "market-report.json").read_text())
            age = (now - datetime.fromisoformat(previous["as_of_utc"])).total_seconds()
            if previous.get("available") and 0 <= age < 60:
                data_age = (now - datetime.fromisoformat(previous["latest_close_available_at"])).total_seconds()
                previous["latest_close_age_s"] = round(max(0, data_age), 1)
                previous["stale"] = data_age >= 120
                return render_report(previous) + "\n[Cached report; at most 60 seconds old.]"
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as error:
            previous = None
            cache_error = f"Report cache ignored: {type(error).__name__}"
    try:
        view = market_view(office.bars(LOOKBACK_MIN), now)
    except Exception as error:
        view = {"schema_version": 1, "as_of_utc": now.isoformat(),
                "available": False, "reason": f"{type(error).__name__}: {str(error)[:180]}"}
    report_changes(view, previous)
    if state_dir is not None:
        try:
            save_report(view, state_dir)
        except OSError as error:
            cache_error = f"Report persistence failed: {type(error).__name__}"
    return render_report(view) + (("\n" + cache_error) if cache_error else "")
