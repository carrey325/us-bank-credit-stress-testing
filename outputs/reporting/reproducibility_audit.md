# Batch 5 reproducibility audit

Status: **PASS**

## Checks

- PASS: required_final_tables_exist
- PASS: required_final_table_schemas_and_semantics
- PASS: required_final_figures_exist
- PASS: required_final_figure_semantics
- PASS: model_panel_retains_missing_nco
- PASS: ytd_quarterization_regression_check
- PASS: field_mapping_has_effective_dates
- PASS: merger_quarters_are_recorded
- PASS: macro_release_calendar_has_no_future_observation
- PASS: panel_forecast_origins_precede_outcomes
- PASS: oos_windows_preserve_time_order_without_shuffle
- PASS: conformal_has_strict_time_order
- PASS: bayesian_diagnostics_saved
- PASS: stress_totals_reconcile_to_paths
- PASS: final_tables_are_rebuilt_from_approved_outputs
- PASS: final_t1_matches_generated_panel_scope
- PASS: market_validation_not_fabricated
- PASS: quantile_uses_pinball_not_rmse_for_tail_scoring
- PASS: cre_specification_record_is_present
- PASS: resume_metrics_match_generated_scope
- PASS: final_report_has_ten_pages_and_required_positioning
- PASS: readme_states_final_delivery_and_model_positioning

## Carry-forward limitations

- One source reconciliation item remains REVIEW_REQUIRED; it is not reclassified.
- Some macro features use documented final-vintage fallback lags rather than a complete real-time vintage feed.
- Bayesian posterior forecasts are unavailable under the documented environment fallback.
- Recursive CRE Q0.90 is not historically calibrated across all pre-specified pseudo-stress windows.
- Mortgage stress attribution is unavailable because no approved mortgage stress model exists.
- Market validation is not completed because no verified legal-entity-to-parent-to-ticker mapping is available.
