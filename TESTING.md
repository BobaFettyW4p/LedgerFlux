# LedgerFlux Testing Guide

This document provides comprehensive testing instructions for the LedgerFlux market data fan-out system, both for local development and Kubernetes deployment.

## Overview

The LedgerFlux system consists of four main services:
- **Ingestor**: Connects to Coinbase WebSocket and publishes raw market data
- **Normalizer**: Validates and normalizes data, routes to shards
- **Snapshotter**: Maintains product state and creates snapshots
- **Gateway**: Provides WebSocket API to clients

## Prerequisites

### Local Development
- Python 3.12+
- Docker and Docker Compose
- `uv` package manager
- `make` command

### Kubernetes Testing
- `kubectl` configured
- Local Kubernetes cluster (minikube or kind)
- Docker for image building

## Local Development Testing

### 1. Setup Infrastructure
```bash
# Start infrastructure services (NATS, DynamoDB, MinIO, Prometheus, Grafana)
make compose-up

# Verify services are running
docker-compose ps
```

### 2. Run Services
Open multiple terminals and run each service:

```bash
# Terminal 1: Ingestor
make run-ingestor

# Terminal 2: Normalizer (shard 0)
make run-normalizer

# Terminal 3: Snapshotter (shard 0)
make run-snapshotter

# Terminal 4: Gateway
make run-gateway
```

### 3. Test with Client
```bash
# Basic connectivity test
make test-client-basic

# Load test with multiple clients
make test-client-load
```

### 4. Monitor System
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **NATS Monitoring**: http://localhost:8222

## Kubernetes Testing

### 1. Complete Test Suite
```bash
# Run full test suite (setup + test + metrics)
make k8s-all
```

### 2. Individual Test Steps
```bash
# Setup cluster and deploy services
make k8s-setup

# Run integration tests
make k8s-test

# Run load tests
make k8s-load

# Check metrics and monitoring
make k8s-metrics

# Show system status
make k8s-status

# Clean up test environment
make k8s-cleanup
```

### 3. Manual Testing
```bash
# Port forward gateway for testing
kubectl port-forward -n ledgerflux svc/gateway 8000:8000

# Run test client
python test_client.py --gateway-url ws://localhost:8000/ws --products BTC-USD,ETH-USD --duration 60
```

## Test Scenarios

### 1. Basic Connectivity Test
- **Purpose**: Verify end-to-end data flow
- **Duration**: 30 seconds
- **Expected**: 
  - WebSocket connection established
  - Subscription successful
  - Market data received (snapshots + increments)
  - No connection errors

### 2. Load Test
- **Purpose**: Test system under multiple concurrent clients
- **Configuration**: 10 concurrent clients, 60 seconds
- **Expected**:
  - All clients connect successfully
  - Rate limiting works correctly
  - No message loss
  - Stable performance

### 3. Failure Recovery Test
- **Purpose**: Test system resilience
- **Scenarios**:
  - Restart individual services
  - Network partition simulation
  - NATS disconnection
  - Coinbase WebSocket drops

### 4. Performance Test
- **Purpose**: Validate performance requirements
- **Metrics**:
  - Message latency < 100ms p95
  - Throughput > 1000 messages/second
  - Memory usage < 512MB per service
  - CPU usage < 50% per service

## Monitoring and Observability

### Key Metrics to Monitor
- **Ingestor**: Messages received, publish rate, connection status
- **Normalizer**: Validation rate, shard distribution, errors
- **Snapshotter**: State updates, snapshot creation, DDB writes
- **Gateway**: Connected clients, message rate, rate limits

### Grafana Dashboards
- System overview dashboard
- Per-service performance metrics
- Error rates and alerts
- Client connection statistics

### Health Checks
- **Gateway**: `/health` and `/ready` endpoints
- **Services**: Kubernetes liveness and readiness probes
- **Infrastructure**: NATS, DynamoDB, MinIO health endpoints

## Troubleshooting

### Common Issues

#### 1. Service Connection Failures
```bash
# Check service logs
kubectl logs -n ledgerflux deployment/gateway
kubectl logs -n ledgerflux deployment/ingestor

# Check service status
kubectl get pods -n ledgerflux
kubectl describe pod -n ledgerflux <pod-name>
```

#### 2. NATS Connection Issues
```bash
# Check NATS status
kubectl exec -n ledgerflux deployment/nats -- nats server info

# Check NATS streams
kubectl exec -n ledgerflux deployment/nats -- nats stream list
```

#### 3. WebSocket Connection Issues
```bash
# Test gateway connectivity
curl http://localhost:8000/health

# Check gateway logs
kubectl logs -n ledgerflux deployment/gateway -f
```

#### 4. No Market Data Received
```bash
# Check ingestor logs
kubectl logs -n ledgerflux deployment/ingestor -f

# Verify Coinbase connection
# Check if products are configured correctly
# Verify NATS stream creation
```

### Debug Commands
```bash
# Port forward for debugging
kubectl port-forward -n ledgerflux svc/gateway 8000:8000
kubectl port-forward -n ledgerflux svc/prometheus 9090:9090
kubectl port-forward -n ledgerflux svc/grafana 3000:3000

# Check resource usage
kubectl top pods -n ledgerflux
kubectl top nodes

# Check events
kubectl get events -n ledgerflux --sort-by='.lastTimestamp'
```

## Performance Benchmarks

### Expected Performance
- **Latency**: < 100ms p95 for end-to-end message delivery
- **Throughput**: > 1000 messages/second per shard
- **Memory**: < 512MB per service instance
- **CPU**: < 50% per service instance
- **Connections**: Support 100+ concurrent WebSocket clients

### Load Testing Results
- **10 clients**: Should handle without issues
- **50 clients**: May trigger rate limiting
- **100+ clients**: Requires horizontal scaling

## Test Data Validation

### Message Format Validation
- All messages must conform to Pydantic models
- Sequence numbers must be monotonic per product
- Timestamps must be valid nanoseconds
- Price data must be positive numbers

### Shard Distribution Validation
- Products must consistently hash to same shard
- Shard distribution should be roughly even
- No message reordering within a product

### State Consistency Validation
- Snapshot data must match latest tick data
- Product state must be consistent across services
- No data loss during service restarts

## Continuous Integration

### Automated Tests
- Unit tests for all models and utilities
- Integration tests for service communication
- End-to-end tests for complete data flow
- Performance regression tests

### Test Environment
- GitHub Actions for CI/CD
- Automated deployment to test cluster
- Automated test execution
- Test result reporting

## Next Steps

After successful local and Kubernetes testing:

1. **AWS Deployment**: Deploy to EKS with production configurations
2. **Monitoring**: Set up CloudWatch, X-Ray, and production dashboards
3. **Scaling**: Implement horizontal pod autoscaling
4. **Security**: Add authentication and authorization
5. **Backup**: Implement data backup and disaster recovery

## Support

For issues or questions:
1. Check logs and metrics first
2. Review this testing guide
3. Check the main documentation
4. Create an issue with detailed logs and steps to reproduce
