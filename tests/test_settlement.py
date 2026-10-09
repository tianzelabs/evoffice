import pytest

from server import settlement


def test_a_favourable_move_can_still_LOSE():
    """The load-bearing test. 0.05 BTC long, price up 20 points at 80,000: gross
    +1.0, fees ~3.2. If this ever reports a win, the fee model is broken."""
    r = settlement.settle("long", 0.05, 80_000.0, 80_020.0)
    assert r.gross == pytest.approx(1.0)
    assert r.fees == pytest.approx(0.0004 * 0.05 * (80_000 + 80_020))
    assert r.pnl < 0


def test_a_move_that_clears_the_fee_wins():
    assert settlement.settle("long", 0.05, 80_000.0, 80_200.0).pnl > 0


def test_a_short_is_scored_in_its_own_direction():
    assert settlement.settle("short", 0.05, 80_000.0, 79_800.0).pnl > 0
    assert settlement.settle("short", 0.05, 80_000.0, 80_200.0).pnl < 0


def test_both_legs_pay():
    r = settlement.settle("long", 1.0, 100.0, 100.0)
    assert r.pnl == pytest.approx(-0.0004 * 200.0)


def test_breakeven_move_really_breaks_even_and_ignores_size():
    m = settlement.breakeven_move(80_000.0)
    for size in (0.001, 0.05, 3.0):
        assert settlement.settle("long", size, 80_000.0, 80_000.0 + m).pnl == pytest.approx(0.0, abs=1e-9)
    assert m == pytest.approx(64.0, rel=0.01)   # ~0.0008 x price


def test_nonsense_is_refused():
    with pytest.raises(ValueError):
        settlement.settle("sideways", 1, 100, 100)
    with pytest.raises(ValueError):
        settlement.settle("long", 0, 100, 100)
