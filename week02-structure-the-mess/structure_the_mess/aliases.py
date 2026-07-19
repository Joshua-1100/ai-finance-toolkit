"""Deterministic label -> canonical key table.

Two jobs:

1. It lets the whole pipeline run with --no-llm, so the tool is usable and
   testable without an API key (and in CI, where there isn't one).
2. It is the regression baseline for the model. `compare_normalizers` in
   validate.py runs both paths over the same document and reports where they
   disagree. That comparison is the point: it turns "the LLM seems fine" into
   a measurable claim, and it is the seed of the eval harness Week 3 needs.

The table is hand-built for this issuer's layout. That is the honest
trade-off of the deterministic path - it does not generalize, which is
precisely why the model path exists.
"""
from __future__ import annotations

from typing import Optional

from .schema import RawRow, Statement

# Footnote block context -> handler. The page-3 footnote tables reuse the
# expense-category labels, so context is the only disambiguator.
_FOOTNOTE_PREFIXES: list[tuple[str, dict[str, str]]] = [
    (
        "(1) includes stock-based compensation",
        {
            "cost of revenue": "sbc_cost_of_revenue",
            "sales and marketing": "sbc_sales_and_marketing",
            "research and development": "sbc_research_and_development",
            "general and administrative": "sbc_general_and_administrative",
            "total stock-based compensation": "sbc_total",
        },
    ),
    (
        "(2) includes amortization of acquired",
        {
            "cost of revenue": "intangible_amortization_cost_of_revenue",
            "sales and marketing": "intangible_amortization_sales_and_marketing",
            "total amortization of acquired": "intangible_amortization_total",
        },
    ),
    (
        "(3) includes acquisition-related",
        {
            "general and administrative": "acquisition_related_expenses",
            "total acquisition-related": "acquisition_related_expenses",
        },
    ),
    (
        "(4) includes amortization of debt",
        {
            "interest expense": "debt_issuance_cost_amortization",
            "total amortization of debt": "debt_issuance_cost_amortization",
        },
    ),
    (
        "(5) includes lease impairment",
        {
            "general and administrative": "lease_impairment_charges",
            "total lease impairment": "lease_impairment_charges",
        },
    ),
    (
        "(6) includes legal reserve",
        {
            "general and administrative": "legal_reserve_and_settlements",
            "total legal reserve": "legal_reserve_and_settlements",
        },
    ),
]

# Ordered (substring, key) pairs, evaluated longest-substring-first so that
# "total operating expenses" wins over "operating expenses".
_TABLES: dict[Statement, dict[str, str]] = {
    Statement.INCOME_STATEMENT: {
        "revenue": "revenue",
        "cost of revenue": "cost_of_revenue",
        "gross profit": "gross_profit",
        "sales and marketing": "sales_and_marketing",
        "research and development": "research_and_development",
        "general and administrative": "general_and_administrative",
        "total operating expenses": "total_operating_expenses",
        "loss from operations": "operating_income_loss",
        "income from operations": "operating_income_loss",
        "interest income": "interest_income",
        "interest expense": "interest_expense",
        "other income (expense), net": "other_income_expense_net",
        "total non-operating income, net": "total_non_operating_income_net",
        "before income taxes": "pretax_income_loss",
        "provision for income taxes": "income_tax_provision",
        "net loss": "net_income_loss",
        "net income": "net_income_loss",
        "per share attributable to common stockholders, basic and diluted":
            "eps_diluted",
        "net income per share, basic": "eps_basic",
        "net income per share, diluted": "eps_diluted",
        "weighted-average shares used in computing net loss": "wavg_shares_basic",
        "weighted-average shares used in computing net income":
            "wavg_shares_diluted",
    },
    Statement.BALANCE_SHEET: {
        "cash and cash equivalents": "cash_and_equivalents",
        "available-for-sale securities": "available_for_sale_securities",
        "accounts receivable, net": "accounts_receivable_net",
        "contract assets": "contract_assets",
        "restricted cash short-term": "restricted_cash_current",
        "prepaid expenses and other current assets":
            "prepaid_and_other_current_assets",
        "total current assets": "total_current_assets",
        "property and equipment, net": "property_and_equipment_net",
        "goodwill": "goodwill",
        "acquired intangible assets, net": "acquired_intangibles_net",
        "operating lease right-of-use assets": "operating_lease_rou_assets",
        "deferred contract acquisition costs, noncurrent":
            "deferred_contract_acquisition_costs_noncurrent",
        "restricted cash": "restricted_cash_noncurrent",
        "other noncurrent assets": "other_noncurrent_assets",
        "total assets": "total_assets",
        "accounts payable": "accounts_payable",
        "accrued expenses and other current liabilities":
            "accrued_expenses_and_other_current_liabilities",
        "accrued compensation": "accrued_compensation",
        "operating lease liabilities": "operating_lease_liabilities_current",
        "operating lease liabilities, noncurrent":
            "operating_lease_liabilities_noncurrent",
        "deferred revenue": "deferred_revenue_current",
        "deferred revenue, noncurrent": "deferred_revenue_noncurrent",
        "current portion of convertible senior notes":
            "convertible_notes_current",
        "total current liabilities": "total_current_liabilities",
        "convertible senior notes, net": "convertible_notes_noncurrent",
        "other noncurrent liabilities": "other_noncurrent_liabilities",
        "total liabilities": "total_liabilities",
        "class a common stock": "common_stock_class_a",
        "class b common stock": "common_stock_class_b",
        "additional paid-in capital": "additional_paid_in_capital",
        "accumulated deficit": "accumulated_deficit",
        "accumulated other comprehensive": "accumulated_oci",
        "total stockholders' equity": "total_stockholders_equity",
        "total liabilities and stockholders' equity":
            "total_liabilities_and_equity",
    },
    Statement.CASH_FLOW: {
        "net loss": "cf_net_income_loss",
        "depreciation and amortization expense": "depreciation_and_amortization",
        "non-cash operating lease costs": "non_cash_operating_lease_costs",
        "amortization of deferred contract acquisition":
            "amortization_of_deferred_contract_costs",
        "stock-based compensation expense": "stock_based_compensation",
        "amortization of debt issuance costs":
            "amortization_of_debt_issuance_costs",
        "net accretion of discounts": "accretion_discounts_afs",
        "deferred income taxes": "deferred_income_taxes",
        "provision for bad debt": "provision_for_bad_debt",
        "other effect of asset acquisitions": "other_operating_adjustments",
        "accounts receivable, net": "chg_accounts_receivable",
        "contract assets": "chg_contract_assets",
        "deferred contract acquisition costs": "chg_deferred_contract_costs",
        "prepaid expenses and other current assets": "chg_prepaid_and_other_current",
        "other noncurrent assets": "chg_other_noncurrent_assets",
        "accounts payable": "chg_accounts_payable",
        "accrued expenses and other current liabilities": "chg_accrued_expenses",
        "accrued compensation": "chg_accrued_compensation",
        "operating lease liabilities": "chg_operating_lease_liabilities",
        "deferred revenue": "chg_deferred_revenue",
        "other noncurrent liabilities": "chg_other_noncurrent_liabilities",
        "net cash provided by operating activities": "net_cash_from_operating",
        "purchases of property and equipment": "purchases_of_ppe",
        "capitalized internal-use software": "capitalized_internal_use_software",
        "asset acquisitions and business combinations": "acquisitions_net_of_cash",
        "purchases of available-for-sale securities": "purchases_of_afs_securities",
        "maturities of available-for-sale securities": "maturities_of_afs_securities",
        "other investing activities": "other_investing",
        "net cash used in investing activities": "net_cash_from_investing",
        "proceeds from settlement of the 2025 capped":
            "proceeds_capped_call_settlement",
        "gross proceeds from issuance of 2030": "proceeds_convertible_notes",
        "purchases of capped calls": "purchases_of_capped_calls",
        "cash paid for issuance costs on 2030": "debt_issuance_costs_paid",
        "cash paid for issuance costs on revolving":
            "credit_facility_issuance_costs",
        "proceeds from the exercise of stock options":
            "proceeds_from_option_exercises",
        "proceeds from the early exercise": "proceeds_from_early_option_exercises",
        "proceeds from the issuance of common stock for employee":
            "proceeds_from_espp",
        "payment of tax withholding obligation": "taxes_paid_on_rsu_settlement",
        "payment of indemnity holdback": "payment_of_indemnity_holdback",
        "net cash provided by (used in) financing activities":
            "net_cash_from_financing",
        "net increase (decrease) in cash": "net_change_in_cash",
        "beginning of period": "cash_beginning_of_period",
        "end of period": "cash_end_of_period",
    },
    Statement.KEY_METRICS: {
        "net cash provided by operating activities": "net_cash_from_operating",
        "free cash flow": "free_cash_flow",
        "free cash flow margin": "free_cash_flow_margin",
        "net cash used in investing activities": "net_cash_from_investing",
        "net cash provided by (used in) financing activities":
            "net_cash_from_financing",
        "purchases of property and equipment (percentage": "ppe_pct_of_revenue",
        "capitalized internal-use software": "capsw_pct_of_revenue",
        "paying customers": "paying_customers_over_100k",
        "y-y growth": "customers_over_100k_yy_growth",
        "% of revenue": "customers_over_100k_pct_of_revenue",
        "dollar-based net retention rate": "dollar_based_net_retention",
        "remaining performance obligations": "remaining_performance_obligations",
        "current rpo as a percentage": "current_rpo_pct_of_total",
        "total headcount": "total_headcount",
        "revenue by region us": "revenue_us",
        "emea": "revenue_emea",
        "apac": "revenue_apac",
        "other": "revenue_other",
        "channel partners": "revenue_channel_partners",
        "direct customers": "revenue_direct_customers",
    },
}
_TABLES[Statement.INCOME_STATEMENT_NON_GAAP] = _TABLES[Statement.INCOME_STATEMENT]


# Checked before the longest-match pass. Some labels contain another label
# as a substring: the weighted-average share-count row ends with the full
# text of the EPS row, so pure longest-match maps it to eps_diluted.
_PRIORITY: list[tuple[str, str]] = [
    ("weighted-average shares used in computing net loss", "wavg_shares_basic"),
    ("weighted-average shares used in computing non-gaap", "wavg_shares_diluted"),
    ("weighted-average shares used in computing net income", "wavg_shares_diluted"),
]


def deterministic_map(row: RawRow, stmt: Statement) -> Optional[str]:
    label = row.raw_label.lower().strip()
    context = " > ".join(row.section_path).lower()

    for prefix, table in _FOOTNOTE_PREFIXES:
        if context.startswith(prefix):
            for needle, key in sorted(table.items(), key=lambda kv: -len(kv[0])):
                if needle in label:
                    return key
            return None

    for needle, key in _PRIORITY:
        if needle in label:
            return key

    table = _TABLES.get(stmt)
    if table is None:
        return None
    for needle, key in sorted(table.items(), key=lambda kv: -len(kv[0])):
        if needle in label:
            return key
    return None
