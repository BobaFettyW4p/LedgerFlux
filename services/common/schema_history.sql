-- Historical tick data table for LedgerFlux
-- This table stores tick-by-tick price updates for historical analysis and charting

CREATE TABLE IF NOT EXISTS tick_history (
    id BIGSERIAL PRIMARY KEY,
    product VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sequence BIGINT NOT NULL,
    price NUMERIC(18,8),
    bid NUMERIC(18,8),
    ask NUMERIC(18,8),
    volume NUMERIC(18,8),
    ts_event BIGINT,
    ts_ingest BIGINT
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_tick_history_product_time
    ON tick_history (product, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_tick_history_timestamp
    ON tick_history (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_tick_history_product_seq
    ON tick_history (product, sequence);

-- Unique constraint to prevent duplicate ticks
CREATE UNIQUE INDEX IF NOT EXISTS idx_tick_history_unique
    ON tick_history (product, sequence, timestamp);

-- Optional: Add partitioning for better performance with large datasets
-- This can be enabled later if needed:
--
-- -- Convert to partitioned table (requires recreating the table)
-- CREATE TABLE tick_history_partitioned (
--     LIKE tick_history INCLUDING ALL
-- ) PARTITION BY RANGE (timestamp);
--
-- -- Create monthly partitions (example)
-- CREATE TABLE tick_history_2025_01 PARTITION OF tick_history_partitioned
--     FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');

COMMENT ON TABLE tick_history IS 'Historical tick-by-tick market data for all products';
COMMENT ON COLUMN tick_history.product IS 'Product identifier (e.g., BTC-USD, ETH-USD)';
COMMENT ON COLUMN tick_history.timestamp IS 'Database insertion timestamp';
COMMENT ON COLUMN tick_history.sequence IS 'Coinbase sequence number for ordering';
COMMENT ON COLUMN tick_history.price IS 'Last trade price';
COMMENT ON COLUMN tick_history.bid IS 'Best bid price';
COMMENT ON COLUMN tick_history.ask IS 'Best ask price';
COMMENT ON COLUMN tick_history.volume IS 'Trade volume/size';
COMMENT ON COLUMN tick_history.ts_event IS 'Event timestamp from exchange (nanoseconds since epoch)';
COMMENT ON COLUMN tick_history.ts_ingest IS 'Ingestion timestamp (nanoseconds since epoch)';
