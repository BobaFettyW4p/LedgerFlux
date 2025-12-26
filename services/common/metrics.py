"""
Prometheus metrics for LedgerFlux services.

This module defines all application metrics using prometheus-client.
Metrics are organized by service and can be imported by any component.
"""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST

# =============================================================================
# Gateway Metrics
# =============================================================================

# Client connections
gateway_clients_connected = Gauge(
    'ledgerflux_gateway_clients_connected',
    'Number of currently connected WebSocket clients'
)

gateway_clients_total = Counter(
    'ledgerflux_gateway_clients_total',
    'Total number of client connections',
    ['status']  # connected, disconnected
)

# Message delivery
gateway_messages_sent_total = Counter(
    'ledgerflux_gateway_messages_sent_total',
    'Total messages sent to clients',
    ['product', 'message_type']  # message_type: snapshot, incr, rate_limit, pong, error
)

gateway_rate_limits_total = Counter(
    'ledgerflux_gateway_rate_limits_total',
    'Total number of rate limit hits per client'
)

# Subscriptions
gateway_subscriptions_total = Counter(
    'ledgerflux_gateway_subscriptions_total',
    'Total subscription operations',
    ['product', 'operation']  # operation: subscribe, unsubscribe
)

gateway_active_subscriptions = Gauge(
    'ledgerflux_gateway_active_subscriptions',
    'Current number of active subscriptions',
    ['product']
)

# Message processing latency
gateway_message_latency_seconds = Histogram(
    'ledgerflux_gateway_message_latency_seconds',
    'Time to process and send message to client',
    ['product'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# =============================================================================
# Ingestor Metrics
# =============================================================================

# Ticks received from Coinbase
ingestor_ticks_received_total = Counter(
    'ledgerflux_ingestor_ticks_received_total',
    'Total ticks received from Coinbase',
    ['product']
)

# Ticks published to NATS
ingestor_ticks_published_total = Counter(
    'ledgerflux_ingestor_ticks_published_total',
    'Total ticks published to NATS',
    ['product', 'shard']
)

# Sequence gaps and resyncs
ingestor_gaps_detected_total = Counter(
    'ledgerflux_ingestor_gaps_detected_total',
    'Total sequence gaps detected',
    ['product']
)

ingestor_resyncs_total = Counter(
    'ledgerflux_ingestor_resyncs_total',
    'Total resync operations performed',
    ['product', 'status']  # status: success, failure
)

# WebSocket connection status
ingestor_websocket_connected = Gauge(
    'ledgerflux_ingestor_websocket_connected',
    'Coinbase WebSocket connection status (1=connected, 0=disconnected)'
)

ingestor_websocket_reconnects_total = Counter(
    'ledgerflux_ingestor_websocket_reconnects_total',
    'Total WebSocket reconnection attempts'
)

# Processing latency
ingestor_processing_latency_seconds = Histogram(
    'ledgerflux_ingestor_processing_latency_seconds',
    'Time from receiving tick to publishing to NATS',
    ['product'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# =============================================================================
# Normalizer Metrics
# =============================================================================

normalizer_messages_received_total = Counter(
    'ledgerflux_normalizer_messages_received_total',
    'Total messages received from NATS',
    ['shard']
)

normalizer_messages_processed_total = Counter(
    'ledgerflux_normalizer_messages_processed_total',
    'Total messages successfully processed',
    ['shard', 'product']
)

normalizer_out_of_order_total = Counter(
    'ledgerflux_normalizer_out_of_order_total',
    'Total out-of-order messages detected',
    ['shard', 'product']
)

normalizer_validation_errors_total = Counter(
    'ledgerflux_normalizer_validation_errors_total',
    'Total validation errors',
    ['shard', 'error_type']
)

normalizer_processing_latency_seconds = Histogram(
    'ledgerflux_normalizer_processing_latency_seconds',
    'Message processing latency',
    ['shard'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# =============================================================================
# Snapshotter Metrics
# =============================================================================

snapshotter_ticks_processed_total = Counter(
    'ledgerflux_snapshotter_ticks_processed_total',
    'Total ticks processed',
    ['shard', 'product']
)

snapshotter_snapshots_written_total = Counter(
    'ledgerflux_snapshotter_snapshots_written_total',
    'Total snapshots written to PostgreSQL',
    ['product', 'status']  # status: success, failure
)

snapshotter_history_written_total = Counter(
    'ledgerflux_snapshotter_history_written_total',
    'Total historical ticks written to PostgreSQL',
    ['product', 'status']  # status: success, failure
)

snapshotter_write_latency_seconds = Histogram(
    'ledgerflux_snapshotter_write_latency_seconds',
    'Database write latency',
    ['operation'],  # operation: snapshot, history
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

snapshotter_products_tracked = Gauge(
    'ledgerflux_snapshotter_products_tracked',
    'Number of products being tracked',
    ['shard']
)

# =============================================================================
# NATS/Broker Metrics
# =============================================================================

nats_messages_published_total = Counter(
    'ledgerflux_nats_messages_published_total',
    'Total messages published to NATS',
    ['subject', 'service']
)

nats_messages_consumed_total = Counter(
    'ledgerflux_nats_messages_consumed_total',
    'Total messages consumed from NATS',
    ['subject', 'service']
)

nats_publish_errors_total = Counter(
    'ledgerflux_nats_publish_errors_total',
    'Total NATS publish errors',
    ['service']
)

nats_consumer_lag_messages = Gauge(
    'ledgerflux_nats_consumer_lag_messages',
    'Number of messages behind in the stream',
    ['consumer', 'service']
)

# =============================================================================
# PostgreSQL Metrics
# =============================================================================

postgres_queries_total = Counter(
    'ledgerflux_postgres_queries_total',
    'Total database queries executed',
    ['service', 'operation', 'status']  # operation: select, insert, update; status: success, error
)

postgres_query_latency_seconds = Histogram(
    'ledgerflux_postgres_query_latency_seconds',
    'Database query latency',
    ['service', 'operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

postgres_connections_active = Gauge(
    'ledgerflux_postgres_connections_active',
    'Number of active database connections',
    ['service']
)

# =============================================================================
# System Info Metrics
# =============================================================================

ledgerflux_build_info = Info(
    'ledgerflux_build',
    'Build information'
)

# =============================================================================
# Helper Functions
# =============================================================================

def get_metrics_response():
    """
    Generate Prometheus metrics response.

    Returns tuple of (content, media_type) suitable for FastAPI Response.
    """
    return generate_latest(), CONTENT_TYPE_LATEST


def set_build_info(service_name: str, version: str = "0.1.0", commit: str = "unknown"):
    """
    Set build information for the service.

    Args:
        service_name: Name of the service (gateway, ingestor, etc.)
        version: Version string
        commit: Git commit hash
    """
    ledgerflux_build_info.info({
        'service': service_name,
        'version': version,
        'commit': commit
    })
