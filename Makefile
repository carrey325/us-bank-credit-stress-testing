.DEFAULT_GOAL := test

test:
	python -m pytest -q

pilot:
	python scripts/run_batch1.py --pilot

full:
	python scripts/run_batch1.py --full
