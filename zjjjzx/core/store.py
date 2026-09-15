from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from zjjjzx.core.parser import Listing


class Store:
    def __init__(self, path: str) -> None:
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
                external_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluations (
                external_id TEXT PRIMARY KEY REFERENCES listings(external_id),
                hard_pass INTEGER NOT NULL,
                hard_reason TEXT NOT NULL,
                llm_pass INTEGER,
                llm_reason TEXT NOT NULL DEFAULT '',
                confidence REAL,
                score REAL,
                level TEXT,
                notified INTEGER NOT NULL DEFAULT 0,
                user_decision TEXT NOT NULL DEFAULT 'pending',
                evaluation_scope TEXT NOT NULL DEFAULT '',
                extracted TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                fetched INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS map_cache (
                address TEXT PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                distance_meters REAL,
                updated_at TEXT NOT NULL
            );
            """
        )
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(evaluations)")
        }
        if "evaluation_scope" not in columns:
            self.connection.execute(
                "ALTER TABLE evaluations ADD COLUMN evaluation_scope TEXT NOT NULL DEFAULT ''"
            )
            self.connection.commit()

        if "extracted" not in columns:
            self.connection.execute(
                "ALTER TABLE evaluations ADD COLUMN extracted TEXT NOT NULL DEFAULT '{}'"
            )
            self.connection.commit()

        self.connection.commit()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert(self, listing: Listing) -> bool:
        now = self.now()
        exists = self.connection.execute(
            "SELECT 1 FROM listings WHERE external_id = ?", (listing.external_id,)
        ).fetchone()
        payload = json.dumps(listing.to_dict(), ensure_ascii=False)
        self.connection.execute(
            """INSERT INTO listings(external_id, payload, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(external_id) DO UPDATE SET payload=excluded.payload, last_seen_at=excluded.last_seen_at""",
            (listing.external_id, payload, now, now),
        )
        self.connection.commit()
        return exists is None

    def evaluation(self, external_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM evaluations WHERE external_id = ?", (external_id,)
        ).fetchone()

    def save_evaluation(self, external_id: str, values: dict) -> None:
        now = self.now()
        self.connection.execute(
            """INSERT INTO evaluations(
                external_id, hard_pass, hard_reason, llm_pass, llm_reason,
                confidence, score, level, notified, user_decision, evaluation_scope, extracted, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                hard_pass=excluded.hard_pass, hard_reason=excluded.hard_reason,
                llm_pass=excluded.llm_pass, llm_reason=excluded.llm_reason,
                confidence=excluded.confidence, score=excluded.score,
                level=excluded.level, notified=excluded.notified,
                user_decision=excluded.user_decision, evaluation_scope=excluded.evaluation_scope,
                extracted=excluded.extracted, updated_at=excluded.updated_at""",
            (
                external_id,
                int(values.get("hard_pass", False)),
                values.get("hard_reason", ""),
                None if values.get("llm_pass") is None else int(values["llm_pass"]),
                values.get("llm_reason", ""),
                values.get("confidence"),
                values.get("score"),
                values.get("level"),
                int(values.get("notified", False)),
                values.get("user_decision", "pending"),
                values.get("evaluation_scope", ""),
                json.dumps(values.get("extracted", {}), ensure_ascii=False),
                now,
            ),
        )
        self.connection.commit()

    def map_cache(self, address: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM map_cache WHERE address = ?", (address,)
        ).fetchone()

    def save_map_cache(
        self,
        address: str,
        latitude: float,
        longitude: float,
        distance_meters: float | None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO map_cache(address, latitude, longitude, distance_meters, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(address) DO UPDATE SET latitude=excluded.latitude,
               longitude=excluded.longitude, distance_meters=excluded.distance_meters,
               updated_at=excluded.updated_at""",
            (address, latitude, longitude, distance_meters, self.now()),
        )
        self.connection.commit()

    def start_run(self) -> int:
        cursor = self.connection.execute("INSERT INTO runs(started_at) VALUES (?)", (self.now(),))
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, **values: int | str) -> None:
        allowed = {key: value for key, value in values.items() if key in {"finished_at", "fetched", "new_count", "candidate_count", "error"}}
        allowed.setdefault("finished_at", self.now())
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        self.connection.execute(f"UPDATE runs SET {assignments} WHERE id = ?", (*allowed.values(), run_id))
        self.connection.commit()

    def update_user_decision(self, external_id: str, decision: str) -> None:
        self.connection.execute(
            "UPDATE evaluations SET user_decision = ?, updated_at = ? WHERE external_id = ?",
            (decision, self.now(), external_id),
        )
        self.connection.commit()

    def mark_notified(self, external_id: str, notified: bool = True) -> None:
        self.connection.execute(
            "UPDATE evaluations SET notified = ?, updated_at = ? WHERE external_id = ?",
            (1 if notified else 0, self.now(), external_id),
        )
        self.connection.commit()

    def get_candidates(self, limit: int | None = None) -> list[dict]:
        query = """
            SELECT
                e.external_id,
                e.score,
                e.llm_reason,
                e.extracted,
                e.notified,
                e.user_decision,
                e.updated_at,
                l.payload,
                m.distance_meters
            FROM evaluations e
            JOIN listings l ON e.external_id = l.external_id
            LEFT JOIN map_cache m ON json_extract(l.payload, '$.address') = m.address
            WHERE e.hard_pass = 1 AND e.llm_pass = 1
            ORDER BY COALESCE(e.score, 0) DESC, e.updated_at DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self.connection.execute(query).fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {}
            try:
                extracted = json.loads(row["extracted"])
            except Exception:
                extracted = {}
            results.append({
                "external_id": row["external_id"],
                "score": row["score"],
                "llm_reason": row["llm_reason"],
                "extracted": extracted,
                "notified": bool(row["notified"]),
                "user_decision": row["user_decision"],
                "updated_at": row["updated_at"],
                "distance_meters": row["distance_meters"],
                "listing": payload,
            })
        return results

    def get_rejected(self, limit: int | None = None) -> list[dict]:
        query = """
            SELECT
                e.external_id,
                e.hard_pass,
                e.hard_reason,
                e.llm_pass,
                e.llm_reason,
                e.updated_at,
                l.payload,
                m.distance_meters
            FROM evaluations e
            JOIN listings l ON e.external_id = l.external_id
            LEFT JOIN map_cache m ON json_extract(l.payload, '$.address') = m.address
            WHERE e.hard_pass = 0 OR (e.hard_pass = 1 AND e.llm_pass = 0)
            ORDER BY e.updated_at DESC
        """
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self.connection.execute(query).fetchall()
        results = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except Exception:
                payload = {}
            stage = "硬过滤" if not row["hard_pass"] else "语义评估"
            reason = row["hard_reason"] if not row["hard_pass"] else row["llm_reason"]
            results.append({
                "external_id": row["external_id"],
                "stage": stage,
                "reason": reason,
                "updated_at": row["updated_at"],
                "distance_meters": row["distance_meters"],
                "listing": payload,
            })
        return results

    def get_runs(self, limit: int | None = 20) -> list[dict]:
        query = "SELECT * FROM runs ORDER BY id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = self.connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self) -> dict:
        total_listings = self.connection.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        total_evaluations = self.connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        candidates = self.connection.execute(
            "SELECT COUNT(*) FROM evaluations WHERE hard_pass = 1 AND llm_pass = 1"
        ).fetchone()[0]
        rejected = self.connection.execute(
            "SELECT COUNT(*) FROM evaluations WHERE hard_pass = 0 OR llm_pass = 0"
        ).fetchone()[0]
        cached_addresses = self.connection.execute("SELECT COUNT(*) FROM map_cache").fetchone()[0]
        total_runs = self.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        return {
            "total_listings": total_listings,
            "total_evaluations": total_evaluations,
            "candidates": candidates,
            "rejected": rejected,
            "cached_addresses": cached_addresses,
            "total_runs": total_runs,
        }

    def close(self) -> None:
        self.connection.close()
