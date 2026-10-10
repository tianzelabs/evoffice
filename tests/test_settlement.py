import pytest

from server import fees, settlement


def test_a_favourable_move_can_still_LOSE():
    """The load-bearing test. 0.05 BTC long, up 20 points at 80,000, taker both ways:
    gross +1.0, fees ~4.0 (0.05% a side). If this ever reports a win, the fee model is broken."""
    r = settlement.settle("long", 0.05, 80_000.0, 80_020.0)
    assert r.gross == pytest.approx(1.0)
    assert r.fees == pytest.approx(0.0005 * 0.05 * (80_000 + 80_020))
    assert r.pnl < 0


def test_kraken_futures_tier1_rates():
    assert (fees.TIER, fees.MAKER, fees.TAKER) == ("1", 0.0002, 0.0005)


def test_maker_legs_cost_less_than_taker_legs():
    taker = settlement.settle("long", 1.0, 100.0, 100.0, "taker", "taker")
    maker = settlement.settle("long", 1.0, 100.0, 100.0, "maker", "maker")
    assert taker.pnl == pytest.approx(-0.10) and maker.pnl == pytest.approx(-0.04)   # 10 bps vs 4 bps


def test_funding_is_part_of_pnl():
    r = settlement.settle("short", 1.0, 100.0, 100.0, "maker", "maker", funding=0.01)
    assert r.pnl == pytest.approx(-0.04 + 0.01)


def test_a_short_is_scored_in_its_own_direction():
    assert settlement.settle("short", 0.05, 80_000.0, 79_800.0).pnl > 0
    assert settlement.settle("short", 0.05, 80_000.0, 80_200.0).pnl < 0


def test_breakeven_move_really_breaks_even_and_ignores_size():
    for liq in (("taker", "taker"), ("maker", "maker"), ("maker", "taker")):
        m = settlement.breakeven_move(80_000.0, *liq)
        for size in (0.001, 0.05, 3.0):
            assert settlement.settle("long", size, 80_000.0, 80_000.0 + m, *liq).pnl == pytest.approx(0.0, abs=1e-9)
    assert settlement.breakeven_move(80_000.0) == pytest.approx(80.0, rel=0.01)                 # ~10 bps taker/taker
    assert settlement.breakeven_move(80_000.0, "maker", "maker") == pytest.approx(32.0, rel=0.01)


def test_nonsense_is_refused():
    with pytest.raises(ValueError):
        settlement.settle("sideways", 1, 100, 100)
    with pytest.raises(ValueError):
        settlement.settle("long", 1, 100, 100, "slow", "taker")
