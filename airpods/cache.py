import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from .compress import compress_samples
from .parser import DeviceInfo, Sample

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    address TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS samples (
    address TEXT NOT NULL,
    ts REAL NOT NULL,
    l INTEGER,
    r INTEGER,
    c INTEGER,
    l_chg INTEGER,
    r_chg INTEGER,
    c_chg INTEGER,
    cnx INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (address, ts)
);
CREATE TABLE IF NOT EXISTS ranges (
    address TEXT NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    PRIMARY KEY (address, start, end)
);
"""


def _epoch(value: datetime) -> float:
    return value.timestamp()


def _datetime(value: float) -> datetime:
    return datetime.fromtimestamp(value)


def _flag(value: Optional[bool]) -> Optional[int]:
    return None if value is None else int(bool(value))


def _bool(value) -> Optional[bool]:
    return None if value is None else bool(value)


def _merge_ranges(ranges, tolerance_seconds: float = 0):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + tolerance_seconds:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


class Cache:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert_samples(self, samples) -> None:
        rows = [
            (
                sample.address,
                _epoch(sample.ts),
                sample.l,
                sample.r,
                sample.c,
                _flag(sample.l_charging),
                _flag(sample.r_charging),
                _flag(sample.c_charging),
                int(bool(sample.cnx)),
            )
            for sample in compress_samples(samples)
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO samples
                    (address, ts, l, r, c, l_chg, r_chg, c_chg, cnx)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()

    def get_samples(self, address: str, start: datetime, end: datetime) -> list[Sample]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM samples
                WHERE address = ? AND ts >= ? AND ts <= ?
                ORDER BY ts
                """,
                (address, _epoch(start), _epoch(end)),
            ).fetchall()
        return [
            Sample(
                ts=_datetime(row["ts"]),
                address=row["address"],
                l=row["l"],
                r=row["r"],
                c=row["c"],
                l_charging=_bool(row["l_chg"]),
                r_charging=_bool(row["r_chg"]),
                c_charging=_bool(row["c_chg"]),
                cnx=bool(row["cnx"]),
            )
            for row in rows
        ]

    def add_range(self, address: str, start: datetime, end: datetime) -> None:
        if end < start:
            start, end = end, start
        with self._lock:
            existing = self._conn.execute(
                "SELECT start, end FROM ranges WHERE address = ?", (address,)
            ).fetchall()
            merged = _merge_ranges(
                [(row["start"], row["end"]) for row in existing]
                + [(_epoch(start), _epoch(end))]
            )
            self._conn.execute("DELETE FROM ranges WHERE address = ?", (address,))
            self._conn.executemany(
                "INSERT INTO ranges (address, start, end) VALUES (?, ?, ?)",
                [(address, item[0], item[1]) for item in merged],
            )
            self._conn.commit()

    def get_ranges(self, address: str) -> list[tuple[datetime, datetime]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT start, end FROM ranges WHERE address = ? ORDER BY start",
                (address,),
            ).fetchall()
        return [(_datetime(row["start"]), _datetime(row["end"])) for row in rows]

    def missing_ranges(
        self,
        address: str,
        start: datetime,
        end: datetime,
        tolerance_seconds: int = 0,
    ) -> list[tuple[datetime, datetime]]:
        if end <= start:
            return []

        start_epoch = _epoch(start)
        end_epoch = _epoch(end)

        with self._lock:
            rows = self._conn.execute(
                "SELECT start, end FROM ranges WHERE address = ? ORDER BY start",
                (address,),
            ).fetchall()

        merged = _merge_ranges(
            [(row["start"], row["end"]) for row in rows], tolerance_seconds
        )

        missing = []
        cursor = start_epoch
        for range_start, range_end in merged:
            if range_end <= cursor:
                continue
            if range_start > cursor + tolerance_seconds:
                missing.append(
                    (_datetime(cursor), _datetime(min(range_start, end_epoch)))
                )
            cursor = max(cursor, range_end)
            if cursor >= end_epoch:
                break

        if end_epoch > cursor + tolerance_seconds:
            missing.append((_datetime(cursor), _datetime(end_epoch)))

        return [
            (max(gap_start, start), min(gap_end, end))
            for gap_start, gap_end in missing
            if gap_end > gap_start
        ]

    def upsert_device(
        self, address: str, name: str, last_seen: Optional[datetime]
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO devices (address, name, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    name = CASE
                        WHEN excluded.name != '' THEN excluded.name
                        ELSE devices.name
                    END,
                    last_seen = CASE
                        WHEN devices.last_seen IS NULL THEN excluded.last_seen
                        WHEN excluded.last_seen IS NULL THEN devices.last_seen
                        ELSE MAX(devices.last_seen, excluded.last_seen)
                    END
                """,
                (address, name, _epoch(last_seen) if last_seen else None),
            )
            self._conn.commit()

    def list_devices(self) -> list[DeviceInfo]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT d.address, d.name, d.last_seen, COUNT(s.ts) AS sample_count
                FROM devices d
                LEFT JOIN samples s ON s.address = d.address
                GROUP BY d.address
                ORDER BY d.last_seen DESC
                """
            ).fetchall()
        return [
            DeviceInfo(
                address=row["address"],
                name=row["name"],
                last_seen=_datetime(row["last_seen"]) if row["last_seen"] else None,
                sample_count=row["sample_count"],
            )
            for row in rows
        ]
