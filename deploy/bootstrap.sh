#!/usr/bin/env bash
# F11 one-time infra setup. Already run against account 540646170532 on
# 2026-08-16 — this script documents exactly what was created (for
# disaster recovery / a second reviewer to reproduce), it is not meant
# to be re-run against the live deployment. Re-running create-* calls
# against existing resources will error; that's intentional, not a bug.
#
# Design decisions baked into these commands (see deployments.md for the
# full record):
#   - Default VPCs / public subnets in both regions, assignPublicIp=ENABLED
#     on every task — no NAT gateway (cost-floor constraint; both regions'
#     default subnets already have an internet gateway).
#   - Worker control port (8100) open 0.0.0.0/0, auth is the shared-secret
#     header in control.py, not network scoping — cross-region reachability
#     without VPC peering has no narrower option in the time available.
#     Documented tradeoff, not an oversight.
#   - initProcessEnabled=true on worker tasks only: without it, the worker
#     process is PID 1 in its own PID namespace, and Linux suppresses the
#     default SIGKILL action for a self-directed kill from PID 1 — found
#     by testing the container locally, not by inspection. The arena
#     never self-kills, so it doesn't need this.
#   - 0.25 vCPU / 1024 MB per task, not the 512MB floor: measured via
#     `docker stats` against the real image (sentence-transformers model
#     loaded) at ~470-525MB per service; 512MB would OOM-kill under normal
#     operation, indistinguishable from the demo's own kill button.
set -euo pipefail
cd "$(dirname "$0")/.."

ACCOUNT_ID="540646170532"
USE1_VPC="vpc-0afe12308e9e44eb3"
EUC1_VPC="vpc-00b38a8c356748be5"
USE1_SUBNETS="subnet-01f2e30747435b7cd,subnet-04c03d504fcbf88ed"
EUC1_SUBNETS="subnet-04b049311f1053265,subnet-0fee5f0096d2167e6"

echo "==> ECR repos"
aws ecr create-repository --repository-name ninelives --region us-east-1 --image-scanning-configuration scanOnPush=true
aws ecr create-repository --repository-name ninelives --region eu-central-1 --image-scanning-configuration scanOnPush=true

echo "==> SSM parameters (SecureString, per-region — task defs reference same-region ARNs only)"
for REGION in us-east-1 eu-central-1; do
  aws ssm put-parameter --region "$REGION" --name "/ninelives/DATABASE_URL" --value "$DATABASE_URL" --type SecureString --overwrite
  aws ssm put-parameter --region "$REGION" --name "/ninelives/ANTHROPIC_API_KEY" --value "$ANTHROPIC_API_KEY" --type SecureString --overwrite
  aws ssm put-parameter --region "$REGION" --name "/ninelives/CONTROL_SHARED_SECRET" --value "$CONTROL_SHARED_SECRET" --type SecureString --overwrite
done

echo "==> IAM execution role (ECR pull, CloudWatch Logs incl. CreateLogGroup, SSM read scoped to /ninelives/*)"
aws iam create-role --role-name ninelivesTaskExecutionRole --assume-role-policy-document file://deploy/trust-policy.json
aws iam attach-role-policy --role-name ninelivesTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name ninelivesTaskExecutionRole --policy-name ninelives-ssm-access --policy-document file://deploy/ssm-access-policy.json
aws iam put-role-policy --role-name ninelivesTaskExecutionRole --policy-name ninelives-logs-create-group --policy-document file://deploy/logs-create-group-policy.json

echo "==> log groups (execution role can write to these but not auto-create them without the policy above)"
aws logs create-log-group --region us-east-1 --log-group-name /ecs/ninelives-arena
aws logs create-log-group --region us-east-1 --log-group-name /ecs/ninelives-worker-us-east-1
aws logs create-log-group --region eu-central-1 --log-group-name /ecs/ninelives-worker-eu-central-1

echo "==> ECS clusters (one per region)"
aws ecs create-cluster --cluster-name ninelives --region us-east-1
aws ecs create-cluster --cluster-name ninelives --region eu-central-1

echo "==> security groups"
ALB_SG=$(aws ec2 create-security-group --region us-east-1 --group-name ninelives-alb-sg --description "ninelives ALB - public HTTP" --vpc-id "$USE1_VPC" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id "$ALB_SG" --protocol tcp --port 80 --cidr 0.0.0.0/0

ARENA_SG=$(aws ec2 create-security-group --region us-east-1 --group-name ninelives-arena-sg --description "ninelives arena task - from ALB only" --vpc-id "$USE1_VPC" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id "$ARENA_SG" --protocol tcp --port 8000 --source-group "$ALB_SG"

WORKER_SG_USE1=$(aws ec2 create-security-group --region us-east-1 --group-name ninelives-worker-sg --description "ninelives worker - control port (secret-gated)" --vpc-id "$USE1_VPC" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --region us-east-1 --group-id "$WORKER_SG_USE1" --protocol tcp --port 8100 --cidr 0.0.0.0/0

WORKER_SG_EUC1=$(aws ec2 create-security-group --region eu-central-1 --group-name ninelives-worker-sg --description "ninelives worker - control port (secret-gated)" --vpc-id "$EUC1_VPC" --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --region eu-central-1 --group-id "$WORKER_SG_EUC1" --protocol tcp --port 8100 --cidr 0.0.0.0/0

echo "==> ALB + target group + listener (arena only, us-east-1)"
ALB_ARN=$(aws elbv2 create-load-balancer --region us-east-1 --name ninelives-arena --subnets $(echo $USE1_SUBNETS | tr ',' ' ') --security-groups "$ALB_SG" --scheme internet-facing --type application --query 'LoadBalancers[0].LoadBalancerArn' --output text)
TG_ARN=$(aws elbv2 create-target-group --region us-east-1 --name ninelives-arena-tg --protocol HTTP --port 8000 --vpc-id "$USE1_VPC" --target-type ip --health-check-path "/" --health-check-interval-seconds 15 --healthy-threshold-count 2 --unhealthy-threshold-count 3 --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 create-listener --region us-east-1 --load-balancer-arn "$ALB_ARN" --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn="$TG_ARN"

echo "==> build + push (see deploy.sh; run it now before registering task defs that reference :latest)"
./deploy/deploy.sh || true  # first run: services don't exist yet, update-service calls will fail harmlessly

echo "==> register task definitions"
aws ecs register-task-definition --region us-east-1 --cli-input-json file://deploy/task-def-arena.json
aws ecs register-task-definition --region us-east-1 --cli-input-json file://deploy/task-def-worker-us-east-1.json
aws ecs register-task-definition --region eu-central-1 --cli-input-json file://deploy/task-def-worker-eu-central-1.json

echo "==> create services"
aws ecs create-service --region us-east-1 --cluster ninelives --service-name ninelives-arena --task-definition ninelives-arena --desired-count 1 --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$USE1_SUBNETS],securityGroups=[$ARENA_SG],assignPublicIp=ENABLED}" --load-balancers "targetGroupArn=$TG_ARN,containerName=arena,containerPort=8000"
aws ecs create-service --region us-east-1 --cluster ninelives --service-name ninelives-worker-us-east-1 --task-definition ninelives-worker-us-east-1 --desired-count 1 --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$USE1_SUBNETS],securityGroups=[$WORKER_SG_USE1],assignPublicIp=ENABLED}"
aws ecs create-service --region eu-central-1 --cluster ninelives --service-name ninelives-worker-eu-central-1 --task-definition ninelives-worker-eu-central-1 --desired-count 1 --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[$EUC1_SUBNETS],securityGroups=[$WORKER_SG_EUC1],assignPublicIp=ENABLED}"

echo "==> demo URL:"
aws elbv2 describe-load-balancers --region us-east-1 --load-balancer-arns "$ALB_ARN" --query 'LoadBalancers[0].DNSName' --output text
