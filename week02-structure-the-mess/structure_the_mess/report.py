"""Standalone HTML report.

One self-contained file - no CDN, no build step, no network. It opens in a
browser by double-clicking, which matters because the audience for this
output is a hiring manager or a colleague, not a terminal.

Everything rendered here comes from the same validated Filing the DuckDB
load uses. The report deliberately shows the identity-check results and the
quarantined rows alongside the analysis: a report that only showed the
pretty tables would be hiding exactly the information that makes the pretty
tables trustworthy.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Optional

from .schema import Filing
from .validate import CheckResult, summarize

CSS = """
:root {
  --bg: #0f1115; --panel: #171a21; --line: #262b36; --text: #e6e9ef;
  --muted: #8b93a7; --accent: #f6821f; --ok: #3fb950; --bad: #f85149;
  --pos: #3fb950; --neg: #f85149; --blue: #58a6ff; --purple: #bc8cff;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 40px 32px 64px; background: var(--bg); color: var(--text);
  font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1120px; margin: 0 auto; }
h1 { font-size: 25px; margin: 0 0 4px; letter-spacing: -0.02em; }
h2 { font-size: 17px; margin: 40px 0 12px; letter-spacing: -0.01em; }
.sub { color: var(--muted); font-size: 13px; margin-bottom: 28px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 18px; min-width: 150px; flex: 1;
}
.card .n { font-size: 24px; font-weight: 650; letter-spacing: -0.02em; }
.card .l { color: var(--muted); font-size: 12px; margin-top: 2px; }
.card.good .n { color: var(--ok); }
.card.warn .n { color: var(--accent); }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--line); }
th:first-child, td:first-child { text-align: left; }
th {
  color: var(--muted); font-weight: 550; font-size: 11.5px;
  text-transform: uppercase; letter-spacing: 0.04em;
}
tbody tr:hover { background: #1c202a; }
.panel {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 6px 16px 4px; overflow-x: auto;
}
.pos { color: var(--pos); } .neg { color: var(--neg); } .mut { color: var(--muted); }
.pill {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 11.5px; font-weight: 600;
}
.pill.ok { background: rgba(63,185,80,.14); color: var(--ok); }
.pill.bad { background: rgba(248,81,73,.14); color: var(--bad); }
.note {
  color: var(--muted); font-size: 12.5px; margin: 10px 2px 0; line-height: 1.6;
}
details { margin-top: 10px; }
summary { cursor: pointer; color: var(--muted); font-size: 13px; padding: 6px 2px; }
summary:hover { color: var(--text); }
.legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px;
  color: var(--muted); margin: 10px 2px 0; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 6px; vertical-align: -1px; }
footer { color: var(--muted); font-size: 12px; margin-top: 48px;
  border-top: 1px solid var(--line); padding-top: 16px; }
code { background: #1c202a; padding: 1px 5px; border-radius: 4px; font-size: 12.5px; }
"""

# Funding sources, in stacking order, with display colors.
COMPONENTS = [
    ("delta_debt", "Debt", "#f85149"),
    ("delta_deferred_revenue", "Deferred revenue (customer-funded)", "#3fb950"),
    ("delta_apic", "Paid-in capital", "#58a6ff"),
    ("retained_earnings_change", "Retained earnings", "#bc8cff"),
    ("delta_aoci", "Other comprehensive income", "#8b93a7"),
]


def _fmt(v: Optional[float], dp: int = 0, suffix: str = "") -> str:
    if v is None:
        return '<span class="mut">—</span>'
    cls = "neg" if v < 0 else ""
    body = f"{v:,.{dp}f}{suffix}"
    if v < 0:
        body = f"({abs(v):,.{dp}f}{suffix})"
    return f'<span class="{cls}">{body}</span>' if cls else body


def _contribution_chart(funding: list[dict]) -> str:
    """Diverging stacked bars: what paid for each quarter's asset growth.

    Positive contributions stack up from the zero line, negative ones stack
    down, and a white tick marks net ΔAssets. Drawn as inline SVG so the
    report stays a single file with no chart library.
    """
    rows = [r for r in funding if r.get("delta_assets") is not None]
    if not rows:
        return ""

    span = 0.0
    for r in rows:
        up = sum(max(0.0, r.get(k) or 0.0) for k, _, _ in COMPONENTS)
        down = sum(min(0.0, r.get(k) or 0.0) for k, _, _ in COMPONENTS)
        span = max(span, up, abs(down), abs(r["delta_assets"]))
    if span <= 0:
        return ""

    W, H = 1060, 300
    pad_l, pad_b, pad_t = 62, 34, 14
    plot_h = H - pad_b - pad_t
    zero_y = pad_t + plot_h * 0.72   # more room above than below
    up_scale = (zero_y - pad_t) / span
    dn_scale = (H - pad_b - zero_y) / span
    slot = (W - pad_l - 16) / len(rows)
    bar_w = min(58, slot * 0.56)

    parts = [
        f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
        f'aria-label="Funding sources for asset growth by quarter">'
    ]
    # Gridlines
    for frac in (0.5, 1.0):
        y = zero_y - span * frac * up_scale
        parts.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W-8}" y2="{y:.1f}" '
            f'stroke="#262b36" stroke-width="1"/>'
            f'<text x="{pad_l-8}" y="{y+4:.1f}" fill="#8b93a7" font-size="10.5" '
            f'text-anchor="end">{span*frac/1000:,.0f}M</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="{zero_y:.1f}" x2="{W-8}" y2="{zero_y:.1f}" '
        f'stroke="#3d4453" stroke-width="1.5"/>'
        f'<text x="{pad_l-8}" y="{zero_y+4:.1f}" fill="#8b93a7" font-size="10.5" '
        f'text-anchor="end">0</text>'
    )

    for i, r in enumerate(rows):
        cx = pad_l + slot * i + slot / 2
        x = cx - bar_w / 2
        y_up, y_dn = zero_y, zero_y
        for key, label, color in COMPONENTS:
            v = r.get(key) or 0.0
            if v == 0:
                continue
            if v > 0:
                h = v * up_scale
                y_up -= h
                y = y_up
            else:
                h = abs(v) * dn_scale
                y = y_dn
                y_dn += h
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                f'height="{max(h,0.6):.1f}" fill="{color}" opacity="0.88">'
                f'<title>{html.escape(r["period"])} · {html.escape(label)}: '
                f'{v:,.0f}K</title></rect>'
            )
        # Net ΔAssets marker
        ny = zero_y - r["delta_assets"] * (up_scale if r["delta_assets"] >= 0 else -dn_scale)
        parts.append(
            f'<line x1="{x-5:.1f}" y1="{ny:.1f}" x2="{x+bar_w+5:.1f}" y2="{ny:.1f}" '
            f'stroke="#e6e9ef" stroke-width="2.25" stroke-linecap="round">'
            f'<title>{html.escape(r["period"])} · net ΔAssets: '
            f'{r["delta_assets"]:,.0f}K</title></line>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{H-12}" fill="#8b93a7" font-size="11.5" '
            f'text-anchor="middle">{html.escape(r["period"])}</text>'
        )

    parts.append("</svg>")
    legend = " ".join(
        f'<span><span class="swatch" style="background:{c}"></span>{html.escape(l)}</span>'
        for _, l, c in COMPONENTS
    )
    legend += ('<span><span class="swatch" style="background:#e6e9ef"></span>'
               "net ΔAssets</span>")
    return f'<div class="panel">{"".join(parts)}</div><div class="legend">{legend}</div>'


def _checks_table(results: list[CheckResult]) -> str:
    summary = summarize(results)
    rows = []
    for name, counts in sorted(summary["by_check"].items()):
        ok = counts["failed"] == 0
        pill = (f'<span class="pill ok">pass</span>' if ok
                else f'<span class="pill bad">{counts["failed"]} failed</span>')
        rows.append(
            f"<tr><td><code>{html.escape(name)}</code></td>"
            f'<td>{counts["passed"]}</td><td>{counts["failed"]}</td>'
            f"<td>{pill}</td></tr>"
        )
    failures = [r for r in results if not r.passed]
    detail = ""
    if failures:
        items = "".join(
            f"<li><code>{html.escape(f.name)}</code> {html.escape(f.period)}: "
            f"expected {f.expected:,.1f}, got {f.actual:,.1f}</li>"
            for f in failures
        )
        detail = f'<div class="note"><ul>{items}</ul></div>'
    return (
        '<div class="panel"><table><thead><tr><th>Identity check</th>'
        "<th>Passed</th><th>Failed</th><th></th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + detail
    )


def _funding_table(funding: list[dict]) -> str:
    head = (
        "<tr><th>Period</th><th>ΔAssets</th><th>ΔDebt</th>"
        "<th>ΔDeferred rev</th><th>ΔPaid-in capital</th>"
        "<th>Retained earnings</th><th>ΔOCI</th></tr>"
    )
    body = "".join(
        f"<tr><td>{html.escape(r['period'])}</td>"
        f"<td>{_fmt(r.get('delta_assets'))}</td>"
        f"<td>{_fmt(r.get('delta_debt'))}</td>"
        f"<td>{_fmt(r.get('delta_deferred_revenue'))}</td>"
        f"<td>{_fmt(r.get('delta_apic'))}</td>"
        f"<td>{_fmt(r.get('retained_earnings_change'))}</td>"
        f"<td>{_fmt(r.get('delta_aoci'))}</td></tr>"
        for r in funding
        if r.get("delta_assets") is not None
    )
    return f'<div class="panel"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def _efficiency_table(eff: list[dict]) -> str:
    head = (
        "<tr><th>Period</th><th>Asset turnover</th><th>Ex-cash</th>"
        "<th>Rev growth YoY</th><th>Asset growth YoY</th>"
        "<th>Incremental op margin</th><th>Current op margin</th>"
        "<th>Gross margin</th><th>SBC % of rev</th></tr>"
    )
    body = "".join(
        f"<tr><td>{html.escape(r['period'])}</td>"
        f"<td>{_fmt(r.get('asset_turnover'), 2)}</td>"
        f"<td>{_fmt(r.get('asset_turnover_ex_cash'), 2)}</td>"
        f"<td>{_fmt(r.get('revenue_growth_yoy_pct'), 1, '%')}</td>"
        f"<td>{_fmt(r.get('asset_growth_yoy_pct'), 1, '%')}</td>"
        f"<td>{_fmt(r.get('incremental_op_margin_pct'), 1, '%')}</td>"
        f"<td>{_fmt(r.get('current_op_margin_pct'), 1, '%')}</td>"
        f"<td>{_fmt(r.get('gaap_gross_margin_pct'), 1, '%')}</td>"
        f"<td>{_fmt(r.get('sbc_pct_of_revenue'), 1, '%')}</td></tr>"
        for r in eff
    )
    return f'<div class="panel"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def _quarantine_block(filing: Filing) -> str:
    if not filing.quarantined:
        return '<div class="note">No rows quarantined.</div>'
    rows = "".join(
        f"<tr><td>{r.page}</td><td>{html.escape(r.raw_label[:90])}</td></tr>"
        for r in filing.quarantined
    )
    return (
        f"<details><summary>{len(filing.quarantined)} quarantined rows "
        f"— shown, never dropped</summary>"
        f'<div class="panel"><table><thead><tr><th>Page</th>'
        f"<th>Raw label</th></tr></thead><tbody>{rows}</tbody></table></div>"
        f"</details>"
    )


def render(
    filing: Filing,
    results: list[CheckResult],
    funding: list[dict],
    efficiency: list[dict],
    raw_row_count: int,
) -> str:
    summary = summarize(results)
    all_pass = summary["failed"] == 0
    method = (
        "Claude tool-use"
        if any(li.normalization_method == "llm" for li in filing.line_items)
        else "deterministic alias table"
    )
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(filing.company)} — structured financial data</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>{html.escape(filing.company)} <span class="mut">({html.escape(filing.ticker)})</span></h1>
<div class="sub">
  {html.escape(filing.periods[0])} – {html.escape(filing.periods[-1])} ·
  source <code>{html.escape(filing.source_file)}</code> ·
  normalized via {method} · generated {generated}
</div>

<div class="cards">
  <div class="card"><div class="n">{raw_row_count}</div><div class="l">raw rows extracted</div></div>
  <div class="card"><div class="n">{len(filing.line_items):,}</div><div class="l">validated line items</div></div>
  <div class="card {'good' if all_pass else 'warn'}">
    <div class="n">{summary['passed']}/{summary['total']}</div>
    <div class="l">identity checks passed</div></div>
  <div class="card {'warn' if filing.quarantined else ''}">
    <div class="n">{len(filing.quarantined)}</div><div class="l">rows quarantined</div></div>
</div>

<h2>Accounting identity checks</h2>
{_checks_table(results)}
<div class="note">
  These assertions come from double-entry bookkeeping, not from hand-labelled
  expected values — the source statements must already satisfy every one of
  them. A wrong number cannot pass. This is the evidence the extraction is
  correct.
</div>

<h2>What funded the growth in the asset base</h2>
{_contribution_chart(funding)}
{_funding_table(funding)}
<div class="note">
  The equity roll-forward, made queryable: ΔAssets = ΔLiabilities + ΔEquity,
  with equity split into what the business earned and what it issued. All
  figures in thousands of USD.
</div>

<h2>Growth efficiency</h2>
{_efficiency_table(efficiency)}
<div class="note">
  Asset turnover is annualized revenue over total assets. The ex-cash column
  strips cash and investments, which is the one to read when a large raise is
  sitting in securities. Incremental operating margin is
  ΔOperating income ÷ ΔRevenue, year over year, on a non-GAAP basis; above the
  current margin means operating leverage, below means growth is getting more
  expensive.
</div>

<h2>Quarantine</h2>
{_quarantine_block(filing)}
<div class="note">
  Rows the normalizer would not map to a canonical key are held here rather
  than discarded. An empty quarantine is not the goal — a silent one is the
  failure mode.
</div>

<footer>
  Generated by <code>structure-the-mess</code> · deterministic extraction,
  model-assisted normalization, identity-checked output.
</footer>
</div></body></html>"""


def write_report(path: str | Path, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(**kwargs), encoding="utf-8")
    return path
