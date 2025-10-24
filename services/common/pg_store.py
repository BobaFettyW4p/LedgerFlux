import json
import os
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row


class PostgresSnapshotStore:
    """Async Postgres-backed store for latest product snapshots.

    Schema:
      CREATE TABLE IF NOT EXISTS snapshots (
        product TEXT PRIMARY KEY,
        version INT NOT NULL DEFAULT 1,
        last_seq BIGINT NOT NULL,
        ts_snapshot BIGINT NOT NULL,
        state JSONB NOT NULL
      );
    """

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or self._dsn_from_env()
        self._conn: Optional[psycopg.AsyncConnection] = None

    def _dsn_from_env(self) -> str:
        host = os.environ.get("PG_HOST", "postgres")
        port = os.environ.get("PG_PORT", "5432")
        user = os.environ.get("PG_USER", "postgres")
        password = os.environ.get("PG_PASSWORD", "")
        database = os.environ.get("PG_DATABASE", "ledgerflux")
        if password:
            return f"postgresql://{user}:{password}@{host}:{port}/{database}"
        return f"postgresql://{user}@{host}:{port}/{database}"

    async def connect(self) -> None:
        if self._conn and not self._conn.closed:
            return
        self._conn = await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row
        )
        try:
            # optional nicety; ignore if fails
            await self._conn.execute(
                "SET application_name = 'ledgerflux-snapshot-store';"
            )
        except Exception:
            pass

    async def close(self) -> None:
        if self._conn and not self._conn.closed:
            await self._conn.close()

    async def ensure_schema(self) -> None:
        if not self._conn:
            raise RuntimeError("Store not connected; call connect() first")
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                  product TEXT PRIMARY KEY,
                  version INT NOT NULL DEFAULT 1,
                  last_seq BIGINT NOT NULL,
                  ts_snapshot BIGINT NOT NULL,
                  state JSONB NOT NULL
                );
                """
            )
        await self._conn.commit()

    async def upsert_latest(
        self,
        product: str,
        version: int,
        last_seq: int,
        ts_snapshot_ns: int,
        state: Dict[str, Any],
    ) -> None:
        if not self._conn:
            raise RuntimeError("Store not connected; call connect() first")
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO snapshots (product, version, last_seq, ts_snapshot, state)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (product) DO UPDATE SET
                  version    = EXCLUDED.version,
                  last_seq   = EXCLUDED.last_seq,
                  ts_snapshot= EXCLUDED.ts_snapshot,
                  state      = EXCLUDED.state
                ;
                """,
                (
                    product,
                    int(version),
                    int(last_seq),
                    int(ts_snapshot_ns),
                    json.dumps(state),
                ),
            )
        await self._conn.commit()

    async def get_latest(self, product: str) -> Optional[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Store not connected; call connect() first")
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT product, version, last_seq, ts_snapshot, state FROM snapshots WHERE product = %s",
                (product,),
            )
            row = await cur.fetchone()
            return row  # already a dict from row_factory, or None
