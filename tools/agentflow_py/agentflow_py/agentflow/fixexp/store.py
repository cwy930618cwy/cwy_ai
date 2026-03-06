import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from agentflow.common import generate_fix_session_id, generate_id
from agentflow.storage import RedisClient, SQLiteStore
from .model import FixSession, FixAttempt, FixStatus


class FixExpStore:
    def __init__(self, redis: RedisClient, sqlite: Optional[SQLiteStore],
                 logger: logging.Logger):
        self._redis = redis
        self._sqlite = sqlite
        self._logger = logger

    async def create_session(self, task_id: str, agent_id: str, problem: str,
                              error_msg: str = "", error_type: str = "",
                              tags: Optional[List[str]] = None) -> FixSession:
        now = datetime.now(timezone.utc).isoformat()
        session = FixSession(
            id=generate_fix_session_id(),
            task_id=task_id,
            agent_id=agent_id,
            problem=problem,
            error_msg=error_msg,
            error_type=error_type,
            status=FixStatus.ACTIVE,
            tags=tags or [],
            created_at=now,
        )
        key = self._redis.key("fixexp", "session", session.id)
        await self._redis.hset(key, {
            "id": session.id,
            "task_id": task_id,
            "agent_id": agent_id,
            "problem": problem,
            "error_msg": error_msg,
            "error_type": error_type,
            "status": FixStatus.ACTIVE,
            "resolution": "",
            "attempt_count": "0",
            "final_experience": "",
            "tags": json.dumps(tags or []),
            "created_at": now,
            "resolved_at": "",
        })
        # Index by agent+task
        await self._redis.sadd(self._redis.key("fixexp", "agent", agent_id, "sessions"), session.id)
        self._logger.info(f"FixSession已创建 id={session.id} agent={agent_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[FixSession]:
        key = self._redis.key("fixexp", "session", session_id)
        data = await self._redis.hgetall(key)
        if not data:
            return None
        return self._map_session(data)

    async def add_attempt(self, session_id: str, approach: str, reasoning: str,
                           result: str, result_detail: str = "",
                           modified_files: Optional[List[str]] = None,
                           code_changes: str = "",
                           confidence: float = 0.5) -> FixAttempt:
        now = datetime.now(timezone.utc).isoformat()
        attempt = FixAttempt(
            id=generate_id("attempt"),
            session_id=session_id,
            approach=approach,
            reasoning=reasoning,
            result=result,
            result_detail=result_detail,
            modified_files=modified_files or [],
            code_changes=code_changes,
            confidence=confidence,
            created_at=now,
        )
        attempt_key = self._redis.key("fixexp", "session", session_id, "attempts")
        await self._redis.rpush(attempt_key, json.dumps(attempt.to_dict()))

        # Update attempt count
        sess_key = self._redis.key("fixexp", "session", session_id)
        session = await self.get_session(session_id)
        if session:
            await self._redis.hset(sess_key, {"attempt_count": str(session.attempt_count + 1)})

        return attempt

    async def get_attempts(self, session_id: str) -> List[FixAttempt]:
        attempt_key = self._redis.key("fixexp", "session", session_id, "attempts")
        items = await self._redis.lrange(attempt_key, 0, -1)
        result = []
        for item in items:
            try:
                d = json.loads(item)
                result.append(FixAttempt(**d))
            except Exception:
                pass
        return result

    async def close_session(self, session_id: str, resolution: str,
                             final_experience: str = "") -> Optional[FixSession]:
        sess_key = self._redis.key("fixexp", "session", session_id)
        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(sess_key, {
            "status": FixStatus.RESOLVED,
            "resolution": resolution,
            "final_experience": final_experience,
            "resolved_at": now,
        })
        return await self.get_session(session_id)

    async def update_attempt_label(self, session_id: str, attempt_id: str, label: str) -> bool:
        attempt_key = self._redis.key("fixexp", "session", session_id, "attempts")
        items = await self._redis.lrange(attempt_key, 0, -1)
        updated = []
        found = False
        for item in items:
            try:
                d = json.loads(item)
                if d.get("id") == attempt_id:
                    d["label"] = label
                    found = True
                updated.append(json.dumps(d))
            except Exception:
                updated.append(item)

        if found:
            await self._redis.delete(attempt_key)
            for item in updated:
                await self._redis.rpush(attempt_key, item)
        return found

    async def query_experiences(self, error_type: str = "", keyword: str = "",
                                 limit: int = 10) -> List[Tuple[float, FixSession, List[FixAttempt]]]:
        """Query resolved fix sessions with TF-IDF scoring."""
        # Find all session IDs by scanning
        pattern = self._redis.key("fixexp", "session", "*")
        all_keys = await self._redis.scan_iter(pattern, count=100)
        results = []
        import time as _time
        now_ts = _time.time()

        for key in all_keys:
            if "attempts" in key:
                continue
            data = await self._redis.hgetall(key)
            if not data:
                continue
            if data.get("status") != FixStatus.RESOLVED:
                continue
            session = self._map_session(data)
            if error_type and session.error_type != error_type:
                continue

            # Score: TF-IDF approximation with time decay
            score = self._compute_score(session, keyword, now_ts)
            if score > 0:
                attempts = await self.get_attempts(session.id)
                results.append((score, session, attempts))

        results.sort(key=lambda x: -x[0])
        return results[:limit]

    def _compute_score(self, session: FixSession, keyword: str, now_ts: float) -> float:
        if not keyword:
            base_score = 1.0
        else:
            # TF-IDF approximation: count keyword occurrences
            text = f"{session.problem} {session.error_msg} {session.resolution}"
            words = text.lower().split()
            kw_lower = keyword.lower()
            tf = words.count(kw_lower) / max(1, len(words))
            base_score = tf * 10 + (0.5 if kw_lower in text.lower() else 0)
            if base_score == 0:
                return 0.0

        # Time decay
        try:
            from datetime import datetime as _dt, timezone as _tz
            created_ts = _dt.fromisoformat(session.created_at.replace("Z", "+00:00")).timestamp()
            days_old = (now_ts - created_ts) / 86400
            decay = 0.95 ** days_old
        except Exception:
            decay = 1.0

        return base_score * decay

    def _map_session(self, data: Dict) -> FixSession:
        tags = []
        if t := data.get("tags"):
            try:
                tags = json.loads(t)
            except Exception:
                pass
        return FixSession(
            id=data.get("id", ""),
            task_id=data.get("task_id", ""),
            agent_id=data.get("agent_id", ""),
            problem=data.get("problem", ""),
            error_msg=data.get("error_msg", ""),
            error_type=data.get("error_type", ""),
            status=data.get("status", FixStatus.ACTIVE),
            resolution=data.get("resolution", ""),
            attempt_count=int(data.get("attempt_count", 0)),
            final_experience=data.get("final_experience", ""),
            tags=tags,
            created_at=data.get("created_at", ""),
            resolved_at=data.get("resolved_at", ""),
        )
