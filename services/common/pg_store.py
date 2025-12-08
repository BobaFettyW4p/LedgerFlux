"""
Async PostgreSQL snapshot store used by gateway and snapshotter.

The store maintains a single `snapshots` table keyed by product and exposes
minimal helpers to connect, ensure schema, upsert the latest state, fetch the
latest snapshot for a product, and close the connection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row


@dataclass
class SnapshotRecord:
    product: str
    version: int
    last_seq: int
    ts_snapshot: int
    state: Dict[str, Any]


class PostgresSnapshotStore:
    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn_input = dsn
        self._conn: Optional[psycopg.AsyncConnection[Any]] = None

    def _build_dsn(self) -> str:
        if self._dsn_input:
            return self._dsn_input

        env_dsn = os.getenv("PG_DSN")
        if env_dsn:
            return env_dsn

        host = os.getenv("PG_HOST", "localhost")
        port = int(os.getenv("PG_PORT", "5432"))
        database = os.getenv("PG_DATABASE", "ledgerflux")
        user = os.getenv("PG_USER", "postgres")
        password = os.getenv("PG_PASSWORD")

        auth = user
        if password:
            auth = f"{user}:{password}"

        return f"postgresql://{auth}@{host}:{port}/{database}"

    async def connect(self) -> None:
        if self._conn:
            return
        dsn = self._build_dsn()
        self._conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)

    async def ensure_schema(self) -> None:
        if not self._conn:
            await self.connect()
        assert self._conn is not None

        create_stmt = """
        CREATE TABLE IF NOT EXISTS snapshots (
            product TEXT PRIMARY KEY,
            version INT NOT NULL,
            last_seq BIGINT NOT NULL,
            ts_snapshot BIGINT NOT NULL,
            state JSONB NOT NULL
        )
        """
        async with self._conn.cursor() as cur:
            await cur.execute(create_stmt)

    async def upsert_latest(
        self,
        product: str,
        version: int,
        last_seq: int,
        ts_snapshot_ns: int,
        state: Dict[str, Any],
    ) -> None:
        if not self._conn:
            await self.connect()
        assert self._conn is not None

        upsert_stmt = """
        INSERT INTO snapshots (product, version, last_seq, ts_snapshot, state)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (product)
        DO UPDATE SET
            version = EXCLUDED.version,
            last_seq = EXCLUDED.last_seq,
            ts_snapshot = EXCLUDED.ts_snapshot,
            state = EXCLUDED.state
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                upsert_stmt, (product, version, last_seq, ts_snapshot_ns, state)
            )

    async def get_latest(self, product: str) -> Optional[SnapshotRecord]:
        if not self._conn:
            await self.connect()
        assert self._conn is not None

        query = """
        SELECT product, version, last_seq, ts_snapshot, state
        FROM snapshots
        WHERE product = %s
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (product,))
            row = await cur.fetchone()
            if not row:
                return None
            return SnapshotRecord(
                product=row["product"],
                version=int(row["version"]),
                last_seq=int(row["last_seq"]),
                ts_snapshot=int(row["ts_snapshot"]),
                state=row["state"],
            )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
