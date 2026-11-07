# ─────────────────────────────────────────────────────────────────────────────
# Terraform Module — EC2
# Provisions 4 CloudPulse application servers with security groups and EIPs.
# ─────────────────────────────────────────────────────────────────────────────

# ── Variables ─────────────────────────────────────────────────────────────────
variable "project_name"  { type = string }
variable "environment"   { type = string }
variable "instance_type" { type = string }
variable "ami"           { type = string }
variable "key_name"      { type = string }
variable "subnet_ids"    { type = list(string) }
variable "vpc_id"        { type = string }

locals {
  server_names = [
    "web-server-01",
    "web-server-02",
    "web-server-03",
    "web-server-04",
  ]
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2-sg"
  description = "Security group for CloudPulse EC2 application servers"
  vpc_id      = var.vpc_id

  # SSH access (restrict to your office/bastion CIDR in production)
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # CloudPulse API
  ingress {
    description = "CloudPulse API"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Prometheus
  ingress {
    description = "Prometheus"
    from_port   = 9090
    to_port     = 9090
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Grafana
  ingress {
    description = "Grafana"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Alertmanager
  ingress {
    description = "Alertmanager"
    from_port   = 9093
    to_port     = 9093
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Unrestricted egress
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ec2-sg"
  }
}

# ── User-Data Script ──────────────────────────────────────────────────────────
locals {
  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    exec > >(tee /var/log/cloudpulse-init.log) 2>&1

    echo "=== Installing Docker ==="
    yum update -y
    amazon-linux-extras install docker -y
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ec2-user

    echo "=== Installing Docker Compose ==="
    curl -SL "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64" \
         -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose

    echo "=== Pulling CloudPulse image ==="
    aws ecr get-login-password --region us-east-1 | \
      docker login --username AWS --password-stdin \
      $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com

    docker pull \
      $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com/cloudpulse:latest

    echo "=== Starting CloudPulse container ==="
    docker run -d \
      --name cloudpulse-api \
      --restart unless-stopped \
      -p 8000:8000 \
      --env-file /etc/cloudpulse/.env \
      $(aws sts get-caller-identity --query Account --output text).dkr.ecr.us-east-1.amazonaws.com/cloudpulse:latest

    echo "=== CloudPulse initialisation complete ==="
  EOF
}

# ── EC2 Instances ─────────────────────────────────────────────────────────────
resource "aws_instance" "servers" {
  count = length(local.server_names)

  ami                    = var.ami
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = var.subnet_ids[count.index % length(var.subnet_ids)]
  vpc_security_group_ids = [aws_security_group.ec2.id]
  user_data              = local.user_data
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    delete_on_termination = true
    encrypted             = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  tags = {
    Name   = "${var.project_name}-${var.environment}-${local.server_names[count.index]}"
    Server = local.server_names[count.index]
  }
}

# ── Elastic IPs ───────────────────────────────────────────────────────────────
resource "aws_eip" "servers" {
  count    = length(aws_instance.servers)
  instance = aws_instance.servers[count.index].id
  domain   = "vpc"

  tags = {
    Name = "${var.project_name}-${var.environment}-${local.server_names[count.index]}-eip"
  }
}

# ── IAM Role for EC2 (ECR pull + CloudWatch logs) ─────────────────────────────
resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-${var.environment}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-${var.environment}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ── Outputs ───────────────────────────────────────────────────────────────────
output "instance_ids"       { value = aws_instance.servers[*].id }
output "public_ips"         { value = aws_eip.servers[*].public_ip }
output "security_group_id"  { value = aws_security_group.ec2.id }
