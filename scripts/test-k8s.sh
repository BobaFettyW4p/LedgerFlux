#!/bin/bash
# LedgerFlux Kubernetes Test Script
# This script sets up and tests the LedgerFlux system on local Kubernetes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NAMESPACE="ledgerflux"
REGISTRY="localhost:51432"  # Minikube registry port
CLUSTER_TYPE="minikube"    # Optimized for minikube

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if kubectl is installed
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
        exit 1
    fi
    
    # Check if cluster is running
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Kubernetes cluster is not running"
        exit 1
    fi
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        log_error "Docker is not running"
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

setup_cluster() {
    log_info "Setting up Kubernetes cluster..."
    
    # Create namespace
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    log_success "Namespace $NAMESPACE created/verified"
    
    # Setup minikube registry and docker environment
    log_info "Setting up minikube registry..."
    minikube addons enable registry
    eval $(minikube docker-env)
    log_success "Minikube registry enabled and docker environment configured"
}

build_images() {
    log_info "Building Docker images..."
    
    # Use central build script to ensure consistency
    ./docker/build-images.sh
    log_success "All images built successfully"
}

deploy_infrastructure() {
    log_info "Deploying infrastructure services..."
    
    # Deploy NATS
    kubectl apply -f k8s/infrastructure/nats.yaml
    kubectl wait --for=condition=ready pod -l app=nats -n $NAMESPACE --timeout=300s
    log_success "NATS deployed and ready"
    
    # Deploy DynamoDB Local
    kubectl apply -f k8s/infrastructure/dynamodb.yaml
    kubectl wait --for=condition=ready pod -l app=dynamodb -n $NAMESPACE --timeout=600s
    log_success "DynamoDB Local deployed and ready"
    
    # Deploy MinIO
    kubectl apply -f k8s/infrastructure/minio.yaml
    kubectl wait --for=condition=ready pod -l app=minio -n $NAMESPACE --timeout=300s
    log_success "MinIO deployed and ready"
    
    # Deploy Prometheus
    kubectl apply -f k8s/infrastructure/prometheus.yaml
    kubectl wait --for=condition=ready pod -l app=prometheus -n $NAMESPACE --timeout=300s
    log_success "Prometheus deployed and ready"
    
    # Deploy Grafana
    kubectl apply -f k8s/infrastructure/grafana.yaml
    kubectl wait --for=condition=ready pod -l app=grafana -n $NAMESPACE --timeout=300s
    log_success "Grafana deployed and ready"
}

deploy_services() {
    log_info "Deploying LedgerFlux services..."
    
    # Apply configuration
    kubectl apply -f k8s/services/config.yaml
    kubectl apply -f k8s/services/nats-config.yaml
    kubectl apply -f k8s/services/ingestor-config.yaml
    kubectl apply -f k8s/services/normalizer-config.yaml
    kubectl apply -f k8s/services/snapshotter-config.yaml
    kubectl apply -f k8s/services/gateway-config.yaml
    log_success "Configuration applied"
    
    # Deploy services in order
    services=("ingestor" "normalizer" "snapshotter" "gateway")
    
    for service in "${services[@]}"; do
        log_info "Deploying $service..."
        kubectl apply -f k8s/services/$service.yaml
        
        # Wait for deployment to be ready
        kubectl wait --for=condition=available deployment/$service -n $NAMESPACE --timeout=300s
        log_success "$service deployed and ready"
    done
}

test_connectivity() {
    log_info "Testing service connectivity..."
    
    # Test NATS connectivity
    log_info "Testing NATS..."
    kubectl exec -n $NAMESPACE deployment/nats -- nats server info
    log_success "NATS is accessible"
    
    # Test gateway health
    log_info "Testing gateway health..."
    kubectl port-forward -n $NAMESPACE svc/gateway 8000:8000 &
    PORT_FORWARD_PID=$!
    sleep 5
    
    if curl -f http://localhost:8000/health; then
        log_success "Gateway health check passed"
    else
        log_error "Gateway health check failed"
    fi
    
    # Clean up port forward
    kill $PORT_FORWARD_PID 2>/dev/null || true
}

run_integration_tests() {
    log_info "Running integration tests..."
    
    # Port forward gateway for testing
    kubectl port-forward -n $NAMESPACE svc/gateway 8000:8000 &
    PORT_FORWARD_PID=$!
    sleep 5
    
    # Run test client
    log_info "Running test client..."
    python test_client.py --gateway-url ws://localhost:8000/ws --products BTC-USD,ETH-USD --duration 30
    
    # Clean up port forward
    kill $PORT_FORWARD_PID 2>/dev/null || true
    
    log_success "Integration tests completed"
}

run_load_tests() {
    log_info "Running load tests..."
    
    # Port forward gateway for testing
    kubectl port-forward -n $NAMESPACE svc/gateway 8000:8000 &
    PORT_FORWARD_PID=$!
    sleep 5
    
    # Run load test
    log_info "Running load test with 10 clients..."
    python test_client.py --gateway-url ws://localhost:8000/ws --products BTC-USD,ETH-USD --load-test --num-clients 10 --duration 60
    
    # Clean up port forward
    kill $PORT_FORWARD_PID 2>/dev/null || true
    
    log_success "Load tests completed"
}

check_metrics() {
    log_info "Checking metrics and monitoring..."
    
    # Port forward Prometheus
    kubectl port-forward -n $NAMESPACE svc/prometheus 9090:9090 &
    PROMETHEUS_PID=$!
    
    # Port forward Grafana
    kubectl port-forward -n $NAMESPACE svc/grafana 3000:3000 &
    GRAFANA_PID=$!
    
    sleep 5
    
    log_info "Prometheus: http://localhost:9090"
    log_info "Grafana: http://localhost:3000 (admin/admin)"
    
    # Check if metrics are being collected
    if curl -f http://localhost:9090/api/v1/query?query=up; then
        log_success "Prometheus is collecting metrics"
    else
        log_warning "Prometheus metrics not accessible"
    fi
    
    # Clean up port forwards
    kill $PROMETHEUS_PID 2>/dev/null || true
    kill $GRAFANA_PID 2>/dev/null || true
}

cleanup() {
    log_info "Cleaning up test environment..."
    
    # Delete namespace (this will delete all resources)
    kubectl delete namespace $NAMESPACE --ignore-not-found=true
    
    log_success "Cleanup completed"
}

show_status() {
    log_info "Current system status:"
    echo ""
    
    # Show pods
    kubectl get pods -n $NAMESPACE
    echo ""
    
    # Show services
    kubectl get svc -n $NAMESPACE
    echo ""
    
    # Show deployments
    kubectl get deployments -n $NAMESPACE
    echo ""
}

# Main script logic
case "${1:-all}" in
    "setup")
        check_prerequisites
        setup_cluster
        build_images
        deploy_infrastructure
        deploy_services
        ;;
    "test")
        test_connectivity
        run_integration_tests
        ;;
    "load")
        run_load_tests
        ;;
    "metrics")
        check_metrics
        ;;
    "status")
        show_status
        ;;
    "cleanup")
        cleanup
        ;;
    "all")
        check_prerequisites
        setup_cluster
        build_images
        deploy_infrastructure
        deploy_services
        test_connectivity
        run_integration_tests
        check_metrics
        ;;
    *)
        echo "Usage: $0 {setup|test|load|metrics|status|cleanup|all}"
        echo ""
        echo "Commands:"
        echo "  setup   - Setup cluster and deploy all services"
        echo "  test    - Run integration tests"
        echo "  load    - Run load tests"
        echo "  metrics - Check metrics and monitoring"
        echo "  status  - Show current system status"
        echo "  cleanup - Clean up test environment"
        echo "  all     - Run complete test suite (default)"
        exit 1
        ;;
esac

log_success "Script completed successfully!"
