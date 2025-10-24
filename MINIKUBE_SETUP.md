
\# Minikube Setup for LedgerFlux Testing

This guide provides optimized setup instructions for testing LedgerFlux on minikube.

## Why Minikube for LedgerFlux?

Minikube is the **recommended choice** for LedgerFlux testing because:

### ✅ **Stateful Services Support**
- **NATS JetStream**: Needs persistent storage for message retention
- **DynamoDB Local**: Database requires reliable storage
- **MinIO**: Object storage needs persistent volumes
- **Prometheus**: Time-series data needs storage

### ✅ **Production-like Environment**
- VM-based isolation mimics cloud environments
- LoadBalancer services work out-of-the-box
- Better resource isolation and management

### ✅ **Built-in Features**
- Integrated registry for image management
- Addon ecosystem (ingress, metrics, etc.)
- Easy service exposure and port forwarding

## Prerequisites

```bash
# Verify minikube installation
minikube version

# Check if minikube is running
minikube status

# If not running, start minikube
minikube start --memory=4096 --cpus=2 --disk-size=20g
```

## Optimized Minikube Configuration

### 1. Start Minikube with Optimal Settings
```bash
# Recommended minikube configuration for LedgerFlux
minikube start \
  --memory=4096 \
  --cpus=2 \
  --disk-size=20g \
  --driver=docker \
  --addons=registry,ingress,metrics-server
```

### 2. Enable Required Addons
```bash
# Enable registry for local image management
minikube addons enable registry

# Enable ingress for service exposure
minikube addons enable ingress

# Enable metrics server for HPA
minikube addons enable metrics-server

# List enabled addons
minikube addons list
```

### 3. Configure Docker Environment
```bash
# Point Docker to minikube's Docker daemon
eval $(minikube docker-env)

# Verify Docker is using minikube
docker context ls
```

## LedgerFlux-Specific Setup

### 1. Quick Setup
```bash
# Run the complete test suite
make k8s-all
```

### 2. Step-by-Step Setup
```bash
# 1. Setup cluster and build images
make k8s-setup

# 2. Verify deployment
make k8s-status

# 3. Run tests
make k8s-test

# 4. Check metrics
make k8s-metrics
```

## Service Access

### Port Forwarding (Recommended)
```bash
# Gateway WebSocket
kubectl port-forward -n ledgerflux svc/gateway 8000:8000

# Prometheus
kubectl port-forward -n ledgerflux svc/prometheus 9090:9090

# Grafana
kubectl port-forward -n ledgerflux svc/grafana 3000:3000

# NATS Monitoring
kubectl port-forward -n ledgerflux svc/nats 8222:8222
```

### LoadBalancer Access (Alternative)
```bash
# Get minikube IP
minikube ip

# Get service URLs
minikube service -n ledgerflux gateway --url
minikube service -n ledgerflux prometheus --url
minikube service -n ledgerflux grafana --url
```

## Testing Workflow

### 1. Development Testing
```bash
# Start minikube
minikube start

# Setup LedgerFlux
make k8s-setup

# Test connectivity
make k8s-test

# Monitor system
make k8s-metrics
```

### 2. Load Testing
```bash
# Run load tests
make k8s-load

# Monitor resource usage
kubectl top pods -n ledgerflux
kubectl top nodes
```

### 3. Cleanup
```bash
# Clean up test environment
make k8s-cleanup

# Or stop minikube entirely
minikube stop
```

## Troubleshooting

### Common Issues

#### 1. Image Not Found
```bash
# Ensure Docker is using minikube
eval $(minikube docker-env)

# Rebuild images
make k8s-setup
```

#### 2. Storage Issues
```bash
# Check persistent volumes
kubectl get pv
kubectl get pvc -n ledgerflux

# Check storage class
kubectl get storageclass
```

#### 3. Service Access Issues
```bash
# Check service status
kubectl get svc -n ledgerflux

# Check pod status
kubectl get pods -n ledgerflux

# Check logs
kubectl logs -n ledgerflux deployment/gateway
```

#### 4. Resource Constraints
```bash
# Check resource usage
kubectl top pods -n ledgerflux
kubectl describe nodes

# Increase minikube resources if needed
minikube stop
minikube start --memory=6144 --cpus=3
```

## Performance Optimization

### Minikube Resource Tuning
```bash
# For better performance, increase resources
minikube start \
  --memory=6144 \
  --cpus=3 \
  --disk-size=30g \
  --driver=docker
```

### Service Resource Limits
```yaml
# Example resource limits in your deployments
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

## Monitoring and Debugging

### 1. System Monitoring
```bash
# Check cluster status
minikube status

# Check addon status
minikube addons list

# Check resource usage
kubectl top nodes
kubectl top pods -n ledgerflux
```

### 2. Service Debugging
```bash
# Check service logs
kubectl logs -n ledgerflux deployment/gateway -f
kubectl logs -n ledgerflux deployment/ingestor -f

# Check service events
kubectl get events -n ledgerflux --sort-by='.lastTimestamp'

# Describe problematic resources
kubectl describe pod -n ledgerflux <pod-name>
```

### 3. Network Debugging
```bash
# Test service connectivity
kubectl exec -n ledgerflux deployment/gateway -- curl http://localhost:8000/health

# Check NATS connectivity
kubectl exec -n ledgerflux deployment/nats -- nats server info
```

## Comparison with Kind

| Feature | Minikube | Kind |
|---------|----------|------|
| **Startup Time** | 2-3 minutes | 30 seconds |
| **Resource Usage** | Higher (VM) | Lower (containers) |
| **Storage** | Excellent | Good |
| **LoadBalancer** | Native support | Requires workarounds |
| **Registry** | Built-in | Manual setup |
| **Production-like** | Yes | Limited |
| **CI/CD** | Good | Excellent |

## Recommendation

**Stick with minikube** for LedgerFlux testing because:

1. **Stateful Services**: Your system has multiple stateful services that benefit from VM isolation
2. **Storage Requirements**: NATS, DynamoDB, MinIO, and Prometheus all need reliable storage
3. **Production Similarity**: VM-based environment better mimics AWS EKS
4. **Ease of Use**: Built-in registry and LoadBalancer support simplify testing

## Next Steps

After successful minikube testing:

1. **Validate Performance**: Ensure all acceptance criteria are met
2. **Load Testing**: Test with realistic production loads
3. **Failure Testing**: Validate resilience and recovery
4. **AWS Migration**: Deploy to EKS with confidence

The minikube setup provides an excellent foundation for validating your LedgerFlux system before AWS deployment.
