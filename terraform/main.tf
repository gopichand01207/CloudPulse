# ─────────────────────────────────────────────────────────────────────────────
# Terraform — CloudPulse Main Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "cloudpulse-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "cloudpulse-terraform-locks"
  }
}

# ── Provider ───────────────────────────────────────────────────────────────────
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = "Platform Engineering"
    }
  }
}

# ── Data Sources ───────────────────────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

# ── VPC Module ─────────────────────────────────────────────────────────────────
module "vpc" {
  source = "./modules/vpc"

  project_name       = var.project_name
  environment        = var.environment
  cidr_block         = var.vpc_cidr
  public_subnets     = var.public_subnets
  private_subnets    = var.private_subnets
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

# ── EC2 Module ─────────────────────────────────────────────────────────────────
module "ec2" {
  source = "./modules/ec2"

  project_name    = var.project_name
  environment     = var.environment
  instance_type   = var.ec2_instance_type
  ami             = var.ec2_ami
  key_name        = "${var.project_name}-${var.environment}-key"
  subnet_ids      = module.vpc.public_subnet_ids
  vpc_id          = module.vpc.vpc_id

  depends_on = [module.vpc]
}

# ── RDS Module ─────────────────────────────────────────────────────────────────
module "rds" {
  source = "./modules/rds"

  project_name       = var.project_name
  environment        = var.environment
  db_name            = var.db_name
  db_username        = var.db_username
  db_password        = var.db_password
  instance_class     = var.db_instance_class
  subnet_ids         = module.vpc.private_subnet_ids
  vpc_id             = module.vpc.vpc_id
  ec2_security_group = module.ec2.security_group_id

  depends_on = [module.vpc, module.ec2]
}

# ── ECS Module ─────────────────────────────────────────────────────────────────
module "ecs" {
  source = "./modules/ecs"

  project_name       = var.project_name
  environment        = var.environment
  cluster_name       = "${var.project_name}-cluster"
  task_family        = "${var.project_name}-api"
  service_name       = "${var.project_name}-api-service"
  container_image    = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.project_name}:latest"
  container_port     = 8000
  desired_count      = 2
  subnet_ids         = module.vpc.private_subnet_ids
  vpc_id             = module.vpc.vpc_id
  aws_region         = var.aws_region
  database_url       = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${module.rds.rds_endpoint}/${var.db_name}"

  depends_on = [module.rds]
}
