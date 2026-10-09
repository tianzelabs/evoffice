"""The strategy version is what the leaderboard scores per row, so it must move
when the strategy moves and only then."""
from agents.trader.version import strategy_version


def ns_from(src: str) -> dict:
    ns: dict = {}
    exec(src, ns)
    ns.pop("__builtins__", None)
    return ns


def v(src):
    ns = ns_from(src)
    return strategy_version(ns, sorted(ns))[0]


def test_redefining_the_same_function_keeps_the_version():
    a = "def should_wake(b):\n    return len(b) > 3\n"
    assert v(a) == v(a) is not None


def test_changing_a_threshold_changes_the_version():
    assert v("def should_wake(b):\n    return len(b) > 3\n") != v("def should_wake(b):\n    return len(b) > 4\n")


def test_nested_functions_do_not_make_the_hash_depend_on_memory_addresses():
    src = "def f(x):\n    def g(y):\n        return y + 1\n    return g(x)\n"
    assert v(src) == v(src)


def test_data_and_notes_are_not_strategy():
    base = "def should_wake(b):\n    return True\n"
    assert v(base + "notes = 'a'\nprices = [1, 2]\n") == v(base + "notes = 'b'\nprices = [3]\n")


def test_a_class_counts_and_so_does_a_change_to_its_method():
    c1 = "class Model:\n    def score(self, x):\n        return x * 2\n"
    c2 = "class Model:\n    def score(self, x):\n        return x * 3\n"
    assert v(c1) is not None and v(c1) != v(c2)


def test_nothing_defined_means_no_version():
    assert v("x = 1\n") is None
