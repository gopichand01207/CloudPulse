# ─────────────────────────────────────────────────────────────────────────────
# Terraform — CloudPulse Outputs
# ─────────────────────────────────────────────────────────────────────────────

# ── VPC ───────────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "The ID of the CloudPulse VPC."
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "List of IDs for public subnets."
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "List of IDs for private subnets."
  value       = module.vpc.private_subnet_ids
}

# ── EC2 ───────────────────────────────────────────────────────────────────────
output "ec2_instance_ids" {
  description = "List of EC2 instance IDs for CloudPulse application servers."
  value       = module.ec2.instance_ids
}

output "ec2_public_ips" {
  description = "Elastic IP addresses attached to each EC2 instance."
  value       = module.ec2.public_ips
}

output "ec2_security_group_id" {
  description = "Security group ID attached to EC2 instances."
  value       = module.ec2.security_group_id
}

# ── RDS ───────────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "Connection endpoint for the RDS PostgreSQL instance."
  value       = module.rds.rds_endpoint
  sensitive   = false
}

output "rds_port" {
  description = "Port the RDS instance listens on (default 5432)."
  value       = module.rds.rds_port
}

# ── ECS ───────────────────────────────────────────────────────────────────────
output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster running the CloudPulse API."
  value       = module.ecs.cluster_arn
}

output "ecs_service_name" {
  description = "Name of the ECS service managing CloudPulse API tasks."
  value       = module.ecs.service_name
}

output "ecs_task_definition_arn" {
  description = "ARN of the latest active ECS task definition."
  value       = module.ecs.task_definition_arn
}

# ── Application URL ───────────────────────────────────────────────────────────
output "cloudpulse_api_url" {
  description = "Public URL of the CloudPulse API (via EC2 Elastic IP)."
  value       = "http://${module.ec2.public_ips[0]}:8000"
}

output "grafana_url" {
  description = "Grafana dashboard URL."
  value       = "http://${module.ec2.public_ips[0]}:3000"
}

output "prometheus_url" {
  description = "Prometheus web UI URL."
  value       = "http://${module.ec2.public_ips[0]}:9090"
}
