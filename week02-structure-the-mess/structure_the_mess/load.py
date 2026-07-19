"""Load validated line items into DuckDB.

Long format, one row per (statement, key, period). Wide financial tables
are pleasant to read and miserable to query - every new quarter would be a
schema change. Long format means adding Q2 2026 is an INSERT.

The views on top implement the growth-attribution metric set: where did the
change in the asset base actually come from, and is the revenue it bought
getting cheaper or more expensive.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from .schema import Filing

SCHEMA = """
CREATE TABLE IF NOT EXISTS line_items (
    company            VARCHAR,
    ticker             VARCHAR,
    source_file        VARCHAR,
    statement          VARCHAR,
    canonical_key      VARCHAR,
    label              VARCHAR,
    period             VARCHAR,
    period_sort        INTEGER,
    value              DOUBLE,
    unit               VARCHAR,
    page               INTEGER,
    source_line        VARCHAR,
    confidence         DOUBLE,
    method             VARCHAR
);

CREATE TABLE IF NOT EXISTS quarantined (
    company     VARCHAR,
    page        INTEGER,
    section     VARCHAR,
    raw_label   VARCHAR,
    source_line VARCHAR
);
"""

# A tidy wide view of the keys the growth analysis needs.
FACTS_VIEW = """
CREATE OR REPLACE VIEW facts AS
SELECT
    period,
    period_sort,
    MAX(CASE WHEN canonical_key = 'revenue'
        AND statement = 'income_statement' THEN value END)      AS revenue,
    MAX(CASE WHEN canonical_key = 'cost_of_revenue'
        AND statement = 'income_statement' THEN value END)      AS cost_of_revenue,
    MAX(CASE WHEN canonical_key = 'operating_income_loss'
        AND statement = 'income_statement' THEN value END)      AS gaap_operating_income,
    MAX(CASE WHEN canonical_key = 'operating_income_loss'
        AND statement = 'income_statement_non_gaap' THEN value END)
                                                                AS non_gaap_operating_income,
    MAX(CASE WHEN canonical_key = 'net_income_loss'
        AND statement = 'income_statement' THEN value END)      AS net_income,
    MAX(CASE WHEN canonical_key = 'total_assets' THEN value END)        AS total_assets,
    MAX(CASE WHEN canonical_key = 'total_liabilities' THEN value END)   AS total_liabilities,
    MAX(CASE WHEN canonical_key = 'total_stockholders_equity' THEN value END)
                                                                AS total_equity,
    MAX(CASE WHEN canonical_key = 'additional_paid_in_capital' THEN value END)
                                                                AS apic,
    MAX(CASE WHEN canonical_key = 'accumulated_deficit' THEN value END) AS accumulated_deficit,
    MAX(CASE WHEN canonical_key = 'accumulated_oci' THEN value END)     AS aoci,
    COALESCE(MAX(CASE WHEN canonical_key = 'convertible_notes_current' THEN value END), 0)
      + COALESCE(MAX(CASE WHEN canonical_key = 'convertible_notes_noncurrent' THEN value END), 0)
                                                                AS total_debt,
    COALESCE(MAX(CASE WHEN canonical_key = 'deferred_revenue_current' THEN value END), 0)
      + COALESCE(MAX(CASE WHEN canonical_key = 'deferred_revenue_noncurrent' THEN value END), 0)
                                                                AS deferred_revenue,
    COALESCE(MAX(CASE WHEN canonical_key = 'cash_and_equivalents' THEN value END), 0)
      + COALESCE(MAX(CASE WHEN canonical_key = 'available_for_sale_securities' THEN value END), 0)
                                                                AS cash_and_investments,
    MAX(CASE WHEN canonical_key = 'stock_based_compensation' THEN value END)
                                                                AS sbc_cash_flow,
    MAX(CASE WHEN canonical_key = 'proceeds_from_option_exercises' THEN value END)
                                                                AS option_proceeds,
    MAX(CASE WHEN canonical_key = 'free_cash_flow' THEN value END)      AS free_cash_flow
FROM line_items
GROUP BY period, period_sort;
"""

# Where did the change in the asset base come from? This is the equity
# roll-forward made queryable: ΔAssets = ΔLiabilities + ΔEquity, with equity
# split into the part the business earned and the part it issued.
FUNDING_VIEW = """
CREATE OR REPLACE VIEW funding_mix AS
SELECT
    period,
    period_sort,
    total_assets - LAG(total_assets) OVER w                AS delta_assets,
    total_debt - LAG(total_debt) OVER w                    AS delta_debt,
    deferred_revenue - LAG(deferred_revenue) OVER w        AS delta_deferred_revenue,
    apic - LAG(apic) OVER w                                AS delta_apic,
    net_income                                             AS retained_earnings_change,
    aoci - LAG(aoci) OVER w                                AS delta_aoci,
    ROUND(100.0 * (total_debt - LAG(total_debt) OVER w)
          / NULLIF(total_assets - LAG(total_assets) OVER w, 0), 1)  AS pct_debt_funded,
    ROUND(100.0 * (apic - LAG(apic) OVER w)
          / NULLIF(total_assets - LAG(total_assets) OVER w, 0), 1)  AS pct_equity_funded,
    ROUND(100.0 * (deferred_revenue - LAG(deferred_revenue) OVER w)
          / NULLIF(total_assets - LAG(total_assets) OVER w, 0), 1)  AS pct_customer_funded
FROM facts
WINDOW w AS (ORDER BY period_sort)
ORDER BY period_sort;
"""

# Growth quality. Gross asset turnover is distorted by a large cash raise
# sitting in securities, so the ex-cash version is the one to read.
EFFICIENCY_VIEW = """
CREATE OR REPLACE VIEW growth_efficiency AS
SELECT
    period,
    period_sort,
    ROUND(revenue * 4.0 / NULLIF(total_assets, 0), 3)       AS asset_turnover,
    ROUND(revenue * 4.0
          / NULLIF(total_assets - cash_and_investments, 0), 3)
                                                            AS asset_turnover_ex_cash,
    ROUND(100.0 * (revenue - LAG(revenue, 4) OVER w)
          / NULLIF(LAG(revenue, 4) OVER w, 0), 1)           AS revenue_growth_yoy_pct,
    ROUND(100.0 * (total_assets - LAG(total_assets, 4) OVER w)
          / NULLIF(LAG(total_assets, 4) OVER w, 0), 1)      AS asset_growth_yoy_pct,
    ROUND(100.0 * (non_gaap_operating_income - LAG(non_gaap_operating_income, 4) OVER w)
          / NULLIF(revenue - LAG(revenue, 4) OVER w, 0), 1) AS incremental_op_margin_pct,
    ROUND(100.0 * non_gaap_operating_income / NULLIF(revenue, 0), 1)
                                                            AS current_op_margin_pct,
    ROUND(100.0 * (revenue - cost_of_revenue) / NULLIF(revenue, 0), 1)
                                                            AS gaap_gross_margin_pct,
    ROUND(100.0 * sbc_cash_flow / NULLIF(revenue, 0), 1)    AS sbc_pct_of_revenue
FROM facts
WINDOW w AS (ORDER BY period_sort)
ORDER BY period_sort;
"""


# Which derived view columns are computed from which canonical keys. Kept
# next to the SQL that defines them so the two stay in step. Used by the
# --trace command to answer "what else moves if this number is wrong?"
VIEW_DEPENDENCIES: dict[str, list[str]] = {
    "facts.revenue": ["revenue"],
    "facts.cost_of_revenue": ["cost_of_revenue"],
    "facts.gaap_operating_income": ["operating_income_loss"],
    "facts.non_gaap_operating_income": ["operating_income_loss"],
    "facts.net_income": ["net_income_loss"],
    "facts.total_assets": ["total_assets"],
    "facts.total_liabilities": ["total_liabilities"],
    "facts.total_equity": ["total_stockholders_equity"],
    "facts.apic": ["additional_paid_in_capital"],
    "facts.accumulated_deficit": ["accumulated_deficit"],
    "facts.aoci": ["accumulated_oci"],
    "facts.total_debt": [
        "convertible_notes_current",
        "convertible_notes_noncurrent",
    ],
    "facts.deferred_revenue": [
        "deferred_revenue_current",
        "deferred_revenue_noncurrent",
    ],
    "facts.cash_and_investments": [
        "cash_and_equivalents",
        "available_for_sale_securities",
    ],
    "facts.sbc_cash_flow": ["stock_based_compensation"],
    "facts.free_cash_flow": ["free_cash_flow"],
    "funding_mix.delta_assets": ["total_assets"],
    "funding_mix.delta_debt": [
        "convertible_notes_current",
        "convertible_notes_noncurrent",
    ],
    "funding_mix.delta_deferred_revenue": [
        "deferred_revenue_current",
        "deferred_revenue_noncurrent",
    ],
    "funding_mix.delta_apic": ["additional_paid_in_capital"],
    "funding_mix.retained_earnings_change": ["net_income_loss"],
    "funding_mix.delta_aoci": ["accumulated_oci"],
    "growth_efficiency.asset_turnover": ["revenue", "total_assets"],
    "growth_efficiency.asset_turnover_ex_cash": [
        "revenue", "total_assets", "cash_and_equivalents",
        "available_for_sale_securities",
    ],
    "growth_efficiency.revenue_growth_yoy_pct": ["revenue"],
    "growth_efficiency.asset_growth_yoy_pct": ["total_assets"],
    "growth_efficiency.incremental_op_margin_pct": [
        "operating_income_loss", "revenue",
    ],
    "growth_efficiency.gaap_gross_margin_pct": ["revenue", "cost_of_revenue"],
    "growth_efficiency.sbc_pct_of_revenue": [
        "stock_based_compensation", "revenue",
    ],
}


def dependents_of(canonical_key: str) -> list[str]:
    """Derived view columns that would move if this key were wrong."""
    return sorted(
        col for col, keys in VIEW_DEPENDENCIES.items() if canonical_key in keys
    )


def _period_sort(period: str) -> int:
    """'Q1 2026' -> 20261, so ordering is chronological not lexical."""
    q, year = period.split()
    return int(year) * 10 + int(q[1])


def load(filing: Filing, db_path: str | Path) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Rebuild rather than delete. Unlinking fails whenever the file is locked
    # or lives on a read-only mount, and losing the run over a stale artifact
    # is a bad trade - dropping the tables achieves the same thing.
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass
    con = duckdb.connect(str(db_path))
    con.execute("DROP TABLE IF EXISTS line_items")
    con.execute("DROP TABLE IF EXISTS quarantined")
    con.execute(SCHEMA)

    con.executemany(
        "INSERT INTO line_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                filing.company,
                filing.ticker,
                filing.source_file,
                li.statement.value,
                li.canonical_key,
                li.label,
                li.period,
                _period_sort(li.period),
                li.value,
                li.unit.value,
                li.page,
                li.source_line,
                li.normalization_confidence,
                li.normalization_method,
            )
            for li in filing.line_items
        ],
    )
    con.executemany(
        "INSERT INTO quarantined VALUES (?,?,?,?,?)",
        [
            (filing.company, r.page, r.section_title, r.raw_label, r.source_line)
            for r in filing.quarantined
        ],
    )
    for view in (FACTS_VIEW, FUNDING_VIEW, EFFICIENCY_VIEW):
        con.execute(view)
    con.commit()
    return con
