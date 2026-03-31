"""
SQLite-backed dialog observability pipeline.

This module persists:
1. Raw callback snapshots (from native raw callback logs).
2. Structured callback journal entries (from native dialog callback journal).
3. Correlated dialog steps and their choices assembled from journal events.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_DB_RELATIVE_PATH = os.path.join("Widgets", "Data", "Dialog", "dialog_journal.sqlite3")
DEFAULT_QUERY_LIMIT = 200
DEFAULT_TIMEOUT_MS = 8000
MAX_SEEN_EVENT_KEYS = 4096


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _event_field(event: Any, name: str, index: int, default: Any) -> Any:
    if isinstance(event, dict):
        return event.get(name, default)
    if hasattr(event, name):
        return getattr(event, name)
    if isinstance(event, (tuple, list)) and len(event) > index:
        return event[index]
    return default


def _event_bytes_hex(event: Any, name: str, index: int) -> str:
    data = _event_field(event, name, index, [])
    if data is None:
        return ""
    try:
        return "".join(f"{int(byte) & 0xFF:02x}" for byte in data)
    except Exception:
        return ""


def _event_bytes_list(event: Any, name: str, index: int) -> List[int]:
    data = _event_field(event, name, index, [])
    if data is None:
        return []
    if isinstance(data, str):
        text = data.strip().replace(" ", "")
        if not text:
            return []
        if len(text) % 2 != 0:
            text = "0" + text
        try:
            return [int(text[i : i + 2], 16) for i in range(0, len(text), 2)]
        except Exception:
            return []
    try:
        return [int(x) & 0xFF for x in data]
    except Exception:
        return []


def _u32_at(data: Sequence[int], offset: int) -> int:
    if len(data) < (offset + 4):
        return 0
    return (
        (int(data[offset]) & 0xFF)
        | ((int(data[offset + 1]) & 0xFF) << 8)
        | ((int(data[offset + 2]) & 0xFF) << 16)
        | ((int(data[offset + 3]) & 0xFF) << 24)
    )


def _dialog_raw_hints(message_id: int, w_bytes: Sequence[int]) -> Tuple[int, int, str]:
    # Restep: (dialog_id, agent_id, event_type)
    if message_id == 0x100000A3:  # kDialogButton
        return _u32_at(w_bytes, 8), 0, "recv_choice_raw"
    if message_id == 0x100000A6:  # kDialogBody
        return 0, _u32_at(w_bytes, 4), "recv_body_raw"
    if message_id in (0x30000014, 0x30000015):  # kSendAgentDialog / kSendGadgetDialog
        return _u32_at(w_bytes, 0), 0, "sent_choice_raw"
    return 0, 0, ""


def _normalize_direction_filter(direction: Optional[str]) -> Optional[bool]:
    if direction is None:
        return None
    value = str(direction).strip().lower()
    if not value or value in {"all", "both", "*"}:
        return None
    if value in {"recv", "received", "incoming", "in"}:
        return True
    if value in {"sent", "outgoing", "out"}:
        return False
    raise ValueError(f"Unsupported direction filter: {direction}")


def _parse_message_type_filter(message_type: Optional[Any]) -> Tuple[Optional[int], Optional[str]]:
    if message_type is None:
        return None, None
    if isinstance(message_type, bool):
        raise TypeError("message_type must be int or str, not bool")
    if isinstance(message_type, int):
        return int(message_type), None
    value = str(message_type).strip()
    if not value:
        return None, None
    try:
        return int(value, 0), None
    except ValueError:
        return None, value.lower()


def _normalize_npc_uid_filter(npc_uid: Optional[str]) -> Optional[str]:
    if npc_uid is None:
        return None
    value = str(npc_uid).strip()
    return value if value else None


def _sha1_key(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()


def _resolve_project_root() -> str:
    try:
        import Py4GW

        getter = getattr(Py4GW.Console, "get_projects_path", None)
        if callable(getter):
            root = getter()
            if root:
                return os.path.abspath(root)
    except Exception:
        pass
    return os.getcwd()


def _build_npc_uid(map_id: int, model_id: int, agent_id: int) -> str:
    if not agent_id:
        return ""
    return f"{int(map_id)}:{int(model_id)}:{int(agent_id)}"


def _build_npc_archetype_uid(map_id: int, model_id: int) -> str:
    return f"{int(map_id)}:{int(model_id)}"


def _resolve_map_name(map_id: int) -> str:
    resolved_map_id = int(map_id or 0)
    if resolved_map_id <= 0:
        return ""
    try:
        from .Map import Map
    except Exception:
        try:
            from Map import Map  # type: ignore
        except Exception:
            return ""
    try:
        name = _safe_text(Map.GetMapName(resolved_map_id)).strip()
    except Exception:
        return ""
    if not name or name == "Unknown Map ID":
        return ""
    return name


def _resolve_current_map_id() -> int:
    try:
        from .Map import Map
    except Exception:
        try:
            from Map import Map  # type: ignore
        except Exception:
            return 0
    try:
        return int(Map.GetMapID() or 0)
    except Exception:
        return 0


def _resolve_model_id(agent_id: int) -> int:
    resolved_agent_id = int(agent_id or 0)
    if resolved_agent_id <= 0:
        return 0
    try:
        from .Agent import Agent
    except Exception:
        try:
            from Agent import Agent  # type: ignore
        except Exception:
            return 0
    try:
        return int(Agent.GetModelID(resolved_agent_id) or 0)
    except Exception:
        return 0


def _resolve_npc_name(agent_id: int) -> str:
    resolved_agent_id = int(agent_id or 0)
    if resolved_agent_id <= 0:
        return ""
    try:
        from .Agent import Agent
    except Exception:
        try:
            from Agent import Agent  # type: ignore
        except Exception:
            return ""
    try:
        return _safe_text(Agent.GetNameByID(resolved_agent_id)).strip()
    except Exception:
        return ""


class DialogStepSQLitePipeline:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._db_path: Optional[str] = None
        self._step_timeout_ms = DEFAULT_TIMEOUT_MS
        self._pending_steps: Dict[str, Dict[str, Any]] = {}
        self._body_text_to_dialog_id: Dict[str, int] = {}
        self._dialog_id_to_body_text: Dict[int, Tuple[str, str]] = {}
        self._seen_keys: set[str] = set()
        self._seen_order: List[str] = []

    def configure(
        self,
        *,
        db_path: Optional[str] = None,
        step_timeout_ms: Optional[int] = None,
    ) -> str:
        with self._lock:
            if step_timeout_ms is not None and int(step_timeout_ms) > 0:
                self._step_timeout_ms = int(step_timeout_ms)
            if db_path:
                resolved = os.path.abspath(str(db_path))
                if self._conn is not None and self._db_path and resolved != self._db_path:
                    self._conn.close()
                    self._conn = None
                self._db_path = resolved
            self._ensure_connection()
            return self._db_path or ""

    def get_db_path(self) -> str:
        with self._lock:
            self._ensure_connection()
            return self._db_path or ""

    def sync(
        self,
        *,
        raw_events: Optional[Sequence[Any]] = None,
        callback_journal: Optional[Sequence[Any]] = None,
    ) -> Dict[str, int]:
        with self._lock:
            conn = self._ensure_connection()
            inserted_raw = 0
            inserted_journal = 0
            finalized_steps = 0
            latest_tick = 0
            with conn:
                if raw_events:
                    inserted_raw = self._insert_raw_callbacks(conn, raw_events)
                if callback_journal:
                    inserted_journal, finalized_steps, latest_tick = self._insert_callback_journal(conn, callback_journal)
                if latest_tick:
                    finalized_steps += self._finalize_stale_steps(conn, latest_tick, current_map_id=0)
                self._repair_persisted_step_rows(conn)
                self._backfill_display_names(conn)
            return {
                "raw_inserted": inserted_raw,
                "journal_inserted": inserted_journal,
                "steps_finalized": finalized_steps,
            }

    def flush_pending(self) -> int:
        with self._lock:
            conn = self._ensure_connection()
            finalized = 0
            with conn:
                keys = list(self._pending_steps.keys())
                for npc_uid in keys:
                    if self._finalize_step(conn, npc_uid, reason="flush", end_tick=0):
                        finalized += 1
            return finalized

    def get_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)
        limit = max(1, int(limit))
        offset = max(0, int(offset))

        where: List[str] = []
        params: List[Any] = []
        if incoming_filter is not None:
            where.append("incoming = ?")
            params.append(1 if incoming_filter else 0)
        if message_id_filter is not None:
            where.append("message_id = ?")
            params.append(message_id_filter)
        if event_type_filter:
            where.append("LOWER(event_type) = ?")
            params.append(event_type_filter)

        sql = (
            "SELECT id, tick, ts, message_id, incoming, map_id, map_name, agent_id, npc_name, model_id, npc_uid, "
            "dialog_id, context_dialog_id, event_type, text_raw FROM raw_callbacks"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            conn = self._ensure_connection()
            rows = conn.execute(sql, params).fetchall()
            return [self._raw_row_to_dict(row) for row in rows]

    def clear_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)

        where: List[str] = []
        params: List[Any] = []
        if incoming_filter is not None:
            where.append("incoming = ?")
            params.append(1 if incoming_filter else 0)
        if message_id_filter is not None:
            where.append("message_id = ?")
            params.append(message_id_filter)
        if event_type_filter:
            where.append("LOWER(event_type) = ?")
            params.append(event_type_filter)

        sql = "DELETE FROM raw_callbacks"
        if where:
            sql += " WHERE " + " AND ".join(where)

        with self._lock:
            conn = self._ensure_connection()
            with conn:
                cursor = conn.execute(sql, params)
            return int(cursor.rowcount or 0)

    def get_callback_journal(
        self,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)
        npc_uid_filter = _normalize_npc_uid_filter(npc_uid)
        limit = max(1, int(limit))
        offset = max(0, int(offset))

        where: List[str] = []
        params: List[Any] = []
        if npc_uid_filter:
            where.append("npc_uid = ?")
            params.append(npc_uid_filter)
        if incoming_filter is not None:
            where.append("incoming = ?")
            params.append(1 if incoming_filter else 0)
        if message_id_filter is not None:
            where.append("message_id = ?")
            params.append(message_id_filter)
        if event_type_filter:
            where.append("LOWER(event_type) = ?")
            params.append(event_type_filter)

        sql = (
            "SELECT id, tick, ts, message_id, incoming, dialog_id, context_dialog_id, "
            "agent_id, map_id, map_name, model_id, npc_uid, npc_name, event_type, text_raw, text_decoded "
            "FROM callback_journal"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            conn = self._ensure_connection()
            rows = conn.execute(sql, params).fetchall()
            return [self._callback_row_to_dict(row) for row in rows]

    def clear_callback_journal(
        self,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)
        npc_uid_filter = _normalize_npc_uid_filter(npc_uid)

        where: List[str] = []
        params: List[Any] = []
        if npc_uid_filter:
            where.append("npc_uid = ?")
            params.append(npc_uid_filter)
        if incoming_filter is not None:
            where.append("incoming = ?")
            params.append(1 if incoming_filter else 0)
        if message_id_filter is not None:
            where.append("message_id = ?")
            params.append(message_id_filter)
        if event_type_filter:
            where.append("LOWER(event_type) = ?")
            params.append(event_type_filter)

        sql = "DELETE FROM callback_journal"
        if where:
            sql += " WHERE " + " AND ".join(where)

        with self._lock:
            conn = self._ensure_connection()
            with conn:
                cursor = conn.execute(sql, params)
            return int(cursor.rowcount or 0)

    def get_dialog_steps(
        self,
        *,
        map_id: Optional[int] = None,
        npc_uid_instance: Optional[str] = None,
        npc_uid_archetype: Optional[str] = None,
        body_dialog_id: Optional[int] = None,
        choice_dialog_id: Optional[int] = None,
        limit: int = DEFAULT_QUERY_LIMIT,
        offset: int = 0,
        include_choices: bool = True,
    ) -> List[Dict[str, Any]]:
        limit = max(1, int(limit))
        offset = max(0, int(offset))
        where: List[str] = []
        params: List[Any] = []

        if map_id is not None:
            where.append("t.map_id = ?")
            params.append(int(map_id))
        if npc_uid_instance:
            where.append("t.npc_uid_instance = ?")
            params.append(str(npc_uid_instance))
        if npc_uid_archetype:
            where.append("t.npc_uid_archetype = ?")
            params.append(str(npc_uid_archetype))
        if body_dialog_id is not None:
            where.append("t.body_dialog_id = ?")
            params.append(int(body_dialog_id))
        if choice_dialog_id is not None:
            where.append("EXISTS (SELECT 1 FROM dialog_choices c WHERE c.step_id = t.id AND c.choice_dialog_id = ?)")
            params.append(int(choice_dialog_id))

        sql = (
            "SELECT t.id, t.start_tick, t.end_tick, t.map_id, t.map_name, t.agent_id, t.npc_name, t.model_id, "
            "t.npc_uid_instance, t.npc_uid_archetype, t.body_dialog_id, t.body_text_raw, "
            "t.body_text_decoded, t.selected_dialog_id, t.selected_source_message_id, "
            "t.finalized_reason, t.created_at FROM dialog_steps t"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY t.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            conn = self._ensure_connection()
            rows = conn.execute(sql, params).fetchall()
            steps = [self._step_row_to_dict(row) for row in rows]
            if not include_choices or not steps:
                return steps

            step_ids = [step["id"] for step in steps]
            choices_by_step = self._get_choices_by_step_ids(conn, step_ids)
            for step in steps:
                step["choices"] = choices_by_step.get(step["id"], [])
            return steps

    def get_dialog_step(self, step_id: int, *, include_choices: bool = True) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._ensure_connection()
            row = conn.execute(
                "SELECT id, start_tick, end_tick, map_id, map_name, agent_id, npc_name, model_id, "
                "npc_uid_instance, npc_uid_archetype, body_dialog_id, body_text_raw, "
                "body_text_decoded, selected_dialog_id, selected_source_message_id, "
                "finalized_reason, created_at FROM dialog_steps WHERE id = ?",
                (int(step_id),),
            ).fetchone()
            if row is None:
                return None
            step = self._step_row_to_dict(row)
            if include_choices:
                step["choices"] = self.get_dialog_choices(int(step_id))
            return step

    def get_dialog_choices(self, step_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._ensure_connection()
            rows = conn.execute(
                "SELECT id, step_id, choice_index, choice_dialog_id, choice_text_raw, "
                "choice_text_decoded, skill_id, button_icon, decode_pending, selected, source_message_id "
                "FROM dialog_choices WHERE step_id = ? ORDER BY choice_index ASC, id ASC",
                (int(step_id),),
            ).fetchall()
            return [self._choice_row_to_dict(row) for row in rows]

    def export_raw_callbacks_json(
        self,
        path: str,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> int:
        entries = self.get_raw_callbacks(
            direction=direction,
            message_type=message_type,
            limit=limit,
            offset=offset,
        )
        payload = {
            "generated_at": time.time(),
            "count": len(entries),
            "filters": {
                "direction": direction,
                "message_type": message_type,
                "limit": int(limit),
                "offset": int(offset),
            },
            "entries": entries,
        }
        self._write_json(path, payload)
        return len(entries)

    def export_callback_journal_json(
        self,
        path: str,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> int:
        entries = self.get_callback_journal(
            npc_uid=npc_uid,
            direction=direction,
            message_type=message_type,
            limit=limit,
            offset=offset,
        )
        payload = {
            "generated_at": time.time(),
            "count": len(entries),
            "filters": {
                "npc_uid": npc_uid,
                "direction": direction,
                "message_type": message_type,
                "limit": int(limit),
                "offset": int(offset),
            },
            "entries": entries,
        }
        self._write_json(path, payload)
        return len(entries)

    def export_dialog_steps_json(
        self,
        path: str,
        *,
        map_id: Optional[int] = None,
        npc_uid_instance: Optional[str] = None,
        npc_uid_archetype: Optional[str] = None,
        body_dialog_id: Optional[int] = None,
        choice_dialog_id: Optional[int] = None,
        limit: int = 5000,
        offset: int = 0,
    ) -> int:
        steps = self.get_dialog_steps(
            map_id=map_id,
            npc_uid_instance=npc_uid_instance,
            npc_uid_archetype=npc_uid_archetype,
            body_dialog_id=body_dialog_id,
            choice_dialog_id=choice_dialog_id,
            limit=limit,
            offset=offset,
            include_choices=True,
        )
        payload = {
            "generated_at": time.time(),
            "count": len(steps),
            "filters": {
                "map_id": map_id,
                "npc_uid_instance": npc_uid_instance,
                "npc_uid_archetype": npc_uid_archetype,
                "body_dialog_id": body_dialog_id,
                "choice_dialog_id": choice_dialog_id,
                "limit": int(limit),
                "offset": int(offset),
            },
            "steps": steps,
        }
        self._write_json(path, payload)
        return len(steps)

    def prune_dialog_logs(
        self,
        *,
        max_raw_rows: Optional[int] = None,
        max_journal_rows: Optional[int] = None,
        max_step_rows: Optional[int] = None,
        older_than_days: Optional[float] = None,
    ) -> Dict[str, int]:
        removed_raw = 0
        removed_journal = 0
        removed_steps = 0
        removed_choices = 0

        with self._lock:
            conn = self._ensure_connection()
            with conn:
                if older_than_days is not None and float(older_than_days) > 0:
                    cutoff = float(time.time()) - float(older_than_days) * 86400.0
                    removed_raw += int(conn.execute("DELETE FROM raw_callbacks WHERE ts < ?", (cutoff,)).rowcount or 0)
                    removed_journal += int(conn.execute("DELETE FROM callback_journal WHERE ts < ?", (cutoff,)).rowcount or 0)
                    old_step_rows = conn.execute(
                        "SELECT id FROM dialog_steps WHERE created_at < ? ORDER BY id ASC",
                        (cutoff,),
                    ).fetchall()
                    old_step_ids = [int(row[0]) for row in old_step_rows]
                    if old_step_ids:
                        removed_choices += self._delete_choices_for_step_ids(conn, old_step_ids)
                        removed_steps += int(
                            conn.execute(
                                f"DELETE FROM dialog_steps WHERE id IN ({','.join('?' for _ in old_step_ids)})",
                                old_step_ids,
                            ).rowcount
                            or 0
                        )

                if max_raw_rows is not None and int(max_raw_rows) >= 0:
                    removed_raw += self._trim_table(conn, "raw_callbacks", int(max_raw_rows))

                if max_journal_rows is not None and int(max_journal_rows) >= 0:
                    removed_journal += self._trim_table(conn, "callback_journal", int(max_journal_rows))

                if max_step_rows is not None and int(max_step_rows) >= 0:
                    overflow_ids = self._overflow_ids(conn, "dialog_steps", int(max_step_rows))
                    if overflow_ids:
                        removed_choices += self._delete_choices_for_step_ids(conn, overflow_ids)
                        removed_steps += int(
                            conn.execute(
                                f"DELETE FROM dialog_steps WHERE id IN ({','.join('?' for _ in overflow_ids)})",
                                overflow_ids,
                            ).rowcount
                            or 0
                        )

        return {
            "removed_raw_callbacks": removed_raw,
            "removed_callback_journal": removed_journal,
            "removed_dialog_steps": removed_steps,
            "removed_dialog_choices": removed_choices,
        }

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        if not self._db_path:
            self._db_path = os.path.join(_resolve_project_root(), DEFAULT_DB_RELATIVE_PATH)
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(self._db_path, timeout=5.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema(conn)
        self._conn = conn
        return conn

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        self._create_base_schema(conn)
        self._migrate_legacy_step_schema(conn)
        self._ensure_display_name_columns(conn)
        self._create_current_step_schema(conn)
        self._create_display_name_indexes(conn)
        self._backfill_display_names(conn)

    def _create_base_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                tick INTEGER NOT NULL,
                ts REAL NOT NULL,
                message_id INTEGER NOT NULL,
                incoming INTEGER NOT NULL,
                is_frame_message INTEGER NOT NULL DEFAULT 0,
                frame_id INTEGER NOT NULL DEFAULT 0,
                w_bytes_hex TEXT NOT NULL DEFAULT '',
                l_bytes_hex TEXT NOT NULL DEFAULT '',
                map_id INTEGER NOT NULL DEFAULT 0,
                map_name TEXT NOT NULL DEFAULT '',
                agent_id INTEGER NOT NULL DEFAULT 0,
                npc_name TEXT NOT NULL DEFAULT '',
                model_id INTEGER NOT NULL DEFAULT 0,
                npc_uid TEXT NOT NULL DEFAULT '',
                dialog_id INTEGER NOT NULL DEFAULT 0,
                context_dialog_id INTEGER NOT NULL DEFAULT 0,
                event_type TEXT NOT NULL DEFAULT '',
                text_raw TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS callback_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                tick INTEGER NOT NULL,
                ts REAL NOT NULL,
                message_id INTEGER NOT NULL,
                incoming INTEGER NOT NULL,
                dialog_id INTEGER NOT NULL DEFAULT 0,
                context_dialog_id INTEGER NOT NULL DEFAULT 0,
                agent_id INTEGER NOT NULL DEFAULT 0,
                map_id INTEGER NOT NULL DEFAULT 0,
                map_name TEXT NOT NULL DEFAULT '',
                model_id INTEGER NOT NULL DEFAULT 0,
                npc_uid TEXT NOT NULL DEFAULT '',
                npc_name TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                text_raw TEXT NOT NULL DEFAULT '',
                text_decoded TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_raw_tick ON raw_callbacks(tick);
            CREATE INDEX IF NOT EXISTS idx_raw_message ON raw_callbacks(message_id);
            CREATE INDEX IF NOT EXISTS idx_raw_npc_uid ON raw_callbacks(npc_uid);
            CREATE INDEX IF NOT EXISTS idx_raw_map_id ON raw_callbacks(map_id);

            CREATE INDEX IF NOT EXISTS idx_journal_tick ON callback_journal(tick);
            CREATE INDEX IF NOT EXISTS idx_journal_message ON callback_journal(message_id);
            CREATE INDEX IF NOT EXISTS idx_journal_npc_uid ON callback_journal(npc_uid);
            CREATE INDEX IF NOT EXISTS idx_journal_event_type ON callback_journal(event_type);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dialog_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_tick INTEGER NOT NULL,
                end_tick INTEGER NOT NULL DEFAULT 0,
                map_id INTEGER NOT NULL DEFAULT 0,
                map_name TEXT NOT NULL DEFAULT '',
                agent_id INTEGER NOT NULL DEFAULT 0,
                npc_name TEXT NOT NULL DEFAULT '',
                model_id INTEGER NOT NULL DEFAULT 0,
                npc_uid_instance TEXT NOT NULL DEFAULT '',
                npc_uid_archetype TEXT NOT NULL DEFAULT '',
                body_dialog_id INTEGER NOT NULL DEFAULT 0,
                body_text_raw TEXT NOT NULL DEFAULT '',
                body_text_decoded TEXT NOT NULL DEFAULT '',
                selected_dialog_id INTEGER NOT NULL DEFAULT 0,
                selected_source_message_id INTEGER NOT NULL DEFAULT 0,
                finalized_reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )

    def _create_current_step_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dialog_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                step_id INTEGER NOT NULL,
                choice_index INTEGER NOT NULL DEFAULT 0,
                choice_dialog_id INTEGER NOT NULL DEFAULT 0,
                choice_text_raw TEXT NOT NULL DEFAULT '',
                choice_text_decoded TEXT NOT NULL DEFAULT '',
                skill_id INTEGER NOT NULL DEFAULT 0,
                button_icon INTEGER NOT NULL DEFAULT 0,
                decode_pending INTEGER NOT NULL DEFAULT 0,
                selected INTEGER NOT NULL DEFAULT 0,
                source_message_id INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(step_id) REFERENCES dialog_steps(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_steps_map ON dialog_steps(map_id);
            CREATE INDEX IF NOT EXISTS idx_steps_npc_instance ON dialog_steps(npc_uid_instance);
            CREATE INDEX IF NOT EXISTS idx_steps_npc_archetype ON dialog_steps(npc_uid_archetype);
            CREATE INDEX IF NOT EXISTS idx_steps_body_dialog_id ON dialog_steps(body_dialog_id);
            CREATE INDEX IF NOT EXISTS idx_steps_created_at ON dialog_steps(created_at);
            CREATE INDEX IF NOT EXISTS idx_steps_map_name ON dialog_steps(map_name);
            CREATE INDEX IF NOT EXISTS idx_steps_npc_name ON dialog_steps(npc_name);

            CREATE INDEX IF NOT EXISTS idx_choices_step ON dialog_choices(step_id);
            CREATE INDEX IF NOT EXISTS idx_choices_dialog_id ON dialog_choices(choice_dialog_id);
            CREATE INDEX IF NOT EXISTS idx_choices_selected ON dialog_choices(selected);
            """
        )

    def _ensure_display_name_columns(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "raw_callbacks", "map_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "raw_callbacks", "npc_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "callback_journal", "map_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "callback_journal", "npc_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "dialog_steps", "map_name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "dialog_steps", "npc_name", "TEXT NOT NULL DEFAULT ''")

    def _ensure_column(self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}
        if column_name in columns:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _backfill_display_names(self, conn: sqlite3.Connection) -> None:
        self._backfill_table_display_names(conn, "raw_callbacks")
        self._backfill_table_display_names(conn, "callback_journal")
        self._backfill_table_display_names(conn, "dialog_steps")

    def _create_display_name_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_map_name ON raw_callbacks(map_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_npc_name ON raw_callbacks(npc_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_map_name ON callback_journal(map_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_npc_name ON callback_journal(npc_name)")

    def _backfill_table_display_names(self, conn: sqlite3.Connection, table_name: str) -> None:
        rows = conn.execute(
            f"""
            SELECT id, map_id, IFNULL(map_name, ''), agent_id, IFNULL(npc_name, '')
            FROM {table_name}
            WHERE IFNULL(map_name, '') = '' OR IFNULL(npc_name, '') = ''
            """
        ).fetchall()
        if not rows:
            return

        map_cache: Dict[int, str] = {}
        npc_cache: Dict[int, str] = {}
        updates: List[Tuple[str, str, int]] = []
        for row_id, map_id, map_name, agent_id, npc_name in rows:
            resolved_map_id = int(map_id or 0)
            resolved_agent_id = int(agent_id or 0)
            next_map_name = _safe_text(map_name)
            next_npc_name = _safe_text(npc_name)
            if not next_map_name and resolved_map_id > 0:
                next_map_name = map_cache.setdefault(resolved_map_id, _resolve_map_name(resolved_map_id))
            if not next_npc_name and resolved_agent_id > 0:
                next_npc_name = npc_cache.setdefault(resolved_agent_id, _resolve_npc_name(resolved_agent_id))
            if next_map_name != _safe_text(map_name) or next_npc_name != _safe_text(npc_name):
                updates.append((next_map_name, next_npc_name, int(row_id)))
        if updates:
            conn.executemany(
                f"UPDATE {table_name} SET map_name = ?, npc_name = ? WHERE id = ?",
                updates,
            )

    def _migrate_legacy_step_schema(self, conn: sqlite3.Connection) -> None:
        table_names = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "dialog_turns" not in table_names and "dialog_choices" not in table_names:
            return

        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            if "dialog_turns" in table_names:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dialog_steps (
                        id, start_tick, end_tick, map_id, agent_id, model_id,
                        npc_uid_instance, npc_uid_archetype, body_dialog_id,
                        body_text_raw, body_text_decoded, selected_dialog_id,
                        selected_source_message_id, finalized_reason, created_at
                    )
                    SELECT
                        id, start_tick, end_tick, map_id, agent_id, model_id,
                        npc_uid_instance, npc_uid_archetype, body_dialog_id,
                        body_text_raw, body_text_decoded, selected_dialog_id,
                        selected_source_message_id, finalized_reason, created_at
                    FROM dialog_turns
                    """
                )
                conn.execute("DROP TABLE dialog_turns")

            if "dialog_choices" in table_names:
                columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(dialog_choices)")}
                if "turn_id" in columns and "step_id" not in columns:
                    conn.execute("DROP INDEX IF EXISTS idx_choices_turn")
                    conn.execute("DROP INDEX IF EXISTS idx_choices_step")
                    conn.execute("ALTER TABLE dialog_choices RENAME TO dialog_choices_legacy")
                    conn.execute(
                        """
                        CREATE TABLE dialog_choices (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            step_id INTEGER NOT NULL,
                            choice_index INTEGER NOT NULL DEFAULT 0,
                            choice_dialog_id INTEGER NOT NULL DEFAULT 0,
                            choice_text_raw TEXT NOT NULL DEFAULT '',
                            choice_text_decoded TEXT NOT NULL DEFAULT '',
                            skill_id INTEGER NOT NULL DEFAULT 0,
                            button_icon INTEGER NOT NULL DEFAULT 0,
                            decode_pending INTEGER NOT NULL DEFAULT 0,
                            selected INTEGER NOT NULL DEFAULT 0,
                            source_message_id INTEGER NOT NULL DEFAULT 0,
                            FOREIGN KEY(step_id) REFERENCES dialog_steps(id) ON DELETE CASCADE
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT INTO dialog_choices (
                            id, step_id, choice_index, choice_dialog_id, choice_text_raw,
                            choice_text_decoded, skill_id, button_icon, decode_pending,
                            selected, source_message_id
                        )
                        SELECT
                            c.id, c.turn_id, c.choice_index, c.choice_dialog_id, c.choice_text_raw,
                            c.choice_text_decoded, c.skill_id, c.button_icon, c.decode_pending,
                            c.selected, c.source_message_id
                        FROM dialog_choices_legacy c
                        WHERE EXISTS (
                            SELECT 1
                            FROM dialog_steps s
                            WHERE s.id = c.turn_id
                        )
                        """
                    )
                    conn.execute("DROP TABLE dialog_choices_legacy")
        finally:
            conn.execute("PRAGMA foreign_keys = ON")

    def _insert_raw_callbacks(self, conn: sqlite3.Connection, raw_events: Sequence[Any]) -> int:
        inserted = 0
        for event in raw_events:
            tick = _to_int(_event_field(event, "tick", 0, 0), 0)
            message_id = _to_int(_event_field(event, "message_id", 1, 0), 0)
            incoming = bool(_event_field(event, "incoming", 2, False))
            is_frame_message = bool(_event_field(event, "is_frame_message", 3, False))
            frame_id = _to_int(_event_field(event, "frame_id", 4, 0), 0)
            w_bytes = _event_bytes_list(event, "w_bytes", 5)
            w_bytes_hex = _event_bytes_hex(event, "w_bytes", 5)
            l_bytes_hex = _event_bytes_hex(event, "l_bytes", 6)
            dialog_id_hint, agent_id_hint, event_type_hint = _dialog_raw_hints(message_id, w_bytes)
            map_id = _to_int(_event_field(event, "map_id", 7, 0), 0)
            if map_id <= 0:
                map_id = _resolve_current_map_id()
            agent_id = _to_int(_event_field(event, "agent_id", 8, agent_id_hint), 0) or agent_id_hint
            model_id = _to_int(_event_field(event, "model_id", 9, 0), 0)
            if model_id <= 0 and agent_id > 0:
                model_id = _resolve_model_id(agent_id)
            npc_uid = _safe_text(_event_field(event, "npc_uid", 10, ""))
            if not npc_uid:
                npc_uid = _build_npc_uid(map_id, model_id, agent_id)
            dialog_id = _to_int(_event_field(event, "dialog_id", 11, dialog_id_hint), 0) or dialog_id_hint
            context_dialog_id = _to_int(_event_field(event, "context_dialog_id", 12, 0), 0)
            event_type = _safe_text(_event_field(event, "event_type", 13, event_type_hint)).strip().lower()
            if not event_type:
                event_type = event_type_hint
            text_raw = _safe_text(_event_field(event, "text_raw", 14, _event_field(event, "text", 15, "")))
            map_name = _safe_text(_event_field(event, "map_name", 16, "")).strip() or _resolve_map_name(map_id)
            npc_name = _safe_text(_event_field(event, "npc_name", 17, "")).strip() or _resolve_npc_name(agent_id)
            event_key = _sha1_key(
                f"raw|{tick}|{message_id}|{1 if incoming else 0}|{1 if is_frame_message else 0}|"
                f"{frame_id}|{w_bytes_hex}|{l_bytes_hex}"
            )
            if self._key_seen(event_key):
                continue
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO raw_callbacks (
                    event_key, tick, ts, message_id, incoming, is_frame_message, frame_id,
                    w_bytes_hex, l_bytes_hex, map_id, map_name, agent_id, npc_name, model_id, npc_uid,
                    dialog_id, context_dialog_id, event_type, text_raw
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    tick,
                    float(time.time()),
                    message_id,
                    1 if incoming else 0,
                    1 if is_frame_message else 0,
                    frame_id,
                    w_bytes_hex,
                    l_bytes_hex,
                    map_id,
                    map_name,
                    agent_id,
                    npc_name,
                    model_id,
                    npc_uid,
                    dialog_id,
                    context_dialog_id,
                    event_type,
                    text_raw,
                ),
            )
            if int(cursor.rowcount or 0) > 0:
                inserted += 1
                self._remember_key(event_key)
        return inserted

    def _insert_callback_journal(
        self,
        conn: sqlite3.Connection,
        callback_journal: Sequence[Any],
    ) -> Tuple[int, int, int]:
        inserted = 0
        finalized = 0
        latest_tick = 0
        for event in callback_journal:
            normalized = self._normalize_callback_event(event)
            latest_tick = max(latest_tick, normalized["tick"])
            event_key = _sha1_key(
                "journal|{tick}|{message_id}|{incoming}|{dialog_id}|{context_dialog_id}|"
                "{agent_id}|{map_id}|{model_id}|{npc_uid}|{event_type}|{text_raw}".format(
                    tick=normalized["tick"],
                    message_id=normalized["message_id"],
                    incoming=1 if normalized["incoming"] else 0,
                    dialog_id=normalized["dialog_id"],
                    context_dialog_id=normalized["context_dialog_id"],
                    agent_id=normalized["agent_id"],
                    map_id=normalized["map_id"],
                    model_id=normalized["model_id"],
                    npc_uid=normalized["npc_uid"],
                    event_type=normalized["event_type"],
                    text_raw=normalized["text_raw"],
                )
            )
            if self._key_seen(event_key):
                continue
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO callback_journal (
                    event_key, tick, ts, message_id, incoming, dialog_id, context_dialog_id,
                    agent_id, map_id, map_name, model_id, npc_uid, npc_name, event_type, text_raw, text_decoded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    normalized["tick"],
                    float(time.time()),
                    normalized["message_id"],
                    1 if normalized["incoming"] else 0,
                    normalized["dialog_id"],
                    normalized["context_dialog_id"],
                    normalized["agent_id"],
                    normalized["map_id"],
                    normalized["map_name"],
                    normalized["model_id"],
                    normalized["npc_uid"],
                    normalized["npc_name"],
                    normalized["event_type"],
                    normalized["text_raw"],
                    normalized["text_decoded"],
                ),
            )
            if int(cursor.rowcount or 0) <= 0:
                continue
            inserted += 1
            self._remember_key(event_key)
            finalized += self._process_step_event(conn, normalized)
        return inserted, finalized, latest_tick

    def _normalize_callback_event(self, event: Any) -> Dict[str, Any]:
        tick = _to_int(_event_field(event, "tick", 0, 0), 0)
        message_id = _to_int(_event_field(event, "message_id", 1, 0), 0)
        incoming = bool(_event_field(event, "incoming", 2, False))
        dialog_id = _to_int(_event_field(event, "dialog_id", 3, 0), 0)
        context_dialog_id = _to_int(_event_field(event, "context_dialog_id", 4, 0), 0)
        agent_id = _to_int(_event_field(event, "agent_id", 5, 0), 0)
        map_id = _to_int(_event_field(event, "map_id", 6, 0), 0)
        model_id = _to_int(_event_field(event, "model_id", 7, 0), 0)
        npc_uid = _safe_text(_event_field(event, "npc_uid", 8, ""))
        event_type = _safe_text(_event_field(event, "event_type", 9, "")).strip().lower()
        text_raw = _safe_text(_event_field(event, "text", 10, ""))
        map_name = _safe_text(_event_field(event, "map_name", 11, "")).strip()
        npc_name = _safe_text(_event_field(event, "npc_name", 12, "")).strip()
        if not npc_uid:
            npc_uid = _build_npc_uid(map_id, model_id, agent_id)
        if not map_name:
            map_name = _resolve_map_name(map_id)
        if not npc_name:
            npc_name = _resolve_npc_name(agent_id)
        return {
            "tick": tick,
            "message_id": message_id,
            "incoming": incoming,
            "dialog_id": dialog_id,
            "context_dialog_id": context_dialog_id,
            "agent_id": agent_id,
            "map_id": map_id,
            "map_name": map_name,
            "model_id": model_id,
            "npc_uid": npc_uid,
            "npc_name": npc_name,
            "event_type": event_type,
            "text_raw": text_raw,
            "text_decoded": text_raw,
        }

    def _process_step_event(self, conn: sqlite3.Connection, event: Dict[str, Any]) -> int:
        finalized = self._finalize_stale_steps(conn, event["tick"], current_map_id=event["map_id"])
        event_type = event["event_type"]
        step_key = self._event_step_key(event)
        if not step_key:
            return finalized

        if event_type == "recv_body":
            self._remember_body_text_mapping(event)
            existing = self._pending_steps.get(step_key)
            if existing is not None:
                if self._should_hydrate_pending_step(existing, event):
                    self._hydrate_pending_step(existing, event)
                    return finalized
                if self._finalize_step(conn, step_key, reason="next_body", end_tick=event["tick"]):
                    finalized += 1
            self._pending_steps[step_key] = self._new_step_from_body(event)
            return finalized

        if event_type == "recv_choice":
            step = self._pending_steps.get(step_key)
            if step is None:
                if int(event.get("context_dialog_id", 0) or 0) == 0:
                    # Ignore contextless bootstrap choices; they create unresolved steps.
                    return finalized
                step = self._new_step_from_choice(event)
                self._pending_steps[step_key] = step
            self._hydrate_step_from_choice_context(step, event)
            self._append_choice(step, event)
            step["last_tick"] = event["tick"]
            return finalized

        if event_type == "sent_choice":
            step = self._pending_steps.get(step_key)
            if step is None:
                if int(event.get("context_dialog_id", 0) or 0) == 0:
                    # Ignore contextless bootstrap sends; wait for a resolvable step context.
                    return finalized
                step = self._new_step_from_choice(event)
                self._pending_steps[step_key] = step
            self._hydrate_step_from_choice_context(step, event)
            step["selected_dialog_id"] = event["dialog_id"]
            step["selected_source_message_id"] = event["message_id"]
            self._mark_choice_selected(step, event["dialog_id"], event["message_id"], event["text_decoded"])
            step["last_tick"] = event["tick"]
            if self._finalize_step(conn, step_key, reason="sent_choice", end_tick=event["tick"]):
                finalized += 1
            return finalized

        step = self._pending_steps.get(step_key)
        if step is not None:
            step["last_tick"] = max(step.get("last_tick", 0), event["tick"])
        return finalized

    def _event_step_key(self, event: Dict[str, Any]) -> str:
        npc_uid = _safe_text(event.get("npc_uid", "")).strip()
        if npc_uid:
            return npc_uid
        agent_id = int(event.get("agent_id", 0) or 0)
        if agent_id:
            return _build_npc_uid(
                int(event.get("map_id", 0) or 0),
                int(event.get("model_id", 0) or 0),
                agent_id,
            )
        return ""

    def _new_step_from_body(self, event: Dict[str, Any]) -> Dict[str, Any]:
        body_dialog_id = event["dialog_id"] or event["context_dialog_id"]
        if body_dialog_id == 0:
            inferred = self._infer_dialog_id_from_body_text(event.get("text_decoded", ""))
            if inferred:
                body_dialog_id = inferred
        npc_uid_instance = self._event_step_key(event)
        body_text_raw = event["text_raw"]
        body_text_decoded = event["text_decoded"]
        if body_dialog_id != 0 and (not body_text_raw or not body_text_decoded):
            cached_raw, cached_decoded = self._cached_body_text_for_dialog(body_dialog_id)
            body_text_raw = body_text_raw or cached_raw
            body_text_decoded = body_text_decoded or cached_decoded
        return {
            "start_tick": event["tick"],
            "last_tick": event["tick"],
            "map_id": event["map_id"],
            "map_name": event.get("map_name", "") or _resolve_map_name(int(event["map_id"] or 0)),
            "agent_id": event["agent_id"],
            "npc_name": event.get("npc_name", "") or _resolve_npc_name(int(event["agent_id"] or 0)),
            "model_id": event["model_id"],
            "npc_uid_instance": npc_uid_instance,
            "npc_uid_archetype": _build_npc_archetype_uid(event["map_id"], event["model_id"]),
            "body_dialog_id": body_dialog_id,
            "body_text_raw": body_text_raw,
            "body_text_decoded": body_text_decoded,
            "selected_dialog_id": 0,
            "selected_source_message_id": 0,
            "choices": [],
        }

    def _new_step_from_choice(self, event: Dict[str, Any]) -> Dict[str, Any]:
        npc_uid_instance = self._event_step_key(event)
        body_dialog_id = event["context_dialog_id"] if event["context_dialog_id"] else 0
        body_text_raw = ""
        body_text_decoded = ""
        if body_dialog_id != 0:
            body_text_raw, body_text_decoded = self._cached_body_text_for_dialog(body_dialog_id)
        return {
            "start_tick": event["tick"],
            "last_tick": event["tick"],
            "map_id": event["map_id"],
            "map_name": event.get("map_name", "") or _resolve_map_name(int(event["map_id"] or 0)),
            "agent_id": event["agent_id"],
            "npc_name": event.get("npc_name", "") or _resolve_npc_name(int(event["agent_id"] or 0)),
            "model_id": event["model_id"],
            "npc_uid_instance": npc_uid_instance,
            "npc_uid_archetype": _build_npc_archetype_uid(event["map_id"], event["model_id"]),
            "body_dialog_id": body_dialog_id,
            "body_text_raw": body_text_raw,
            "body_text_decoded": body_text_decoded,
            "selected_dialog_id": 0,
            "selected_source_message_id": 0,
            "choices": [],
        }

    def _append_choice(self, step: Dict[str, Any], event: Dict[str, Any]) -> None:
        step["choices"].append(
            {
                "choice_index": len(step["choices"]),
                "choice_dialog_id": event["dialog_id"],
                "choice_text_raw": event["text_raw"],
                "choice_text_decoded": event["text_decoded"],
                "skill_id": 0,
                "button_icon": 0,
                "decode_pending": 0,
                "selected": 0,
                "source_message_id": event["message_id"],
            }
        )

    def _hydrate_step_from_choice_context(self, step: Dict[str, Any], event: Dict[str, Any]) -> None:
        context_dialog_id = int(event.get("context_dialog_id", 0) or 0)
        if int(step.get("body_dialog_id", 0) or 0) == 0 and context_dialog_id != 0:
            step["body_dialog_id"] = context_dialog_id
        if int(step.get("map_id", 0) or 0) == 0:
            step["map_id"] = int(event.get("map_id", 0) or 0)
        if not _safe_text(step.get("map_name", "")):
            step["map_name"] = _safe_text(event.get("map_name", "")) or _resolve_map_name(int(event.get("map_id", 0) or 0))
        if int(step.get("agent_id", 0) or 0) == 0:
            step["agent_id"] = int(event.get("agent_id", 0) or 0)
        if not _safe_text(step.get("npc_name", "")):
            step["npc_name"] = _safe_text(event.get("npc_name", "")) or _resolve_npc_name(int(event.get("agent_id", 0) or 0))
        if int(step.get("model_id", 0) or 0) == 0:
            step["model_id"] = int(event.get("model_id", 0) or 0)
        if not _safe_text(step.get("npc_uid_instance", "")):
            step["npc_uid_instance"] = self._event_step_key(event)
        if not _safe_text(step.get("npc_uid_archetype", "")):
            step["npc_uid_archetype"] = _build_npc_archetype_uid(
                int(event.get("map_id", 0) or 0),
                int(event.get("model_id", 0) or 0),
            )
        dialog_id = int(step.get("body_dialog_id", 0) or 0)
        if dialog_id != 0 and (not _safe_text(step.get("body_text_raw")) or not _safe_text(step.get("body_text_decoded"))):
            cached_raw, cached_decoded = self._cached_body_text_for_dialog(dialog_id)
            if cached_raw and not _safe_text(step.get("body_text_raw")):
                step["body_text_raw"] = cached_raw
            if cached_decoded and not _safe_text(step.get("body_text_decoded")):
                step["body_text_decoded"] = cached_decoded

    def _should_hydrate_pending_step(self, step: Dict[str, Any], body_event: Dict[str, Any]) -> bool:
        current_body_id = int(step.get("body_dialog_id", 0) or 0)
        incoming_body_id = int((body_event.get("dialog_id", 0) or body_event.get("context_dialog_id", 0)) or 0)
        current_text = _safe_text(step.get("body_text_decoded", "")).strip()
        incoming_text = _safe_text(body_event.get("text_decoded", "")).strip()
        if current_body_id == 0 and (incoming_body_id != 0 or incoming_text):
            return True
        if current_body_id != 0 and incoming_body_id == current_body_id:
            if incoming_text and (not current_text or incoming_text == current_text):
                return True
        return False

    def _hydrate_pending_step(self, step: Dict[str, Any], body_event: Dict[str, Any]) -> None:
        incoming_body_id = int((body_event.get("dialog_id", 0) or body_event.get("context_dialog_id", 0)) or 0)
        if incoming_body_id != 0:
            step["body_dialog_id"] = incoming_body_id
        incoming_raw = _safe_text(body_event.get("text_raw", ""))
        incoming_decoded = _safe_text(body_event.get("text_decoded", ""))
        if incoming_raw and not _safe_text(step.get("body_text_raw", "")):
            step["body_text_raw"] = incoming_raw
        if incoming_decoded and not _safe_text(step.get("body_text_decoded", "")):
            step["body_text_decoded"] = incoming_decoded
        if int(step.get("map_id", 0) or 0) == 0:
            step["map_id"] = int(body_event.get("map_id", 0) or 0)
        if not _safe_text(step.get("map_name", "")):
            step["map_name"] = _safe_text(body_event.get("map_name", "")) or _resolve_map_name(int(body_event.get("map_id", 0) or 0))
        if int(step.get("agent_id", 0) or 0) == 0:
            step["agent_id"] = int(body_event.get("agent_id", 0) or 0)
        if not _safe_text(step.get("npc_name", "")):
            step["npc_name"] = _safe_text(body_event.get("npc_name", "")) or _resolve_npc_name(int(body_event.get("agent_id", 0) or 0))
        if int(step.get("model_id", 0) or 0) == 0:
            step["model_id"] = int(body_event.get("model_id", 0) or 0)
        if not _safe_text(step.get("npc_uid_instance", "")):
            step["npc_uid_instance"] = self._event_step_key(body_event)
        if not _safe_text(step.get("npc_uid_archetype", "")):
            step["npc_uid_archetype"] = _build_npc_archetype_uid(
                int(body_event.get("map_id", 0) or 0),
                int(body_event.get("model_id", 0) or 0),
            )
        step["last_tick"] = max(int(step.get("last_tick", 0) or 0), int(body_event.get("tick", 0) or 0))

    def _remember_body_text_mapping(self, body_event: Dict[str, Any]) -> None:
        dialog_id = int((body_event.get("dialog_id", 0) or body_event.get("context_dialog_id", 0)) or 0)
        raw = _safe_text(body_event.get("text_raw", ""))
        decoded = _safe_text(body_event.get("text_decoded", ""))
        if dialog_id != 0 and (raw or decoded):
            self._dialog_id_to_body_text[dialog_id] = (raw, decoded)
            key = self._body_text_key(decoded)
            if key:
                self._body_text_to_dialog_id[key] = dialog_id

    def _cached_body_text_for_dialog(self, dialog_id: int) -> Tuple[str, str]:
        value = self._dialog_id_to_body_text.get(int(dialog_id))
        if not value:
            return "", ""
        return _safe_text(value[0]), _safe_text(value[1])

    def _body_text_key(self, text: Any) -> str:
        value = _safe_text(text).strip()
        return value.lower() if value else ""

    def _infer_dialog_id_from_body_text(self, text: Any) -> int:
        key = self._body_text_key(text)
        if not key:
            return 0
        return int(self._body_text_to_dialog_id.get(key, 0) or 0)

    def _mark_choice_selected(self, step: Dict[str, Any], dialog_id: int, message_id: int, fallback_text: str) -> None:
        matched = False
        for choice in step["choices"]:
            if int(choice.get("choice_dialog_id", 0)) == int(dialog_id):
                choice["selected"] = 1
                choice["source_message_id"] = message_id
                matched = True
        if matched:
            return
        step["choices"].append(
            {
                "choice_index": len(step["choices"]),
                "choice_dialog_id": int(dialog_id),
                "choice_text_raw": _safe_text(fallback_text),
                "choice_text_decoded": _safe_text(fallback_text),
                "skill_id": 0,
                "button_icon": 0,
                "decode_pending": 0,
                "selected": 1,
                "source_message_id": int(message_id),
            }
        )

    def _finalize_stale_steps(self, conn: sqlite3.Connection, current_tick: int, current_map_id: int) -> int:
        finalized = 0
        keys = list(self._pending_steps.keys())
        for key in keys:
            step = self._pending_steps.get(key)
            if step is None:
                continue
            last_tick = int(step.get("last_tick", 0) or 0)
            map_id = int(step.get("map_id", 0) or 0)
            if current_map_id and map_id and map_id != current_map_id:
                if self._finalize_step(conn, key, reason="map_change", end_tick=current_tick):
                    finalized += 1
                continue
            if current_tick and last_tick and (current_tick - last_tick) > self._step_timeout_ms:
                if self._finalize_step(conn, key, reason="timeout", end_tick=current_tick):
                    finalized += 1
        return finalized

    def _finalize_step(self, conn: sqlite3.Connection, key: str, *, reason: str, end_tick: int) -> bool:
        step = self._pending_steps.pop(key, None)
        if step is None:
            return False

        body_dialog_id = int(step.get("body_dialog_id", 0) or 0)
        body_text_raw = _safe_text(step.get("body_text_raw", ""))
        body_text_decoded = _safe_text(step.get("body_text_decoded", ""))
        selected_dialog_id = int(step.get("selected_dialog_id", 0) or 0)
        choices = list(step.get("choices", []))
        map_id = int(step.get("map_id", 0) or 0)
        agent_id = int(step.get("agent_id", 0) or 0)
        model_id = int(step.get("model_id", 0) or 0)
        map_name = _safe_text(step.get("map_name", "")).strip() or _resolve_map_name(map_id)
        npc_name = _safe_text(step.get("npc_name", "")).strip() or _resolve_npc_name(agent_id)

        if body_dialog_id == 0 and body_text_decoded:
            inferred_id = self._infer_dialog_id_from_body_text(body_text_decoded)
            if inferred_id:
                body_dialog_id = inferred_id
                step["body_dialog_id"] = inferred_id

        if body_dialog_id != 0 and (not body_text_raw or not body_text_decoded):
            cached_raw, cached_decoded = self._cached_body_text_for_dialog(body_dialog_id)
            if cached_raw and not body_text_raw:
                body_text_raw = cached_raw
                step["body_text_raw"] = cached_raw
            if cached_decoded and not body_text_decoded:
                body_text_decoded = cached_decoded
                step["body_text_decoded"] = cached_decoded

        # Drop pure bootstrap noise: no body, no text, no choices, no user selection.
        if body_dialog_id == 0 and not body_text_decoded.strip() and not choices and selected_dialog_id == 0:
            return False

        cursor = conn.execute(
            """
            INSERT INTO dialog_steps (
                start_tick, end_tick, map_id, map_name, agent_id, npc_name, model_id, npc_uid_instance, npc_uid_archetype,
                body_dialog_id, body_text_raw, body_text_decoded, selected_dialog_id,
                selected_source_message_id, finalized_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(step.get("start_tick", 0) or 0),
                int(end_tick or step.get("last_tick", 0) or 0),
                map_id,
                map_name,
                agent_id,
                npc_name,
                model_id,
                _safe_text(step.get("npc_uid_instance", "")),
                _safe_text(step.get("npc_uid_archetype", "")),
                body_dialog_id,
                body_text_raw,
                body_text_decoded,
                selected_dialog_id,
                int(step.get("selected_source_message_id", 0) or 0),
                _safe_text(reason),
                float(time.time()),
            ),
        )
        step_id = int(cursor.lastrowid or 0)
        if step_id <= 0:
            return False

        for index, choice in enumerate(step.get("choices", [])):
            conn.execute(
                """
                INSERT INTO dialog_choices (
                    step_id, choice_index, choice_dialog_id, choice_text_raw, choice_text_decoded,
                    skill_id, button_icon, decode_pending, selected, source_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    int(choice.get("choice_index", index)),
                    int(choice.get("choice_dialog_id", 0) or 0),
                    _safe_text(choice.get("choice_text_raw", "")),
                    _safe_text(choice.get("choice_text_decoded", "")),
                    int(choice.get("skill_id", 0) or 0),
                    int(choice.get("button_icon", 0) or 0),
                    1 if bool(choice.get("decode_pending", False)) else 0,
                    1 if bool(choice.get("selected", False)) else 0,
                    int(choice.get("source_message_id", 0) or 0),
                ),
            )
        if body_dialog_id != 0 and body_text_decoded:
            key_by_text = self._body_text_key(body_text_decoded)
            if key_by_text:
                self._body_text_to_dialog_id[key_by_text] = body_dialog_id
            self._dialog_id_to_body_text[body_dialog_id] = (body_text_raw, body_text_decoded)
        return True

    def _repair_persisted_step_rows(self, conn: sqlite3.Connection) -> None:
        # 1) Backfill missing body dialog ids from exact body text matches for same NPC instance.
        conn.execute(
            """
            UPDATE dialog_steps
            SET body_dialog_id = (
                SELECT t2.body_dialog_id
                FROM dialog_steps t2
                WHERE t2.npc_uid_instance = dialog_steps.npc_uid_instance
                  AND t2.body_dialog_id <> 0
                  AND t2.body_text_decoded = dialog_steps.body_text_decoded
                ORDER BY t2.id DESC
                LIMIT 1
            )
            WHERE body_dialog_id = 0
              AND IFNULL(body_text_decoded, '') <> ''
              AND EXISTS (
                SELECT 1
                FROM dialog_steps t2
                WHERE t2.npc_uid_instance = dialog_steps.npc_uid_instance
                  AND t2.body_dialog_id <> 0
                  AND t2.body_text_decoded = dialog_steps.body_text_decoded
              )
            """
        )

        # 2) Backfill missing body text from same NPC+body dialog rows.
        conn.execute(
            """
            UPDATE dialog_steps
            SET body_text_raw = CASE
                    WHEN IFNULL(body_text_raw, '') <> '' THEN body_text_raw
                    ELSE COALESCE((
                        SELECT t2.body_text_raw
                        FROM dialog_steps t2
                        WHERE t2.npc_uid_instance = dialog_steps.npc_uid_instance
                          AND t2.body_dialog_id = dialog_steps.body_dialog_id
                          AND IFNULL(t2.body_text_raw, '') <> ''
                        ORDER BY t2.id DESC
                        LIMIT 1
                    ), '')
                END,
                body_text_decoded = CASE
                    WHEN IFNULL(body_text_decoded, '') <> '' THEN body_text_decoded
                    ELSE COALESCE((
                        SELECT t2.body_text_decoded
                        FROM dialog_steps t2
                        WHERE t2.npc_uid_instance = dialog_steps.npc_uid_instance
                          AND t2.body_dialog_id = dialog_steps.body_dialog_id
                          AND IFNULL(t2.body_text_decoded, '') <> ''
                        ORDER BY t2.id DESC
                        LIMIT 1
                    ), '')
                END
            WHERE body_dialog_id <> 0
              AND (IFNULL(body_text_raw, '') = '' OR IFNULL(body_text_decoded, '') = '')
            """
        )

    def _get_choices_by_step_ids(self, conn: sqlite3.Connection, step_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not step_ids:
            return {}
        placeholders = ",".join("?" for _ in step_ids)
        rows = conn.execute(
            f"""
            SELECT id, step_id, choice_index, choice_dialog_id, choice_text_raw, choice_text_decoded,
                   skill_id, button_icon, decode_pending, selected, source_message_id
            FROM dialog_choices
            WHERE step_id IN ({placeholders})
            ORDER BY step_id ASC, choice_index ASC, id ASC
            """,
            list(step_ids),
        ).fetchall()
        out: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            choice = self._choice_row_to_dict(row)
            out.setdefault(int(choice["step_id"]), []).append(choice)
        return out

    def _overflow_ids(self, conn: sqlite3.Connection, table_name: str, max_rows: int) -> List[int]:
        row = conn.execute(f"SELECT COUNT(*) AS total FROM {table_name}").fetchone()
        total = int(row[0]) if row else 0
        overflow = max(0, total - int(max_rows))
        if overflow <= 0:
            return []
        rows = conn.execute(
            f"SELECT id FROM {table_name} ORDER BY id ASC LIMIT ?",
            (overflow,),
        ).fetchall()
        return [int(item[0]) for item in rows]

    def _trim_table(self, conn: sqlite3.Connection, table_name: str, max_rows: int) -> int:
        overflow_ids = self._overflow_ids(conn, table_name, max_rows)
        if not overflow_ids:
            return 0
        cursor = conn.execute(
            f"DELETE FROM {table_name} WHERE id IN ({','.join('?' for _ in overflow_ids)})",
            overflow_ids,
        )
        return int(cursor.rowcount or 0)

    def _delete_choices_for_step_ids(self, conn: sqlite3.Connection, step_ids: Sequence[int]) -> int:
        if not step_ids:
            return 0
        cursor = conn.execute(
            f"DELETE FROM dialog_choices WHERE step_id IN ({','.join('?' for _ in step_ids)})",
            list(step_ids),
        )
        return int(cursor.rowcount or 0)

    def _callback_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "tick": int(row["tick"]),
            "ts": float(row["ts"]),
            "message_id": int(row["message_id"]),
            "incoming": bool(row["incoming"]),
            "dialog_id": int(row["dialog_id"]),
            "context_dialog_id": int(row["context_dialog_id"]),
            "agent_id": int(row["agent_id"]),
            "map_id": int(row["map_id"]),
            "map_name": _safe_text(row["map_name"]),
            "model_id": int(row["model_id"]),
            "npc_uid": _safe_text(row["npc_uid"]),
            "npc_name": _safe_text(row["npc_name"]),
            "event_type": _safe_text(row["event_type"]),
            "text_raw": _safe_text(row["text_raw"]),
            "text_decoded": _safe_text(row["text_decoded"]),
        }

    def _raw_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "tick": int(row["tick"]),
            "ts": float(row["ts"]),
            "message_id": int(row["message_id"]),
            "incoming": bool(row["incoming"]),
            "map_id": int(row["map_id"]),
            "map_name": _safe_text(row["map_name"]),
            "agent_id": int(row["agent_id"]),
            "npc_name": _safe_text(row["npc_name"]),
            "model_id": int(row["model_id"]),
            "npc_uid": _safe_text(row["npc_uid"]),
            "dialog_id": int(row["dialog_id"]),
            "context_dialog_id": int(row["context_dialog_id"]),
            "event_type": _safe_text(row["event_type"]),
            "text_raw": _safe_text(row["text_raw"]),
        }

    def _step_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "start_tick": int(row["start_tick"]),
            "end_tick": int(row["end_tick"]),
            "map_id": int(row["map_id"]),
            "map_name": _safe_text(row["map_name"]),
            "agent_id": int(row["agent_id"]),
            "npc_name": _safe_text(row["npc_name"]),
            "model_id": int(row["model_id"]),
            "npc_uid_instance": _safe_text(row["npc_uid_instance"]),
            "npc_uid_archetype": _safe_text(row["npc_uid_archetype"]),
            "body_dialog_id": int(row["body_dialog_id"]),
            "body_text_raw": _safe_text(row["body_text_raw"]),
            "body_text_decoded": _safe_text(row["body_text_decoded"]),
            "selected_dialog_id": int(row["selected_dialog_id"]),
            "selected_source_message_id": int(row["selected_source_message_id"]),
            "finalized_reason": _safe_text(row["finalized_reason"]),
            "created_at": float(row["created_at"]),
        }

    def _choice_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "step_id": int(row["step_id"]),
            "choice_index": int(row["choice_index"]),
            "choice_dialog_id": int(row["choice_dialog_id"]),
            "choice_text_raw": _safe_text(row["choice_text_raw"]),
            "choice_text_decoded": _safe_text(row["choice_text_decoded"]),
            "skill_id": int(row["skill_id"]),
            "button_icon": int(row["button_icon"]),
            "decode_pending": bool(row["decode_pending"]),
            "selected": bool(row["selected"]),
            "source_message_id": int(row["source_message_id"]),
        }

    def _write_json(self, path: str, payload: Dict[str, Any]) -> None:
        out_path = os.path.abspath(str(path))
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _key_seen(self, event_key: str) -> bool:
        return event_key in self._seen_keys

    def _remember_key(self, event_key: str) -> None:
        self._seen_keys.add(event_key)
        self._seen_order.append(event_key)
        if len(self._seen_order) <= MAX_SEEN_EVENT_KEYS:
            return
        overflow = len(self._seen_order) - MAX_SEEN_EVENT_KEYS
        stale = self._seen_order[:overflow]
        self._seen_order = self._seen_order[overflow:]
        for key in stale:
            self._seen_keys.discard(key)


_PIPELINE_INSTANCE: Optional[DialogStepSQLitePipeline] = None
_PIPELINE_INSTANCE_LOCK = threading.Lock()


def get_dialog_step_pipeline() -> DialogStepSQLitePipeline:
    global _PIPELINE_INSTANCE
    if _PIPELINE_INSTANCE is not None:
        return _PIPELINE_INSTANCE
    with _PIPELINE_INSTANCE_LOCK:
        if _PIPELINE_INSTANCE is None:
            _PIPELINE_INSTANCE = DialogStepSQLitePipeline()
        return _PIPELINE_INSTANCE
