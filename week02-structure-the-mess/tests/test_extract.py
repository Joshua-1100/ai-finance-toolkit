"""Unit tests for the deterministic layer.

The integration tests here are regression tests for bugs that actually
happened during the build. Each one encodes a specific way the geometry
fooled the parser, so a future refactor cannot quietly reintroduce it.
"""
import pytest

from structure_the_mess.extract import clean_label, clean_number


class TestCleanNumber:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("1,234", 1234.0),
            ("$ 400,996", 400996.0),
            ("400,996", 400996.0),
            ("(34,698)", -34698.0),          # parens are negative, not literal
            ("(0.04)", -0.04),
            ("77.8%", 77.8),
            ("(8.7)%", -8.7),
            ("2,543.5", 2543.5),
            ("0", 0.0),
        ],
    )
    def test_parses(self, token, expected):
        assert clean_number(token) == expected

    @pytest.mark.parametrize("token", ["—", "–", "$", "", "   "])
    def test_nil_is_none_not_zero(self, token):
        # Nil and zero are different facts. Collapsing them corrupts deltas.
        assert clean_number(token) is None


class TestCleanLabel:
    def test_strips_footnote_markers(self):
        assert clean_label("Cost of revenue(1)(2)") == "Cost of revenue"
        assert (
            clean_label("General and administrative(1)(3)(5)(6)")
            == "General and administrative"
        )

    def test_keeps_parenthetical_meaning(self):
        # "(loss)" is part of the label, not a footnote marker.
        assert clean_label("Income (loss) before income taxes") == (
            "Income (loss) before income taxes"
        )

    def test_normalizes_whitespace_and_quotes(self):
        assert clean_label("  Total  stockholders’ equity ") == (
            "Total stockholders' equity"
        )


class TestRegressions:
    """Each test corresponds to a bug found while building this."""

    def test_wrapped_label_rows_are_not_dropped(self, rows):
        # BUG: when a label wraps to two lines the renderer centres the values
        # between them, 4pt from each. At the original 3pt row tolerance those
        # values formed a label-less row and were silently discarded, losing
        # two balance sheet lines entirely.
        labels = {r.raw_label for r in rows}
        assert "Current portion of convertible senior notes, net" in labels
        assert "Total liabilities and stockholders' equity" in labels

    def test_long_labels_are_not_truncated(self, rows):
        # BUG: label words were required to sit left of the value boundary, so
        # the tail of long labels vanished. That collapsed the beginning- and
        # end-of-period cash rows onto one identical label.
        labels = {r.raw_label for r in rows}
        assert "Cash, cash equivalents, and restricted cash, beginning of period" in labels
        assert "Cash, cash equivalents, and restricted cash, end of period" in labels
        assert "Asset acquisitions and business combinations, net of cash acquired" in labels

    def test_year_inside_label_is_not_read_as_a_value(self, rows):
        # "2030" in "issuance of 2030 convertible senior notes" parses as a
        # number but is left of the value boundary, so it must stay label text.
        row = next(r for r in rows if "2030 convertible senior notes" in r.raw_label
                   and r.raw_label.startswith("Gross proceeds"))
        assert row.values["Q2 2025"] == 2000000.0

    def test_page_number_is_not_a_value(self, rows):
        # The centered footer page number sits right of the label boundary and
        # parses as a bare integer.
        for r in rows:
            assert r.raw_label.strip() != ""

    def test_footnote_context_disambiguates_repeated_labels(self, rows):
        # "Cost of revenue" appears three times on page 3: once as the real
        # line item, once under the stock-comp footnote, once under the
        # intangibles footnote. Context must distinguish them.
        cor = [r for r in rows if r.raw_label == "Cost of revenue" and r.page == 3]
        assert len(cor) == 3
        assert cor[0].values["Q1 2026"] == 184158.0   # GAAP cost of revenue
        assert cor[1].values["Q1 2026"] == 4144.0     # stock comp within COGS
        assert cor[2].values["Q1 2026"] == 5961.0     # intangible amortization

    def test_negative_values_survive(self, rows):
        loss = next(r for r in rows if r.raw_label == "Loss from operations")
        assert loss.values["Q1 2026"] == -61994.0
