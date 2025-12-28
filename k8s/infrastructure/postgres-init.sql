-- LedgerFlux Database Initialization
-- This script creates the necessary tables for storing market data

-- Create the snapshots table for storing latest state per product
CREATE TABLE IF NOT EXISTS snapshots (
    product TEXT PRIMARY KEY,
    version INT NOT NULL,
    last_seq BIGINT NOT NULL,
    ts_snapshot BIGINT NOT NULL,
    state JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index on timestamp for time-based queries
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts_snapshot);

-- Create the tick_history table for storing historical tick data
CREATE TABLE IF NOT EXISTS tick_history (
    id BIGSERIAL PRIMARY KEY,
    product TEXT NOT NULL,
    sequence BIGINT NOT NULL,
    price NUMERIC(20, 8),
    bid NUMERIC(20, 8),
    ask NUMERIC(20, 8),
    volume NUMERIC(20, 8),
    ts_event BIGINT NOT NULL,
    ts_ingest BIGINT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product, sequence, timestamp)
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_tick_history_product ON tick_history(product);
CREATE INDEX IF NOT EXISTS idx_tick_history_ts_event ON tick_history(ts_event);
CREATE INDEX IF NOT EXISTS idx_tick_history_timestamp ON tick_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_tick_history_product_ts ON tick_history(product, timestamp);

-- Create a view for latest prices (useful for Grafana)
CREATE OR REPLACE VIEW latest_prices AS
SELECT DISTINCT ON (product)
    product,
    price,
    bid,
    ask,
    volume,
    ts_event,
    timestamp
FROM tick_history
ORDER BY product, timestamp DESC;

-- Create a materialized view for aggregated metrics (optional, for performance)
CREATE MATERIALIZED VIEW IF NOT EXISTS price_stats_1min AS
SELECT
    product,
    date_trunc('minute', timestamp) as time_bucket,
    COUNT(*) as tick_count,
    AVG(price) as avg_price,
    MIN(price) as min_price,
    MAX(price) as max_price,
    (array_agg(price ORDER BY timestamp))[1] as open_price,
    (array_agg(price ORDER BY timestamp DESC))[1] as close_price,
    AVG(volume) as avg_volume
FROM tick_history
WHERE price IS NOT NULL
GROUP BY product, date_trunc('minute', timestamp)
ORDER BY time_bucket DESC;

-- Create index on materialized view
CREATE INDEX IF NOT EXISTS idx_price_stats_product_time ON price_stats_1min(product, time_bucket);

-- Grant permissions (adjust if using different user)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Print success message
DO $$
BEGIN
    RAISE NOTICE 'LedgerFlux database schema initialized successfully';
END $$;
