from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankstress.artifacts import validate_artifact_metadata
from bankstress.eda import write_eda
from bankstress.io.fdic_financials import download_noncurrent_panel
from bankstress.macro import build_macro_panel
from bankstress.modeling import build_model_panel, run_cre_interaction, run_oos_models, run_split_panel_jackknife


def main() -> None:
    validate_artifact_metadata(ROOT / "data" / "derived" / "credit_panel.parquet")
    credit_path = ROOT / "data" / "derived" / "credit_panel.parquet"
    try:
        if not credit_path.exists():
            raise FileNotFoundError("Batch 2 requires data/derived/credit_panel.parquet. Run the completed Batch 1 pipeline to recreate this ignored input.")
        credit = pd.read_parquet(credit_path)
        macro = build_macro_panel(ROOT, credit["report_date"])
        noncurrent = download_noncurrent_panel(ROOT, credit["cert"])
        model = build_model_panel(credit, macro, noncurrent)
        model.to_parquet(ROOT / "data" / "derived" / "model_panel.parquet", index=False)
        write_eda(model, ROOT)
        eligible, metrics, _ = run_oos_models(model, ROOT)
        run_split_panel_jackknife(eligible, ROOT)
        realized_shock = pd.read_parquet(ROOT / "data" / "derived" / "cre_realized_shock.parquet")
        run_cre_interaction(model, realized_shock, ROOT)
        (ROOT / "outputs" / "models" / "run_summary.md").write_text(
            "# Batch 2 successful run\n\n"
            f"- Credit-panel rows: {len(credit):,}\n"
            f"- Macro rows: {len(macro):,}\n"
            f"- Model-panel rows: {len(model):,}\n"
            f"- Unified OOS eligible rows: {len(eligible):,}\n"
            "- FFIEC recovery provenance: `data/manifests/ffiec_recovery_manifest.csv`\n"
            "- FDIC noncurrent-loan provenance: `metadata/fdic_noncurrent_manifest.csv`\n"
            "- Macro provenance: `metadata/macro_download_manifest.csv`\n",
            encoding="utf-8",
        )
    except Exception as error:
        log_dir = ROOT / "outputs" / "models"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "run_failures.log").write_text(f"Batch 2 run failed: {type(error).__name__}: {error}\n", encoding="utf-8")
        raise
    print(f"macro rows={len(macro)} model rows={len(model)} eligible rows={len(eligible)} metrics={len(metrics)}")


if __name__ == "__main__":
    main()
