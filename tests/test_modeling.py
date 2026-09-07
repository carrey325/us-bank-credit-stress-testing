from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from bankstress.modeling import _fit_entity_fe, _ols, _predict_entity_fe, _prepare_cre_interaction_data, build_model_panel, load_model_specs, run_cre_interaction, run_oos_models, run_split_panel_jackknife


def _root(tmp_path: Path) -> Path:
    (tmp_path / "configs").mkdir()
    spec = {"primary_segments": ["CRE"], "dynamic_fe_spec": {"exclude_merger_recent": True, "bank_features": ["lagged_noncurrent_ratio"], "segment_macro_variables": {"CRE": ["lagged_gdp_growth"]}},
            "oos_windows": [{"train_start": "2005-01-01", "train_end": "2011-12-31", "test_start": "2012-01-01", "test_end": "2013-12-31"}],
            "cre_interaction_spec": {"segment": "CRE", "exposure": "cre_to_tier1", "exposure_timing": "bank_quarter_lagged_at_forecast_origin", "shock": "cre_price_growth", "include_time_varying_exposure_main_effect": True}}
    (tmp_path / "configs" / "model_specs.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    return tmp_path


def _panel():
    dates = pd.date_range("2005-03-31", "2013-12-31", freq="QE")
    rows = []
    for bank, effect in [("1", .01), ("2", .02), ("3", .03)]:
        for number, date in enumerate(dates):
            nco = .02 + effect + .001 * number
            rows.append({"bank_id": bank, "segment": "CRE", "report_date": date, "annualized_nco_rate": nco, "total_npl": 10 + number,
                         "exposure": 1000, "total_loans": 5000, "allowance": 5 + number, "allowance_coverage": .01, "tier1_ratio": .1, "loan_growth": .01, "eligible_for_model": 1,
                         "merger_recent_flag": 0, "cre_to_tier1": 2 + int(bank), "cre_share": .2, "lagged_nco": nco - .001})
    credit = pd.DataFrame(rows)
    macro = pd.DataFrame({"report_date": dates, "gdp_growth": np.linspace(1, 3, len(dates)), "cre_price_growth": np.linspace(-2, 2, len(dates))})
    noncurrent = pd.DataFrame([{"bank_id": bank, "report_date": date, "fdic_noncurrent_loans": 10 + number, "fdic_total_loans": 1000, "fdic_noncurrent_ratio": (10 + number) / 1000} for bank in ["1", "2", "3"] for number, date in enumerate(dates)])
    credit["cert"] = credit["bank_id"]
    return build_model_panel(credit, macro, noncurrent)


def test_oos_models_use_same_complete_sample_and_write_spj(tmp_path):
    root, panel = _root(tmp_path), _panel()
    assert panel.loc[panel.target_period.eq(pd.Timestamp("2005-06-30")), "lagged_allowance_coverage"].iloc[0] == (5 / 10)
    eligible, metrics, coefficients = run_oos_models(panel, root)
    assert set(metrics.model) == {"ar", "dynamic_fe"}
    assert metrics.groupby(["window", "segment", "weighting"]).n.nunique().eq(1).all()
    assert metrics.common_scoring_keys_verified.all()
    assert not coefficients.empty
    assert not run_split_panel_jackknife(eligible, root).empty


def test_cre_interaction_runs_with_bank_and_quarter_effects(tmp_path):
    root, panel = _root(tmp_path), _panel()
    result = run_cre_interaction(panel, root)
    assert "exposure_x_cre_price_shock" in set(result.term)
    assert "lagged_exposure" in set(result.term)
    assert (root / "outputs" / "models" / "cre_interaction" / "interaction_coefficients.csv").exists()


def test_cre_interaction_exposure_never_postdates_forecast_origin(tmp_path):
    root, panel = _root(tmp_path), _panel()
    panel = panel.sort_values(["bank_id", "report_date"]).copy()
    panel["origin_cre_to_tier1"] = np.arange(len(panel), dtype=float)
    prepared = _prepare_cre_interaction_data(panel, load_model_specs(root)["cre_interaction_spec"]).dropna(subset=["lagged_exposure"])

    assert prepared["exposure_as_of_date"].le(prepared["forecast_origin"]).all()
    bank_one = prepared[prepared.bank_id.eq("1")].iloc[0]
    assert bank_one["lagged_exposure"] == bank_one["origin_cre_to_tier1"]


def test_missing_quarter_gap_does_not_create_lags():
    credit, macro, noncurrent = _panel_inputs()
    credit = credit[~((credit.bank_id == "1") & (credit.report_date == pd.Timestamp("2008-06-30")))]
    panel = build_model_panel(credit, macro, noncurrent)
    after_gap = panel[(panel.bank_id == "1") & (panel.segment == "CRE") & (panel.target_period == pd.Timestamp("2008-09-30"))].iloc[0]
    assert pd.isna(after_gap.lagged_nco_rate)
    assert not after_gap.prediction_eligible


def test_macro_availability_lag_is_not_applied_twice():
    panel = _panel()
    row = panel[(panel.bank_id == "1") & (panel.target_period == pd.Timestamp("2005-09-30"))].iloc[0]
    assert row.lagged_gdp_growth == panel[(panel.bank_id == "1") & (panel.report_date == pd.Timestamp("2005-06-30"))].gdp_growth.iloc[0]


def test_prediction_does_not_require_target_and_unseen_bank_is_explicitly_excluded():
    panel = _panel()
    train = panel[(panel.bank_id != "3") & panel.evaluation_eligible]
    fit = _fit_entity_fe(train, "nco_rate", ["lagged_nco_rate"])
    candidates = panel[panel.bank_id.isin(["1", "3"])].tail(2).copy()
    candidates["nco_rate"] = np.nan
    predicted = _predict_entity_fe(fit, candidates, "nco_rate")
    assert predicted.nco_rate.isna().all()
    assert "3::CRE" not in set(predicted.entity)


def test_ols_matches_hand_calculated_line_and_cluster_se_is_finite():
    x = np.array([[1.0], [2.0], [3.0], [4.0]])
    y = np.array([2.0, 4.0, 6.0, 8.0])
    beta, se, residual = _ols(y, x, np.array(["a", "a", "b", "b"]))
    assert beta[0] == 2.0
    assert np.allclose(residual, 0.0)
    assert np.isfinite(se[0])


def _panel_inputs():
    dates = pd.date_range("2005-03-31", "2013-12-31", freq="QE")
    rows = []
    for bank, effect in [("1", .01), ("2", .02), ("3", .03)]:
        for number, date in enumerate(dates):
            nco = .02 + effect + .001 * number
            rows.append({"bank_id": bank, "segment": "CRE", "report_date": date, "annualized_nco_rate": nco, "total_npl": 10 + number, "exposure": 1000, "total_loans": 5000 + number, "allowance": 5 + number, "allowance_coverage": .01, "tier1_ratio": .1, "loan_growth": .01, "eligible_for_model": 1, "merger_recent_flag": 0, "cre_to_tier1": 2 + int(bank), "cre_share": .2, "lagged_nco": nco - .001, "cert": bank})
    credit = pd.DataFrame(rows)
    macro = pd.DataFrame({"report_date": dates, "gdp_growth": np.linspace(1, 3, len(dates)), "cre_price_growth": np.linspace(-2, 2, len(dates))})
    noncurrent = pd.DataFrame([{"bank_id": bank, "report_date": date, "fdic_noncurrent_loans": 10 + number, "fdic_total_loans": 1000, "fdic_noncurrent_ratio": (10 + number) / 1000} for bank in ["1", "2", "3"] for number, date in enumerate(dates)])
    return credit, macro, noncurrent
