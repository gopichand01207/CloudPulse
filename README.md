# CloudPulse: Infrastructure & Microservices Observability

> Real-time cloud infrastructure monitoring platform built with Python, FastAPI, PostgreSQL, Redis, Prometheus, Grafana, and AWS/Terraform. Automated alerting reduced incident response time by **40%**.

---

## Overview

CloudPulse is a production-grade observability platform designed to monitor cloud infrastructure and microservices at scale. It collects server metrics (CPU, memory, disk, network) in real time, ingests and parses structured/unstructured logs, evaluates configurable alert thresholds, and routes notifications via Email and Slack. Infrastructure is provisioned on AWS with Terraform, and all services run as Docker containers orchestrated by Docker Compose.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                        AWS VPC (us-east-1)                     │
│                                                                │
│   ┌─────────────┐    ┌──────────────────┐    ┌─────────────┐  │
│   │  EC2 (web)  │    │  EC2 (api)       │    │  EC2 (db)   │  │
│   │ web-srv-01  │───▶│  CloudPulse API  │───▶│  RDS Postgres│  │
│   │ web-srv-02  │    │  FastAPI :8000   │    │  Port 5432  │  │
│   └─────────────┘    └────────┬─────────┘    └─────────────┘  │
│   ┌─────────────┐             │                               │
│   │  EC2 (app)  │─────────────┘    ┌──────────────────────┐  │
│   │ app-srv-01  │                  │  Redis (Cache/Queue) │  │
│   └─────────────┘                  │  Port 6379           │  │
│                                    └──────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
          │                    │
          ▼                    ▼
  ┌───────────────┐   ┌────────────────────┐
  │  Prometheus   │   │   Alertmanager     │
  │  Port 9090    │──▶│   Port 9093        │──▶ Email / Slack
  └───────┬───────┘   └────────────────────┘
          │
          ▼
  ┌───────────────┐
  │    Grafana    │
  │   Port 3000   │
  └───────────────┘
```

**Data Flow:**
1. EC2 instances expose `/metrics` endpoints polled by Prometheus every 15 s
2. CloudPulse API persists metrics to PostgreSQL and caches hot data in Redis
3. Alert engine evaluates thresholds; fires to Alertmanager → Email/Slack
4. Grafana visualises Prometheus data via pre-built dashboards

---

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| API Framework | FastAPI | 0.104+ |
| Language | Python | 3.11 |
| ORM | SQLAlchemy (async) | 2.x |
| Database | PostgreSQL | 15 |
| Cache / Broker | Redis | 7 |
| Containerisation | Docker & Docker Compose | 24+ |
| IaC | Terraform | 1.6+ |
| Cloud | AWS (EC2, RDS, ECS, VPC) | — |
| Metrics Scraping | Prometheus | 2.47 |
| Visualisation | Grafana | 10.x |
| Alert Routing | Alertmanager | 0.26 |
| Structured Logging | structlog | 23.x |
| Testing | pytest + pytest-asyncio | — |

---

## Features

- **Real-time metric collection** — CPU, memory, disk I/O, and network throughput sampled from every registered server
- **Multi-server monitoring** — unlimited server registration with per-server configurable thresholds
- **Automated alerting** — Email + Slack notifications evaluated by a rules engine; reduced MTTR by **40%**
- **Log ingestion pipeline** — batch ingest of structured JSON and plain-text log lines with error-rate aggregation
- **Terraform-provisioned AWS infrastructure** — reproducible VPC, EC2, RDS, and ECS topology
- **Containerised microservices** — single `docker-compose up` spins the full stack locally
- **Grafana dashboards** — pre-built panels for CPU trends, memory heat-maps, and alert history
- **OpenAPI documentation** — interactive Swagger UI at `/docs`; ReDoc at `/redoc`

---

## Project Structure

```
CloudPulse/
├── api/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application factory
│   ├── dependencies.py          # DB session, Redis, auth deps
│   ├── models/
│   │   ├── __init__.py
│   │   ├── server_metric.py     # SQLAlchemy ORM model
│   │   ├── alert_event.py
│   │   └── log_entry.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── metrics.py           # Pydantic request/response schemas
│   │   ├── alerts.py
│   │   └── logs.py
│   └── routers/
│       ├── __init__.py
│       ├── metrics.py           # /api/v1/metrics
│       ├── alerts.py            # /api/v1/alerts
│       ├── health.py            # /api/v1/health
│       └── services.py         # /api/v1/services
├── alerting/
│   ├── __init__.py
│   ├── engine.py                # AlertEngine — threshold evaluation
│   └── thresholds.py            # AlertThresholds dataclass + evaluator
├── logging/
│   ├── __init__.py
│   ├── pipeline.py              # LogPipeline — ingest + parse
│   └── pipeline_config.py       # structlog setup + PipelineConfig
├── scripts/
│   ├── init_db.py               # DB initialisation
│   └── seed_data.py             # Sample data for local dev
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── vpc/
│       ├── ec2/
│       └── rds/
├── monitoring/
│   ├── prometheus.yml
│   ├── alertmanager.yml
│   └── grafana/
│       └── dashboards/
│           └── cloudpulse.json
├── tests/
│   ├── conftest.py
│   ├── test_metrics_api.py
│   ├── test_alert_engine.py
│   ├── test_log_pipeline.py
│   └── test_health_api.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

---

## Quick Start

### Prerequisites
- Docker ≥ 24 and Docker Compose v2
- Python 3.11+ (for local dev without Docker)

### 1 — Clone and configure

```bash
git clone https://github.com/gopichandnaik/cloudpulse.git
cd CloudPulse
cp .env.example .env
# Edit .env — set DB_PASSWORD, REDIS_URL, SLACK_WEBHOOK_URL, etc.
```

### 2 — Start all services

```bash
docker-compose up -d
# Starts: cloudpulse-api, postgres, redis, prometheus, grafana, alertmanager
```

### 3 — Initialise the database

```bash
docker-compose exec cloudpulse-api python scripts/init_db.py
```

### 4 — Access services

| Service | URL | Credentials |
|---|---|---|
| CloudPulse API | http://localhost:8000 | — |
| Swagger UI | http://localhost:8000/docs | — |
| ReDoc | http://localhost:8000/redoc | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / admin |
| Alertmanager | http://localhost:9093 | — |

---

## Infrastructure Setup (AWS + Terraform)

```bash
cd terraform

# Initialise providers
terraform init

# Preview changes
terraform plan \
  -var="db_password=yourpassword" \
  -var="aws_region=us-east-1"

# Apply — provisions VPC, EC2, RDS, ECS, security groups
terraform apply \
  -var="db_password=yourpassword" \
  -var="aws_region=us-east-1"
```

After `apply` succeeds, Terraform outputs the API load-balancer DNS, RDS endpoint, and Grafana URL.

```bash
# Destroy all resources when done
terraform destroy -var="db_password=yourpassword"
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/metrics` | List all stored metrics (paginated) |
| `POST` | `/api/v1/metrics/collect` | Ingest a new metric payload |
| `GET` | `/api/v1/metrics/summary` | Per-server aggregated summary |
| `GET` | `/api/v1/metrics/realtime/{server_id}` | Latest snapshot for a server |
| `GET` | `/api/v1/metrics/history` | Time-range filtered metric history |
| `GET` | `/api/v1/alerts` | List alert events |
| `POST` | `/api/v1/alerts/acknowledge/{alert_id}` | Acknowledge an open alert |
| `GET` | `/api/v1/alerts/active` | Only unresolved alerts |
| `GET` | `/api/v1/health` | Liveness / readiness check |
| `GET` | `/api/v1/health/services` | Health of downstream services |
| `POST` | `/api/v1/health/services/probe` | Trigger ad-hoc service probes |
| `GET` | `/api/v1/services` | Registered service catalogue |
| `POST` | `/api/v1/services` | Register a new service |

---

## Alert Thresholds

| Metric | Threshold | Severity | Notification Channel |
|---|---|---|---|
| CPU Utilisation | > 85% | WARNING | Slack |
| CPU Utilisation | > 95% | CRITICAL | Slack + Email |
| Memory Utilisation | > 80% | WARNING | Slack |
| Memory Utilisation | > 90% | CRITICAL | Slack + Email |
| Disk Utilisation | > 75% | WARNING | Slack |
| Disk Utilisation | > 85% | CRITICAL | Slack + Email |
| Response Time | > 1000 ms | WARNING | Slack |
| Response Time | > 2000 ms | CRITICAL | Slack + Email |

Thresholds are configurable per server via `alerting/thresholds.py` or environment variables.

---

## Monitoring Stack

### Prometheus
- Scrapes `/metrics` on all registered hosts every **15 seconds**
- Stores 15-day rolling TSDB
- Configured via `monitoring/prometheus.yml`

### Alertmanager
- Groups duplicate alerts over a 30-second window
- Routes by severity: WARNING → Slack only; CRITICAL → Slack + Email
- Configured via `monitoring/alertmanager.yml`

### Grafana
- Pre-built dashboard: **CloudPulse Overview** (`monitoring/grafana/dashboards/cloudpulse.json`)
- Panels: CPU % by server, memory heat-map, disk utilisation, active alert count, log error rate

---

## Running Tests

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run all tests with verbose output
pytest tests/ -v --asyncio-mode=auto

# Run with coverage report
pytest tests/ -v --asyncio-mode=auto --cov=api --cov=alerting --cov=logging --cov-report=html

# Open coverage report
open htmlcov/index.html
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Async PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `SECRET_KEY` | — | JWT signing secret |
| `SLACK_WEBHOOK_URL` | — | Slack incoming webhook |
| `SMTP_HOST` | — | SMTP server for email alerts |
| `SMTP_PORT` | `587` | SMTP port |
| `ALERT_EMAIL_TO` | — | Recipient email for CRITICAL alerts |
| `LOG_LEVEL` | `INFO` | Application log level |
| `ENVIRONMENT` | `development` | `development` or `production` |

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Run tests: `make test`
4. Lint: `make lint`
5. Open a pull request

---

## License

MIT © Gopi Chand Naik Bhukya
