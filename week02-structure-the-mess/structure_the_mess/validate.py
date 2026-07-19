"""Accounting identity checks over the extracted data.

This module is the reason to trust the output. A parser that returns
plausible-looking numbers is worthless; a parser that returns numbers which
satisfy the accounting identities the source document must satisfy is
checkable. Every check below is a constraint the real financial statements
already obey, so any failure means the pipeline broke something - not that
the company's books are wrong.

These are also the seed of the Week 3 eval harness: a known-good test set
where the expected answers come from double-entry bookkeeping rather than
from hand-labelling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .schema import Filing

TOLERANCE = 1.5  # thousands of USD; absorbs the deck's own rounding


@dataclass
class CheckResult:
    name: str
    period: str
    passed: bool
    expected: Optional[float]
    actual: Optional[float]
    detail: str = ""

    @property
    def diff(self) -> Optional[float]:
        if self.expected is None or self.actual is None:
            return None
        return self.actual - self.expected


def _identity(
    filing: Filing,
    name: str,
    period: str,
    lhs_key: str,
    rhs_keys: list[str],
    signs: Optional[list[int]] = None,
) -> Optional[CheckResult]:
    """lhs == sum(sign_i * rhs_i), skipped if any input is absent."""
    lhs = filing.get(lhs_key, period)
    if lhs is None:
        return None
    signs = signs or [1] * len(rhs_keys)
    total = 0.0
    for key, sign in zip(rhs_keys, signs):
        val = filing.get(key, period)
        if val is None:
            return None
        total += sign * val
    return CheckResult(
        name=name,
        period=period,
        passed=abs(lhs - total) <= TOLERANCE,
        expected=total,
        actual=lhs,
        detail=f"{lhs_key} vs {' + '.join(rhs_keys)}",
    )


def run_checks(filing: Filing) -> list[CheckResult]:
    results: list[CheckResult] = []
    periods = filing.periods

    for i, p in enumerate(periods):
        # --- The fundamental identity. If this fails nothing else matters.
        results.append(
            _identity(
                filing, "balance_sheet_balances", p,
                "total_assets",
                ["total_liabilities", "total_stockholders_equity"],
            )
        )
        results.append(
            _identity(
                filing, "assets_equal_stated_total", p,
                "total_liabilities_and_equity", ["total_assets"],
            )
        )
        # --- Income statement articulation.
        results.append(
            _identity(
                filing, "gross_profit", p,
                "gross_profit", ["revenue", "cost_of_revenue"], [1, -1],
            )
        )
        results.append(
            _identity(
                filing, "total_opex", p,
                "total_operating_expenses",
                [
                    "sales_and_marketing",
                    "research_and_development",
                    "general_and_administrative",
                ],
            )
        )
        results.append(
            _identity(
                filing, "operating_result", p,
                "operating_income_loss",
                ["gross_profit", "total_operating_expenses"], [1, -1],
            )
        )
        results.append(
            _identity(
                filing, "pretax_result", p,
                "pretax_income_loss",
                ["operating_income_loss", "total_non_operating_income_net"],
            )
        )
        results.append(
            _identity(
                filing, "net_result", p,
                "net_income_loss",
                ["pretax_income_loss", "income_tax_provision"], [1, -1],
            )
        )
        # --- Stock comp footnote must foot to its own total.
        results.append(
            _identity(
                filing, "sbc_components_foot", p,
                "sbc_total",
                [
                    "sbc_cost_of_revenue",
                    "sbc_sales_and_marketing",
                    "sbc_research_and_development",
                    "sbc_general_and_administrative",
                ],
            )
        )
        # --- Cash flow articulation.
        results.append(
            _identity(
                filing, "net_change_in_cash", p,
                "net_change_in_cash",
                [
                    "net_cash_from_operating",
                    "net_cash_from_investing",
                    "net_cash_from_financing",
                ],
            )
        )
        results.append(
            _identity(
                filing, "cash_rollforward", p,
                "cash_end_of_period",
                ["cash_beginning_of_period", "net_change_in_cash"],
            )
        )
        results.append(
            _identity(
                filing, "free_cash_flow", p,
                "free_cash_flow",
                [
                    "net_cash_from_operating",
                    "purchases_of_ppe",
                    "capitalized_internal_use_software",
                ],
            )
        )
        # --- Revenue disaggregation must reconcile to the top line, twice.
        results.append(
            _identity(
                filing, "revenue_by_region_foots", p,
                "revenue",
                ["revenue_us", "revenue_emea", "revenue_apac", "revenue_other"],
            )
        )
        results.append(
            _identity(
                filing, "revenue_by_customer_type_foots", p,
                "revenue",
                ["revenue_channel_partners", "revenue_direct_customers"],
            )
        )
        # --- Clean surplus. Cloudflare pays no dividend and repurchases no
        # stock, so the change in accumulated deficit must equal net income
        # exactly. This check is what makes the equity roll-forward - and
        # therefore any funding-source analysis built on it - trustworthy.
        if i > 0:
            prev = periods[i - 1]
            ad_now = filing.get("accumulated_deficit", p)
            ad_prev = filing.get("accumulated_deficit", prev)
            ni = filing.get("net_income_loss", p)
            if None not in (ad_now, ad_prev, ni):
                results.append(
                    CheckResult(
                        name="clean_surplus",
                        period=p,
                        passed=abs((ad_now - ad_prev) - ni) <= TOLERANCE,
                        expected=ni,
                        actual=ad_now - ad_prev,
                        detail="change in accumulated deficit vs net income",
                    )
                )
            # --- Balance sheet delta must equal liability delta plus equity delta.
            ta = filing.get("total_assets", p), filing.get("total_assets", prev)
            tl = filing.get("total_liabilities", p), filing.get("total_liabilities", prev)
            te = (
                filing.get("total_stockholders_equity", p),
                filing.get("total_stockholders_equity", prev),
            )
            if all(v is not None for v in ta + tl + te):
                d_a, d_l, d_e = ta[0] - ta[1], tl[0] - tl[1], te[0] - te[1]
                results.append(
                    CheckResult(
                        name="delta_identity",
                        period=p,
                        passed=abs(d_a - (d_l + d_e)) <= TOLERANCE,
                        expected=d_l + d_e,
                        actual=d_a,
                        detail="ΔAssets vs ΔLiabilities + ΔEquity",
                    )
                )

    return [r for r in results if r is not None]


def summarize(results: list[CheckResult]) -> dict:
    by_name: dict[str, dict[str, int]] = {}
    for r in results:
        entry = by_name.setdefault(r.name, {"passed": 0, "failed": 0})
        entry["passed" if r.passed else "failed"] += 1
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "by_check": by_name,
    }


def compare_normalizers(rows, llm_items, alias_items) -> dict:
    """Where do the model and the hand-built alias table disagree?

    This is the honest measurement of the LLM step. Agreement on rows the
    alias table covers is evidence the model is not quietly inventing
    mappings; rows only the model covers are where it earns its keep.
    """
    llm_map = {(i.page, i.label): i.canonical_key for i in llm_items}
    alias_map = {(i.page, i.label): i.canonical_key for i in alias_items}
    shared = set(llm_map) & set(alias_map)
    disagreements = [
        {"page": k[0], "label": k[1], "llm": llm_map[k], "alias": alias_map[k]}
        for k in sorted(shared)
        if llm_map[k] != alias_map[k]
    ]
    return {
        "rows_both_mapped": len(shared),
        "agreements": len(shared) - len(disagreements),
        "disagreements": disagreements,
        "llm_only": sorted(set(llm_map) - set(alias_map)),
        "alias_only": sorted(set(alias_map) - set(llm_map)),
    }
