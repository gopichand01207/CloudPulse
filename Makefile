# ──────────────────────────────────────────────────────────────────────────────
# CloudPulse — Makefile
# ──────────────────────────────────────────────────────────────────────────────
# Requires: Docker Compose v2 (docker compose), Python 3.11+, Terraform 1.6+
# Usage:    make <target>
# ──────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
.PHONY: help up down restart logs shell test test-cov lint fmt migrate \
        terraform-init terraform-plan terraform-apply terraform-destroy clean

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD   := \033[1m
RESET  := \033[0m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m

# ── Variables (override on CLI: make up COMPOSE_FILE=docker-compose.prod.yml)
COMPOSE_FILE   ?= docker-compose.yml
API_SERVICE    ?= cloudpulse-api
TF_DIR         ?= terraform
TF_VAR_FILE    ?= terraform.tfvars
DB_PASSWORD    ?= changeme

# ──────────────────────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  $(BOLD)$(CYAN)CloudPulse — Makefile Targets$(RESET)"
	@echo ""
	@echo "  $(BOLD)Docker$(RESET)"
	@echo "    $(GREEN)up$(RESET)                Start all services in the background"
	@echo "    $(GREEN)down$(RESET)              Stop and remove containers"
	@echo "    $(GREEN)restart$(RESET)           Restart the API service"
	@echo "    $(GREEN)logs$(RESET)              Tail logs for cloudpulse-api"
	@echo "    $(GREEN)shell$(RESET)             Open a bash shell in the API container"
	@echo ""
	@echo "  $(BOLD)Database$(RESET)"
	@echo "    $(GREEN)migrate$(RESET)           Run DB initialisation script inside the container"
	@echo ""
	@echo "  $(BOLD)Testing$(RESET)"
	@echo "    $(GREEN)test$(RESET)              Run the full pytest suite"
	@echo "    $(GREEN)test-cov$(RESET)          Run tests with HTML coverage report"
	@echo ""
	@echo "  $(BOLD)Code quality$(RESET)"
	@echo "    $(GREEN)lint$(RESET)              Run ruff linter"
	@echo "    $(GREEN)fmt$(RESET)               Format code with black + isort"
	@echo ""
	@echo "  $(BOLD)Terraform$(RESET)"
	@echo "    $(GREEN)terraform-init$(RESET)    Initialise Terraform providers"
	@echo "    $(GREEN)terraform-plan$(RESET)    Preview infrastructure changes"
	@echo "    $(GREEN)terraform-apply$(RESET)   Apply infrastructure changes"
	@echo "    $(GREEN)terraform-destroy$(RESET) Destroy all AWS resources"
	@echo ""
	@echo "  $(BOLD)Misc$(RESET)"
	@echo "    $(GREEN)clean$(RESET)             Remove caches and build artefacts"
	@echo ""

# ──────────────────────────────────────────────────────────────────────────────
# Docker Compose
# ──────────────────────────────────────────────────────────────────────────────

## Start all services in detached mode
up:
	@echo "$(YELLOW)▶ Starting CloudPulse services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)✔ Services started$(RESET)"
	@echo "  API     → http://localhost:8000"
	@echo "  Docs    → http://localhost:8000/docs"
	@echo "  Grafana → http://localhost:3000  (admin/admin)"
	@echo "  Prometheus → http://localhost:9090"

## Stop and remove all containers (preserves volumes)
down:
	@echo "$(YELLOW)▶ Stopping CloudPulse services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) down
	@echo "$(GREEN)✔ Services stopped$(RESET)"

## Restart the API container
restart:
	@echo "$(YELLOW)▶ Restarting $(API_SERVICE)...$(RESET)"
	docker compose -f $(COMPOSE_FILE) restart $(API_SERVICE)
	@echo "$(GREEN)✔ Restarted$(RESET)"

## Follow log output for the API container
logs:
	docker compose -f $(COMPOSE_FILE) logs -f $(API_SERVICE)

## Open an interactive shell inside the API container
shell:
	docker compose -f $(COMPOSE_FILE) exec $(API_SERVICE) /bin/bash

# ──────────────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────────────

## Initialise the database (creates tables, runs seed data)
migrate:
	@echo "$(YELLOW)▶ Running database initialisation...$(RESET)"
	docker compose -f $(COMPOSE_FILE) exec $(API_SERVICE) python scripts/init_db.py
	@echo "$(GREEN)✔ Database initialised$(RESET)"

# ──────────────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────────────

## Run the full pytest suite
test:
	@echo "$(YELLOW)▶ Running tests...$(RESET)"
	pytest tests/ -v --asyncio-mode=auto
	@echo "$(GREEN)✔ Tests complete$(RESET)"

## Run tests with HTML coverage report (opens htmlcov/index.html)
test-cov:
	@echo "$(YELLOW)▶ Running tests with coverage...$(RESET)"
	pytest tests/ -v --asyncio-mode=auto \
		--cov=api --cov=alerting --cov=logging \
		--cov-report=html --cov-report=term-missing
	@echo "$(GREEN)✔ Coverage report saved to htmlcov/$(RESET)"

# ──────────────────────────────────────────────────────────────────────────────
# Code quality
# ──────────────────────────────────────────────────────────────────────────────

## Run ruff linter (fast, checks everything)
lint:
	@echo "$(YELLOW)▶ Linting with ruff...$(RESET)"
	ruff check .
	@echo "$(GREEN)✔ Lint passed$(RESET)"

## Format code with black and isort
fmt:
	@echo "$(YELLOW)▶ Formatting with black...$(RESET)"
	black .
	@echo "$(YELLOW)▶ Sorting imports with isort...$(RESET)"
	isort .
	@echo "$(GREEN)✔ Formatting complete$(RESET)"

# ──────────────────────────────────────────────────────────────────────────────
# Terraform
# ──────────────────────────────────────────────────────────────────────────────

## Initialise Terraform working directory and download providers
terraform-init:
	@echo "$(YELLOW)▶ Initialising Terraform...$(RESET)"
	cd $(TF_DIR) && terraform init
	@echo "$(GREEN)✔ Terraform initialised$(RESET)"

## Show planned infrastructure changes
terraform-plan:
	@echo "$(YELLOW)▶ Running Terraform plan...$(RESET)"
	cd $(TF_DIR) && terraform plan -var="db_password=$(DB_PASSWORD)"

## Apply infrastructure changes (creates/updates AWS resources)
terraform-apply:
	@echo "$(YELLOW)▶ Applying Terraform changes...$(RESET)"
	cd $(TF_DIR) && terraform apply -var="db_password=$(DB_PASSWORD)"
	@echo "$(GREEN)✔ Infrastructure applied$(RESET)"

## Destroy all Terraform-managed AWS resources
terraform-destroy:
	@echo "$(YELLOW)▶ Destroying Terraform resources...$(RESET)"
	cd $(TF_DIR) && terraform destroy -var="db_password=$(DB_PASSWORD)"
	@echo "$(GREEN)✔ Infrastructure destroyed$(RESET)"

# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

## Remove Python caches, test artefacts and build output
clean:
	@echo "$(YELLOW)▶ Cleaning up...$(RESET)"
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache"   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov"       -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info"    -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist"          -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build"         -exec rm -rf {} + 2>/dev/null || true
	find . -name ".coverage"             -delete 2>/dev/null || true
	@echo "$(GREEN)✔ Clean complete$(RESET)"
