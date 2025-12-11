# Observability Setup Guide

Complete guide to setting up Prometheus + Grafana for the Agent Orchestrator.

---

## 📋 What You'll Get

After following this guide, you'll have:

✅ **Prometheus** scraping metrics from your API
✅ **Grafana** dashboard showing real-time visualizations
✅ **Key metrics tracked**: Git operations, task execution, LLM costs
✅ **Alerts** (optional) for critical issues

---

## 🚀 Quick Start (5 minutes)

### Step 1: Install Dependencies

```bash
# Add prometheus-client to requirements.txt
echo "prometheus-client==0.19.0" >> requirements.txt

# Install
pip install -r requirements.txt
```

### Step 2: Start Prometheus + Grafana

```bash
# Start containers
docker-compose -f docker-compose.observability.yml up -d

# Check logs
docker-compose -f docker-compose.observability.yml logs -f
```

**Services will be available at:**
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)

### Step 3: Start Your API

```bash
# Start the orchestrator API
python src/server.py
```

### Step 4: Verify Metrics

```bash
# Check metrics endpoint
curl http://localhost:8000/metrics

# You should see output like:
# # HELP git_merge_duration_seconds ...
# # TYPE git_merge_duration_seconds histogram
# ...
```

### Step 5: View Grafana Dashboard

1. Open http://localhost:3001
2. Login with `admin` / `admin`
3. Navigate to Dashboards → Agent Orchestrator - Overview
4. You should see panels (they'll be empty until you run a task)

---

## 📊 Running Your First Monitored Task

```bash
# Create a test run
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "objective": "Create a simple hello world function",
    "workspace_path": "/tmp/test-workspace",
    "orch_config": {
      "director_model": {"provider": "openai", "model_name": "gpt-4"},
      "worker_model": {"provider": "openai", "model_name": "gpt-4"}
    }
  }'

# Watch metrics update in real-time
watch -n 1 'curl -s http://localhost:8000/metrics | grep -E "(git_merge|task_execution)"'
```

Go to Grafana and watch the dashboard come alive!

---

## 🔧 Configuration

### Prometheus Target Configuration

If you're **not** using Docker Desktop (Mac/Windows), update the target in `observability/prometheus.yml`:

```yaml
# For Linux (find Docker bridge IP)
scrape_configs:
  - job_name: 'agent-orchestrator'
    static_configs:
      - targets: ['172.17.0.1:8000']  # Docker bridge IP
```

**Find your bridge IP:**
```bash
# Linux
docker network inspect bridge | grep Gateway

# Or add to same network
docker-compose -f docker-compose.observability.yml down
# Edit docker-compose.observability.yml to use host network mode
```

### Change Scrape Interval

```yaml
# observability/prometheus.yml
global:
  scrape_interval: 5s  # More frequent (default: 15s)
```

---

## 📈 Understanding the Dashboard

### Panel 1: Active Merges (Gauge)
- **What it shows**: Current number of concurrent git merges
- **What to watch for**:
  - ✅ Should be 0 or 1 (with locks)
  - ❌ If > 1, you have concurrent merges (bad!)

### Panel 2: Active Tasks (Gauge)
- **What it shows**: Tasks currently being executed
- **What to watch for**:
  - ✅ < 10 is normal
  - ⚠️ > 10 might indicate backlog
  - ❌ Stuck at same number = possible deadlock

### Panel 3: Git Merge Duration (Histogram)
- **What it shows**: How long merges take (p50, p95, p99)
- **What to watch for**:
  - ✅ p95 < 5s is good
  - ⚠️ p95 > 10s is slow
  - ❌ Spikes indicate conflicts or LLM resolution

### Panel 4: Merge Results (Rate)
- **What it shows**: Success vs. conflict vs. error rates
- **What to watch for**:
  - ✅ Mostly success (green)
  - ⚠️ Some conflicts (yellow) is normal
  - ❌ High error rate (red) = bug!

### Panel 5: Task States (Stacked Area)
- **What it shows**: Distribution of tasks across states
- **What to watch for**:
  - ✅ Should see progression: planned → ready → active → complete
  - ❌ Tasks stuck in "planned" = dependency deadlock
  - ❌ High "failed" = quality issues

### Panel 6: Task Execution Duration (Line)
- **What it shows**: How long workers take, by type
- **What to watch for**:
  - ✅ Coder: 30-120s, Tester: 10-60s, Planner: 5-30s
  - ❌ Durations > 300s = timeout issues

### Panel 7: Total LLM Cost (Gauge)
- **What it shows**: Cumulative LLM API costs
- **What to watch for**:
  - ✅ Track your burn rate
  - ⚠️ Set budget alerts (see below)
  - ❌ Rapid growth = runaway loop

### Panel 8: LLM Requests by Model (Line)
- **What it shows**: Request rate per model
- **What to watch for**:
  - ✅ Success rate high
  - ⚠️ Rate limits = need backoff/retry
  - ❌ High error rate = API key issues

---

## 🚨 Setting Up Alerts (Optional)

### Example Alert: High Concurrent Merges

```yaml
# observability/alerts.yml
groups:
  - name: git_alerts
    interval: 10s
    rules:
      - alert: ConcurrentMerges
        expr: git_active_merges > 1
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Multiple concurrent git merges detected"
          description: "{{ $value }} merges are running simultaneously. Race condition likely!"

      - alert: HighConflictRate
        expr: rate(git_merge_total{result="conflict"}[5m]) > 0.5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "High merge conflict rate"
          description: "More than 50% of merges have conflicts"

  - name: cost_alerts
    interval: 30s
    rules:
      - alert: HighLLMCost
        expr: llm_cost_dollars_total > 10
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "LLM costs exceeded $10"
          description: "Total cost: ${{ $value }}"

      - alert: RateLimitErrors
        expr: rate(llm_rate_limit_events_total[5m]) > 0.1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Frequent rate limit errors"
          description: "Getting rate limited by LLM provider"
```

**Enable alerts:**
```yaml
# observability/prometheus.yml
rule_files:
  - "alerts.yml"
```

---

## 🔍 Useful Prometheus Queries

### Git Operations

```promql
# Average merge duration (last 5 min)
rate(git_merge_duration_seconds_sum[5m]) / rate(git_merge_duration_seconds_count[5m])

# Conflict rate percentage
100 * rate(git_merge_total{result="conflict"}[5m]) / rate(git_merge_total[5m])

# Peak concurrent merges
max_over_time(git_active_merges[1h])
```

### Task Execution

```promql
# Task completion rate (tasks/sec)
rate(task_completion_total{status="success"}[5m])

# Average retries per task
rate(task_retry_count_sum[5m]) / rate(task_retry_count_count[5m])

# Worker utilization
sum(active_workers) by (worker_profile)
```

### LLM Costs

```promql
# Cost per hour (estimate)
rate(llm_cost_dollars_total[1h]) * 3600

# Tokens per request
rate(llm_tokens_total[5m]) / rate(llm_requests_total[5m])

# Most expensive model
topk(3, rate(llm_cost_dollars_total[5m]) by (model))
```

---

## 🎨 Customizing Grafana

### Create New Panel

1. Click "Add panel" → "Add new panel"
2. Select data source: Prometheus
3. Enter query (see examples above)
4. Configure visualization (graph, gauge, stat, etc.)
5. Save dashboard

### Example: Merge Lock Wait Time

```promql
histogram_quantile(0.95, sum(rate(git_lock_wait_duration_seconds_bucket[5m])) by (le))
```

Visualization: Time series
Title: "Merge Lock Wait Time (p95)"

### Example: Worker Success Rate

```promql
100 * sum(rate(task_completion_total{status="success"}[5m])) by (worker_profile)
  / sum(rate(task_completion_total[5m])) by (worker_profile)
```

Visualization: Gauge
Title: "Worker Success Rate (%)"

---

## 🐛 Troubleshooting

### Issue: Prometheus can't scrape metrics

**Symptoms**: Dashboard shows "No data"

**Fixes**:
1. Check API is running: `curl http://localhost:8000/metrics`
2. Check Prometheus targets: http://localhost:9090/targets
   - Should show `agent-orchestrator` as UP
3. If DOWN, check target IP:
   ```bash
   # Mac/Windows: use host.docker.internal
   # Linux: use docker network inspect bridge | grep Gateway
   ```
4. Update `observability/prometheus.yml` with correct IP
5. Restart: `docker-compose -f docker-compose.observability.yml restart prometheus`

### Issue: Grafana dashboard is empty

**Fixes**:
1. Check data source: Configuration → Data Sources → Prometheus
   - URL should be `http://prometheus:9090`
   - Click "Test" button (should be green)
2. Check time range: Top right, change to "Last 5 minutes"
3. Run a task to generate metrics
4. Wait 15s for scrape interval

### Issue: Metrics not incrementing

**Fixes**:
1. Ensure you've instrumented your code (see `docs/metrics-instrumentation-example.md`)
2. Check imports: `from metrics import git_metrics`
3. Verify context managers are being used: `with git_metrics.track_merge():`
4. Check server logs for errors

---

## 📦 Production Deployment

### Persistent Storage

By default, metrics are stored in Docker volumes. To persist across rebuilds:

```yaml
# docker-compose.observability.yml
volumes:
  prometheus-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /path/to/prometheus/data

  grafana-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /path/to/grafana/data
```

### Retention Policy

```yaml
# observability/prometheus.yml
global:
  scrape_interval: 15s

# Add to prometheus command
command:
  - '--storage.tsdb.retention.time=30d'  # Keep 30 days
  - '--storage.tsdb.retention.size=10GB' # Or 10GB max
```

### Security

```yaml
# observability/grafana/provisioning/datasources/prometheus.yml
datasources:
  - name: Prometheus
    basicAuth: true
    basicAuthUser: admin
    secureJsonData:
      basicAuthPassword: your-secure-password
```

### Alerting to Slack/Email

1. Set up Alertmanager
2. Configure webhook:

```yaml
# observability/alertmanager.yml
route:
  receiver: 'slack'

receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}\n{{ end }}'
```

---

## 🎓 Next Steps

1. **Instrument git_manager.py** - Add metrics to merge operations (see `docs/metrics-instrumentation-example.md`)
2. **Set cost budget alert** - Get notified when LLM costs exceed threshold
3. **Create custom dashboard** - Panels specific to your workflow
4. **Add trace correlation** - Connect metrics to logs (OpenTelemetry)

---

## 📚 Resources

- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Dashboards](https://grafana.com/docs/grafana/latest/dashboards/)
- [Histogram Quantiles Explained](https://prometheus.io/docs/practices/histograms/)

---

## 💡 Pro Tips

1. **Use annotations** - Mark deployments/incidents on dashboard
2. **Create snapshots** - Share dashboard state with team
3. **Export dashboard** - Save JSON for version control
4. **Use variables** - Filter by run_id, worker_profile, etc.
5. **Set thresholds** - Visual alerts on gauges (green/yellow/red)

---

Need help? Check the examples in `docs/metrics-instrumentation-example.md` or ask!
