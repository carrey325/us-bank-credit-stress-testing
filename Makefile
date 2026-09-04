.DEFAULT_GOAL := test

test:
	python -m pytest -q

pilot:
	python scripts/run_batch1.py --pilot

full:
	python scripts/run_batch1.py --full

# Reproducible end-to-end checkpoints. Raw FFIEC files remain manifest-backed
# local inputs and are intentionally not committed.
raw:
	python scripts/run_batch1.py --full

standard:
	python scripts/run_batch1.py --full

panel:
	python scripts/run_batch2.py

qa:
	python -m pytest -q tests/test_flows.py tests/test_panel.py tests/test_qa.py

models:
	python scripts/run_batch3.py

stress:
	python scripts/run_batch4.py

report:
	python scripts/run_batch5.py
