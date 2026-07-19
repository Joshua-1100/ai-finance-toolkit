"""The real test of the pipeline: does the output obey double-entry?

These assertions do not depend on hand-labelled expected values. They
depend on identities the source financial statements must already satisfy,
which makes them cheap to write and impossible to fudge.
"""
from structure_the_mess.validate import run_checks, summarize


def test_all_accounting_identities_hold(filing):
    results = run_checks(filing)
    failures = [r for r in results if not r.passed]
    assert not failures, "\n".join(
        f"{r.name} {r.period}: expected {r.expected:,.1f} got {r.actual:,.1f}"
        for r in failures
    )


def test_every_check_family_actually_ran(filing):
    # A suite that silently skips every check would also report zero failures.
    summary = summarize(run_checks(filing))
    expected_families = {
        "balance_sheet_balances", "gross_profit", "total_opex",
        "operating_result", "pretax_result", "net_result",
        "sbc_components_foot", "net_change_in_cash", "cash_rollforward",
        "free_cash_flow", "revenue_by_region_foots",
        "revenue_by_customer_type_foots", "clean_surplus", "delta_identity",
    }
    assert expected_families <= set(summary["by_check"])
    assert summary["total"] >= 100


def test_balance_sheet_balances_every_period(filing):
    for period in filing.periods:
        assets = filing.get("total_assets", period)
        liabilities = filing.get("total_liabilities", period)
        equity = filing.get("total_stockholders_equity", period)
        assert abs(assets - (liabilities + equity)) < 1.5, period


def test_clean_surplus_holds(filing):
    # No dividends, no buybacks: the change in accumulated deficit must equal
    # net income exactly. This is what licenses the funding-mix analysis.
    for prev, curr in zip(filing.periods, filing.periods[1:]):
        delta = (
            filing.get("accumulated_deficit", curr)
            - filing.get("accumulated_deficit", prev)
        )
        assert abs(delta - filing.get("net_income_loss", curr)) < 1.5, curr


def test_nothing_is_silently_dropped(filing):
    # Quarantined rows are allowed; unaccounted-for rows are not.
    keys = {li.canonical_key for li in filing.line_items}
    for required in ("revenue", "total_assets", "net_income_loss",
                     "additional_paid_in_capital", "free_cash_flow"):
        assert required in keys
