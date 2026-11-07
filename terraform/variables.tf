# ─────────────────────────────────────────────────────────────────────────────
# Terraform — CloudPulse Variable Definitions
# ─────────────────────────────────────────────────────────────────────────────

# ── AWS Configuration ──────────────────────────────────────────────────────────
variable "aws_region" {
  description = "AWS region where all resources will be created."
  type        = string
  default     = "us-east-1"
}

# ── Project Metadata ──────────────────────────────────────────────────────────
variable "environment" {
  description = "Deployment environment (production, staging, development)."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "environment must be one of: production, staging, development."
  }
}

variable "project_name" {
  description = "Name of the project; used as a prefix for all resource names."
  type        = string
  default     = "cloudpulse"
}

# ── EC2 ───────────────────────────────────────────────────────────────────────
variable "ec2_instance_type" {
  description = "EC2 instance type for the CloudPulse application servers."
  type        = string
  default     = "t3.medium"
}

variable "ec2_ami" {
  description = "Amazon Machine Image (AMI) ID for EC2 instances. Default is Amazon Linux 2 in us-east-1."
  type        = string
  default     = "ami-0c02fb55956c7d316" # Amazon Linux 2 (us-east-1)
}

# ── RDS (PostgreSQL) ──────────────────────────────────────────────────────────
variable "db_instance_class" {
  description = "RDS instance class for the PostgreSQL database."
  type        = string
  default     = "db.t3.micro"
}

variable "db_name" {
  description = "Name of the PostgreSQL database to create."
  type        = string
  default     = "cloudpulse"
}

variable "db_username" {
  description = "Master username for the PostgreSQL RDS instance."
  type        = string
  default     = "cloudpulse_admin"
}

variable "db_password" {
  description = "Master password for the PostgreSQL RDS instance. Must be at least 16 characters."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.db_password) >= 16
    error_message = "db_password must be at least 16 characters long."
  }
}

# ── Networking ────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the CloudPulse VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnets" {
  description = "List of CIDR blocks for public subnets (one per AZ)."
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnets" {
  description = "List of CIDR blocks for private subnets (one per AZ)."
  type        = list(string)
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
}
