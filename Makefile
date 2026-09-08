.DEFAULT_GOAL := verify
.PHONY: verify test figures download pilot stress report

verify:
	python scripts/export_results.py --verify

test:
	python -m pytest -q -p no:cacheprovider

figures:
	python scripts/plot_results.py

download:
	python scripts/download_call_reports.py

pilot:
	python scripts/collect_data.py --pilot

# Require validated historical inputs; see docs/reproduction.md.
stress:
	python scripts/run_stress.py

report:
	python scripts/build_report.py
