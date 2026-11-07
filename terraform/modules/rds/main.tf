# ─────────────────────────────────────────────────────────────────────────────
# Terraform Module — RDS (PostgreSQL 15)
# Multi-AZ, encrypted, with automated backups and deletion protection.
# ─────────────────────────────────────────────────────────────────────────────

# ── Variables ─────────────────────────────────────────────────────────────────
variable "project_name"        { type = string }
variable "environment"         { type = string }
variable "db_name"             { type = string }
variable "db_username"         { type = string }
variable "db_password"         { type = string; sensitive = true }
variable "instance_class"      { type = string }
variable "subnet_ids"          { type = list(string) }
variable "vpc_id"              { type = string }
variable "ec2_security_group"  { type = string }

# ── DB Subnet Group ───────────────────────────────────────────────────────────
resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  subnet_ids  = var.subnet_ids
  description = "CloudPulse RDS subnet group (private subnets)"

  tags = {
    Name = "${var.project_name}-${var.environment}-db-subnet-group"
  }
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Security group for CloudPulse RDS — allow PostgreSQL from EC2 only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from EC2 application servers"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.ec2_security_group]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  }
}

# ── Parameter Group ───────────────────────────────────────────────────────────
resource "aws_db_parameter_group" "postgres15" {
  name   = "${var.project_name}-${var.environment}-pg15"
  family = "postgres15"

  parameter {
    name  = "log_connections"
    value = "1"
  }
  parameter {
    name  = "log_disconnections"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000" # log queries > 1 s
  }
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-pg15-params"
  }
}

# ── RDS Instance ──────────────────────────────────────────────────────────────
resource "aws_db_instance" "main" {
  identifier = "${var.project_name}-${var.environment}-postgres"

  # Engine
  engine               = "postgres"
  engine_version       = "15.6"
  instance_class       = var.instance_class
  parameter_group_name = aws_db_parameter_group.postgres15.name

  # Storage
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  # Database credentials
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = 5432

  # Networking
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = true

  # Backups & maintenance
  backup_retention_period   = 7
  backup_window             = "03:00-04:00"
  maintenance_window        = "Mon:04:00-Mon:05:00"
  copy_tags_to_snapshot     = true
  final_snapshot_identifier = "${var.project_name}-${var.environment}-final-snapshot"

  # Protection
  deletion_protection = true
  skip_final_snapshot = false

  # Performance Insights
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Enhanced monitoring
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_monitoring.arn

  tags = {
    Name = "${var.project_name}-${var.environment}-postgres"
  }
}

# ── IAM Role for Enhanced Monitoring ─────────────────────────────────────────
resource "aws_iam_role" "rds_monitoring" {
  name = "${var.project_name}-${var.environment}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "rds_endpoint"         { value = aws_db_instance.main.endpoint }
output "rds_port"             { value = aws_db_instance.main.port }
output "rds_security_group"   { value = aws_security_group.rds.id }
output "rds_instance_id"      { value = aws_db_instance.main.id }
