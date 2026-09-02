from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from bankstress.modeling import build_model_panel, run_cre_interaction, run_oos_models, run_split_panel_jackknife


def _root(tmp_path: Path) -> Path:
    (tmp_path / "configs").mkdir()
    spec = {"primary_segments": ["CRE"], "dynamic_fe_spec": {"exclude_merger_recent": True, "bank_features": ["lagged_noncurrent_ratio"], "segment_macro_variables": {"CRE": ["lagged_gdp_growth"]}},
            "oos_windows": [{"train_start": "2005-01-01", "train_end": "2011-12-31", "test_start": "2012-01-01", "test_end": "2013-12-31"}],
            "cre_interaction_spec": {"segment": "CRE", "exposure": "cre_to_tier1", "shock": "cre_price_growth", "pre_shock_reference": "2011-12-31"}}
    (tmp_path / "configs" / "model_specs.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return tmp_path


def _panel():
    dates = pd.date_range("2005-03-31", "2013-12-31", freq="QE")
    rows = []
    for bank, effect in [("1", .01), ("2", .02), ("3", .03)]:
        for number, date in enumerate(dates):
            nco = .02 + effect + .001 * number
            rows.append({"bank_id": bank, "segment": "CRE", "report_date": date, "annualized_nco_rate": nco, "total_npl": 10 + number,
                         "exposure": 1000, "total_loans": 5000, "allowance_coverage": .01, "tier1_ratio": .1, "loan_growth": .01, "eligible_for_model": 1,
                         "merger_recent_flag": 0, "cre_to_tier1": 2 + int(bank), "cre_share": .2, "lagged_nco": nco - .001})
    credit = pd.DataFrame(rows)
    macro = pd.DataFrame({"report_date": dates, "gdp_growth": np.linspace(1, 3, len(dates)), "cre_price_growth": np.linspace(-2, 2, len(dates))})
    noncurrent = pd.DataFrame([{"bank_id": bank, "report_date": date, "fdic_noncurrent_loans": 10 + number, "fdic_total_loans": 1000, "fdic_noncurrent_ratio": (10 + number) / 1000} for bank in ["1", "2", "3"] for number, date in enumerate(dates)])
    credit["cert"] = credit["bank_id"]
    return build_model_panel(credit, macro, noncurrent)


def test_oos_models_use_same_complete_sample_and_write_spj(tmp_path):
    root, panel = _root(tmp_path), _panel()
    eligible, metrics, coefficients = run_oos_models(panel, root)
    assert set(metrics.model) == {"ar", "dynamic_fe"}
    assert metrics.groupby(["window", "segment"]).n.nunique().eq(1).all()
    assert not coefficients.empty
    assert not run_split_panel_jackknife(eligible, root).empty


def test_cre_interaction_runs_with_bank_and_quarter_effects(tmp_path):
    root, panel = _root(tmp_path), _panel()
    result = run_cre_interaction(panel, root)
    assert "exposure_x_cre_price_shock" in set(result.term)
    assert (root / "outputs" / "models" / "cre_interaction" / "interaction_coefficients.csv").exists()
