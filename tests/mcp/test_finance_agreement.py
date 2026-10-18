"""The widget's provisional calculator agrees with the server's engine.

`financial_model.html` inlines a JavaScript port of `tender.services.finance` between the
markers `finance.js begin` and `finance.js end`; this test extracts it, runs it in node
over a fixture set of assumption combinations, and compares with the Python engine: IRRs
within 0.05 points, levelised cost within 0.5%, payback within 0.05 years. Divergence is
a bug in the widget, never a reason to change the server."""

import itertools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tender.services.finance import Assumptions, FixedInputs, power_project_finance

ROOT = Path(__file__).resolve().parents[2]
WIDGET = ROOT / "mcp" / "widgets" / "financial_model.html"
assert WIDGET.is_file() and "tests" not in WIDGET.parts, WIDGET
FIXED = [
    FixedInputs(
        capacity_mw=700,
        tariff_inr_per_kwh=None,
        cuf_floor_percent=17,
        cuf_ceiling_percent=30,
        ppa_tenure_years=25,
        scod_months=24,
        degradation_cap_percent=0.5,
        pbg_inr_per_mw=2.32e6,
        pbg_duration_months=30,
        ists_waiver=True,
        sources={"cuf_floor_percent": "tender"},
    ),
    FixedInputs(
        capacity_mw=100,
        tariff_inr_per_kwh=2.9,
        cuf_floor_percent=None,
        cuf_ceiling_percent=None,
        ppa_tenure_years=None,
        scod_months=None,
        degradation_cap_percent=None,
        pbg_inr_per_mw=None,
        pbg_duration_months=None,
        ists_waiver=None,
    ),
]
COMBOS = [
    Assumptions(capex_inr_crore_per_mw=c, debt_share_percent=d, interest_percent=i, cuf_percent=u)
    for c, d, i, u in itertools.product((3.2, 4.1, 5.6), (60.0, 80.0), (8.0, 11.5), (20.0, 27.5))
][:16]


def finance_js() -> str:
    html = WIDGET.read_text(encoding="utf-8")
    match = re.search(r"/\* finance\.js begin.*?\*/(.*?)/\* finance\.js end \*/", html, re.S)
    assert match, "the widget inlines finance.js between its markers"
    return match.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is in the tests container")
def test_widget_and_server_agree_within_tolerance(tmp_path: Path) -> None:
    cases = [
        {"fixed": fixed.__dict__, "assumptions": assumptions.__dict__}
        for fixed in FIXED
        for assumptions in COMBOS
    ]
    assert len(cases) >= 12
    script = tmp_path / "run.js"
    script.write_text(
        finance_js() + "\nconst cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
        "const run = (c) => globalThis.TenderFinance.powerProjectFinance(c.fixed, c.assumptions);\n"
        "console.log(JSON.stringify(cases.map(run)));\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        ["node", str(script)], input=json.dumps(cases), capture_output=True, text=True, check=True
    )
    results = json.loads(out.stdout)
    for case, got in zip(cases, results, strict=True):
        want = power_project_finance(
            FixedInputs(**case["fixed"]), Assumptions(**case["assumptions"])
        )
        assert got["used"] == want.used
        for key in ("project_irr_percent", "equity_irr_percent"):
            w, g = getattr(want, key), got[key]
            assert (w is None) == (g is None), key
            if w is not None:
                assert abs(w - g) <= 0.05, (key, w, g, case["assumptions"])
        assert want.levelised_cost_inr_per_kwh is not None and got["levelised_cost_inr_per_kwh"]
        assert (
            abs(want.levelised_cost_inr_per_kwh - got["levelised_cost_inr_per_kwh"])
            <= 0.005 * want.levelised_cost_inr_per_kwh
        )
        if want.payback_years is not None:
            assert abs(want.payback_years - got["payback_years"]) <= 0.05
        assert abs(want.capex_crore - got["capex_crore"]) < 0.01
        assert len(got["cashflows"]) == len(want.cashflows)
