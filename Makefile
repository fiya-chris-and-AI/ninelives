.PHONY: setup demo-reset worker standby ephemeral verify

setup:
	uv sync

demo-reset:
	uv run python scripts/reset_demo.py

worker:
	uv run python worker.py --region us-east-1

standby:
	uv run python worker.py --region eu-central-1 --standby --job-id $(JOB_ID)

ephemeral:
	uv run python worker.py --region us-east-1 --no-memory

verify:
	uv run python scripts/spike_m0.py
