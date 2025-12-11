# Observability Setup

This directory contains Prometheus + Grafana configuration for monitoring the Agent Orchestrator.

## Quick Start

### 1. Configure for your environment

```bash
# Copy template
cp .env.example .env

# Edit .env with your API host (localhost, VM IP, or Docker bridge IP)
nano .env

# Generate prometheus.yml
./configure.sh
```

### 2. Start containers

```bash
# From project root
docker-compose -f docker-compose.observability.yml up -d
```

### 3. Access dashboards

- **Grafana**: http://localhost:3001 (admin/admin)
- **Prometheus**: http://localhost:9090

## Configuration

### For Localhost Development
```bash
API_HOST=localhost
API_PORT=8085
```

### For VM Deployment
```bash
API_HOST=192.168.1.100  # Your VM's IP address
API_PORT=8085
```

Find your VM IP:
```bash
hostname -I | awk '{print $1}'
```

## Troubleshooting

### Prometheus shows "DOWN" target

1. Check Prometheus targets: http://localhost:9090/targets
2. Verify API is accessible: `curl http://<API_HOST>:8085/metrics`
3. Update `.env` with correct `API_HOST`
4. Regenerate: `./configure.sh`
5. Restart: `docker-compose -f ../docker-compose.observability.yml restart prometheus`

### VM-specific issues

- Make sure API is running on the VM
- Check firewall isn't blocking port 8085: `sudo ufw allow 8085`
- Use VM's IP address, not `localhost` in .env

## Files

- **`.env`**: Your local configuration (git-ignored)
- **`.env.example`**: Template configuration
- **`configure.sh`**: Generates `prometheus.yml` from `.env`
- **`prometheus.yml`**: Generated Prometheus config (don't edit manually)
- **`grafana/`**: Grafana provisioning and dashboards

## Full Documentation

See `../docs/observability-setup-guide.md` for complete setup instructions, dashboard explanations, and advanced configuration.
