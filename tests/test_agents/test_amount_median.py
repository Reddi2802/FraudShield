"""ADR-030: the amount rule compares with the customer's MEDIAN, so earlier outliers cannot hide a spike."""

from __future__ import annotations

from agents.rule_compliance import check_amount

TYPICAL = [50.0, 55.0, 60.0, 52.0, 58.0]


def test_spike_fires_against_a_normal_history():
    fired, detail, rule = check_amount(10_526.0, TYPICAL, global_p99=None)
    assert fired and rule == "amount_own_history" and "median" in detail


def test_earlier_flagged_outliers_do_not_hide_a_new_spike():
    """The bug: after 576 / 5,766 / 57,666 landed in the history the MEAN reached ~$4,700, so 3x mean
    (~$14,100) let a $10,526 transaction through. The median stays near $58."""
    poisoned = TYPICAL + [576.0, 5_766.0, 57_666.0]
    assert sum(poisoned) / len(poisoned) * 3 > 10_526.0  # the old (mean) rule would have passed it
    fired, _, rule = check_amount(10_526.0, poisoned, global_p99=None)
    assert fired and rule == "amount_own_history"


def test_normal_amounts_still_pass():
    assert check_amount(120.0, TYPICAL, global_p99=None)[0] is False


def test_thin_history_still_uses_the_global_fallback():
    assert check_amount(500.0, [50.0, 60.0], global_p99=400.0)[2] == "amount_global_fallback"
