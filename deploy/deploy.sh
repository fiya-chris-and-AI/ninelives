#!/usr/bin/env bash
# F11: build → push → redeploy. Run from the ninelives/ directory (or via
# `make deploy`). Assumes bootstrap.sh has already been run once (ECR
# repos, ECS clusters/services, ALB, IAM role, SSM parameters, security
# groups all exist — see bootstrap.sh for that one-time setup and why
# each piece is shaped the way it is).
set -euo pipefail
cd "$(dirname "$0")/.."

ACCOUNT_ID="540646170532"
IMAGE_TAG="${1:-latest}"

echo "==> building image (linux/amd64, CPU-only torch, model baked in)"
docker build --platform linux/amd64 -t ninelives:local -f Dockerfile .

for REGION in us-east-1 eu-central-1; do
  REPO="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/ninelives"
  echo "==> pushing to $REGION"
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
  docker tag ninelives:local "$REPO:$IMAGE_TAG"
  docker push "$REPO:$IMAGE_TAG"
done

echo "==> forcing new deployments (picks up the freshly pushed image)"
aws ecs update-service --region us-east-1 --cluster ninelives --service ninelives-arena --force-new-deployment > /dev/null
aws ecs update-service --region us-east-1 --cluster ninelives --service ninelives-worker-us-east-1 --force-new-deployment > /dev/null
aws ecs update-service --region eu-central-1 --cluster ninelives --service ninelives-worker-eu-central-1 --force-new-deployment > /dev/null

ALB_DNS=$(aws elbv2 describe-load-balancers --region us-east-1 --names ninelives-arena --query 'LoadBalancers[0].DNSName' --output text)
echo "==> deploy triggered. demo URL: http://$ALB_DNS/"
echo "==> waiting for arena to reach steady state..."
aws ecs wait services-stable --region us-east-1 --cluster ninelives --services ninelives-arena

echo "==> cold curl check"
curl -sf -o /dev/null -w "GET / -> %{http_code}\n" "http://$ALB_DNS/"
