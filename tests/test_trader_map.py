from agents.trader import map as mapmod


def test_only_numbered_history_counts_as_history():
    ns = {"history_0": [], "history_10": [], "history_2": [], "past_turns_before_restart": [], "history_notes": "x"}
    assert mapmod.history_names(ns) == ["history_0", "history_2", "history_10"]
    assert "history_notes" in mapmod.own_objects(ns, set(), set())


def test_render_survives_a_namespace_with_odd_names():
    ns = {"history_0": [], "history_before_restart": [], "bars_1m": [1, 2]}
    out = mapmod.render(ns, {"bars_1m": ("bars", "now", "")}, {"say": "(text)"}, ["heartbeat"], [], None)
    assert "history_0 .. history_0" in out and "bars_1m" in out
