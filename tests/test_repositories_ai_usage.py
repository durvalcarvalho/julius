from julius.repositories import ai_usage


def test_spent_in_month_defaults_to_zero(conn):
    assert ai_usage.spent_in_month(conn, "2026-09") == 0.0


def test_add_spent_accumulates_within_month_and_isolates_months(conn):
    ai_usage.add_spent(conn, "2026-09", 0.25)
    ai_usage.add_spent(conn, "2026-09", 0.5)
    ai_usage.add_spent(conn, "2026-10", 0.1)
    assert ai_usage.spent_in_month(conn, "2026-09") == 0.75
    assert ai_usage.spent_in_month(conn, "2026-10") == 0.1
    assert ai_usage.spent_in_month(conn, "2026-08") == 0.0
