"""Canonical schema for extracted financial data.

The whole point of this module is that everything downstream - DuckDB, the
validation suite, any analysis - depends on a *contract*, not on whatever
strings happened to appear in the PDF. The LLM's job in normalize.py is to
map messy reality onto these keys. Nothing else in the pipeline is allowed
to invent a key.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Statement(str, Enum):
    INCOME_STATEMENT = "income_statement"
    INCOME_STATEMENT_NON_GAAP = "income_statement_non_gaap"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    RECONCILIATION = "reconciliation"
    KEY_METRICS = "key_metrics"
    SEGMENT = "segment"


class Unit(str, Enum):
    """Unit traps are a top source of silent error in financial PDFs.

    This deck's page header says "in thousands" but the RPO row is captioned
    "(in millions)" and several rows are percentages or raw counts. Storing
    the unit per line item - rather than assuming the page header - is what
    keeps a 2,543.5 from being read as $2.5 billion when it is $2.5 billion
    but expressed differently from every row above it.
    """
    THOUSANDS_USD = "thousands_usd"
    MILLIONS_USD = "millions_usd"
    USD_PER_SHARE = "usd_per_share"
    THOUSANDS_SHARES = "thousands_shares"
    PERCENT = "percent"
    COUNT = "count"


# Canonical line-item keys. Deliberately finite: if the LLM proposes a key
# that is not here, normalize.py rejects it and the row is quarantined for
# human review rather than silently entering the dataset.
CANONICAL_KEYS: dict[Statement, set[str]] = {
    Statement.INCOME_STATEMENT: {
        "revenue", "cost_of_revenue", "gross_profit",
        "sales_and_marketing", "research_and_development",
        "general_and_administrative", "total_operating_expenses",
        "operating_income_loss", "interest_income", "interest_expense",
        "other_income_expense_net", "total_non_operating_income_net",
        "pretax_income_loss", "income_tax_provision", "net_income_loss",
        "eps_basic", "eps_diluted", "wavg_shares_basic", "wavg_shares_diluted",
        "sbc_cost_of_revenue", "sbc_sales_and_marketing",
        "sbc_research_and_development", "sbc_general_and_administrative",
        "sbc_total", "intangible_amortization_total",
        "acquisition_related_expenses", "lease_impairment_charges",
        "legal_reserve_and_settlements", "debt_issuance_cost_amortization",
        "intangible_amortization_cost_of_revenue",
        "intangible_amortization_sales_and_marketing",
    },
    Statement.BALANCE_SHEET: {
        "cash_and_equivalents", "available_for_sale_securities",
        "accounts_receivable_net", "contract_assets",
        "restricted_cash_current", "prepaid_and_other_current_assets",
        "total_current_assets", "property_and_equipment_net", "goodwill",
        "acquired_intangibles_net", "operating_lease_rou_assets",
        "deferred_contract_acquisition_costs_noncurrent",
        "restricted_cash_noncurrent", "other_noncurrent_assets",
        "total_assets", "accounts_payable",
        "accrued_expenses_and_other_current_liabilities",
        "accrued_compensation", "operating_lease_liabilities_current",
        "deferred_revenue_current", "convertible_notes_current",
        "total_current_liabilities", "convertible_notes_noncurrent",
        "operating_lease_liabilities_noncurrent",
        "deferred_revenue_noncurrent", "other_noncurrent_liabilities",
        "total_liabilities", "common_stock_class_a", "common_stock_class_b",
        "additional_paid_in_capital", "accumulated_deficit",
        "accumulated_oci", "total_stockholders_equity",
        "total_liabilities_and_equity",
    },
    Statement.CASH_FLOW: {
        "cf_net_income_loss", "depreciation_and_amortization",
        "non_cash_operating_lease_costs",
        "amortization_of_deferred_contract_costs",
        "stock_based_compensation", "amortization_of_debt_issuance_costs",
        "accretion_discounts_afs", "deferred_income_taxes",
        "provision_for_bad_debt", "other_operating_adjustments",
        "chg_accounts_receivable", "chg_contract_assets",
        "chg_deferred_contract_costs", "chg_prepaid_and_other_current",
        "chg_other_noncurrent_assets", "chg_accounts_payable",
        "chg_accrued_expenses", "chg_accrued_compensation",
        "chg_operating_lease_liabilities", "chg_deferred_revenue",
        "chg_other_noncurrent_liabilities", "net_cash_from_operating",
        "purchases_of_ppe", "capitalized_internal_use_software",
        "acquisitions_net_of_cash", "purchases_of_afs_securities",
        "maturities_of_afs_securities", "other_investing",
        "net_cash_from_investing", "proceeds_capped_call_settlement",
        "proceeds_convertible_notes", "purchases_of_capped_calls",
        "debt_issuance_costs_paid", "credit_facility_issuance_costs",
        "proceeds_from_option_exercises",
        "proceeds_from_early_option_exercises", "proceeds_from_espp",
        "taxes_paid_on_rsu_settlement", "payment_of_indemnity_holdback",
        "net_cash_from_financing", "net_change_in_cash",
        "cash_beginning_of_period", "cash_end_of_period",
    },
    Statement.KEY_METRICS: {
        "free_cash_flow", "free_cash_flow_margin",
        "ocf_pct_of_revenue", "ppe_pct_of_revenue", "capsw_pct_of_revenue",
        "paying_customers_over_100k", "customers_over_100k_yy_growth",
        "customers_over_100k_pct_of_revenue", "dollar_based_net_retention",
        "remaining_performance_obligations", "current_rpo_pct_of_total",
        "total_headcount",
    },
    Statement.SEGMENT: {
        "revenue_us", "revenue_emea", "revenue_apac", "revenue_other",
        "revenue_channel_partners", "revenue_direct_customers",
        "revenue_total_by_region", "revenue_total_by_customer_type",
    },
}
CANONICAL_KEYS[Statement.INCOME_STATEMENT_NON_GAAP] = CANONICAL_KEYS[
    Statement.INCOME_STATEMENT
]
CANONICAL_KEYS[Statement.RECONCILIATION] = (
    CANONICAL_KEYS[Statement.INCOME_STATEMENT] | {"non_gaap_adjustment"}
)


class RawRow(BaseModel):
    """A row exactly as it came off the page, before any interpretation."""
    page: int
    section_title: str
    section_path: list[str] = Field(
        default_factory=list,
        description="Statement subheadings above this row, e.g. ['Assets', 'Current assets']",
    )
    raw_label: str
    values: dict[str, Optional[float]]
    source_line: str

    @field_validator("raw_label")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


class LineItem(BaseModel):
    """A normalized, schema-conformant financial line item."""
    statement: Statement
    canonical_key: str
    label: str = Field(description="Original label, preserved for audit trail")
    period: str = Field(description="Fiscal period, e.g. 'Q1 2026'")
    value: Optional[float]
    unit: Unit
    page: int
    source_line: str = Field(
        default="",
        description="Verbatim text of the PDF row this value came from. The "
        "audit trail: it lets any figure be traced back to what was actually "
        "printed, without re-parsing the document.",
    )
    normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    normalization_method: str = Field(default="llm")

    @field_validator("canonical_key")
    @classmethod
    def _known_key(cls, v: str, info) -> str:
        stmt = info.data.get("statement")
        if stmt is not None and v not in CANONICAL_KEYS[stmt]:
            raise ValueError(f"'{v}' is not a canonical key for {stmt.value}")
        return v


class Filing(BaseModel):
    """The full extracted document."""
    company: str
    ticker: str
    fiscal_period: str
    source_file: str
    periods: list[str]
    line_items: list[LineItem]
    quarantined: list[RawRow] = Field(
        default_factory=list,
        description="Rows the pipeline refused to normalize. Reviewed, not dropped.",
    )

    def get(self, key: str, period: str) -> Optional[float]:
        for li in self.line_items:
            if li.canonical_key == key and li.period == period:
                return li.value
        return None

    def series(self, key: str) -> dict[str, Optional[float]]:
        return {
            p: self.get(key, p)
            for p in self.periods
            if self.get(key, p) is not None
        }
