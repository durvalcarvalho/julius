from julius.repositories import decision_usage


def test_spent_in_month_defaults_to_zero(conn):
    assert decision_usage.spent_in_month(conn, "typesafe", "2026-09") == 0.0


def test_add_spent_accumulates_within_month_and_isolates_by_provider_and_month(conn):
    decision_usage.add_spent(conn, "typesafe", "2026-09", 0.02)
    decision_usage.add_spent(conn, "typesafe", "2026-09", 0.03)
    decision_usage.add_spent(conn, "typesafe", "2026-10", 0.01)
    decision_usage.add_spent(conn, "other-provider", "2026-09", 0.5)
    assert decision_usage.spent_in_month(conn, "typesafe", "2026-09") == 0.05
    assert decision_usage.spent_in_month(conn, "typesafe", "2026-10") == 0.01
    assert decision_usage.spent_in_month(conn, "typesafe", "2026-08") == 0.0
    assert decision_usage.spent_in_month(conn, "other-provider", "2026-09") == 0.5
