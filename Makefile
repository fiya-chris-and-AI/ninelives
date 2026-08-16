.PHONY: setup demo-reset worker standby ephemeral verify arena seed-memories deploy demo-url

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

seed-memories:
	uv run python scripts/seed_memories.py

arena:
	uv run uvicorn arena:app --host 0.0.0.0 --port 8000

deploy:
	./deploy/deploy.sh

demo-url:
	@aws elbv2 describe-load-balancers --region us-east-1 --names ninelives-arena --query 'LoadBalancers[0].DNSName' --output text
