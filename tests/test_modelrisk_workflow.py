import numpy as np
import pandas as pd
import pytest


def test_macro_centers_reject_missing_quarter_and_nonofficial_scenario():
    from bankstress.modelrisk.stochastic_workflow import official_centers
    data = pd.DataFrame({'scenario': ['baseline'] * 8,
                         'quarter': pd.date_range('2026-03-31', periods=8, freq='QE')})
    with pytest.raises(ValueError, match='nine'):
        official_centers(data)


def test_path_export_reconciles_banks_quarters_and_losses(tmp_path):
    from bankstress.modelrisk.stochastic_workflow import write_paths
    rates = np.array([[[.04, -.04], [.08, .04]], [[.12, .08], [.16, .12]]])
    jump = pd.DataFrame({'bank_id': ['a', 'b'], 'exposure': [400., 800.]})
    quarters = pd.date_range('2026-03-31', periods=2, freq='QE')
    path = tmp_path / 'paths.parquet'
    write_paths(path, rates, jump, quarters)
    saved = pd.read_parquet(path)
    assert len(saved) == 8
    totals = saved.groupby('path_id').quarter_loss_thousands.sum()
    assert totals.tolist() == pytest.approx([20., 68.])
    assert saved.query("bank_id == 'b' and path_id == 0").raw_nco_rate.tolist() == [-.04, .04]
