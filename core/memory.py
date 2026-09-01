"""
记忆系统
========
三层记忆，全部是本地文件，不依赖任何模型厂商，换模型/断网都不影响：

1. 画像记忆 (profile)   -> SQLite 表，key-value，存长期稳定的"关于你"的事实
2. 事件记忆 (episodic)  -> SQLite 表，按时间存对话/事件流水
3. 语义记忆 (semantic)  -> 本地向量库（.npy + .jsonl），用于"这件事和之前说的哪件事像"
"""
import sqlite3
import os
import json
import time
import threading
import numpy as np

from .embeddings import EmbeddingProvider


class MemoryStore:
    def __init__(self, config: dict, base_dir: str):
        mem_cfg = config["memory"]
        self.base_dir = base_dir
        self.db_path = os.path.join(base_dir, mem_cfg["db_path"])
        self.vector_dir = os.path.join(base_dir, mem_cfg["vector_db_path"])
        self.top_k = mem_cfg["top_k_recall"]

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.vector_dir, exist_ok=True)

        self.embedder = EmbeddingProvider(mem_cfg["local_embedding_model_path"], base_dir)

        # check_same_thread=False + 显式锁：CLI下单线程用不上，但网页版
        # (Flask开发服务器默认多线程处理请求) 需要这个，否则会报
        # "SQLite objects created in a thread can only be used in that same thread"
        self._lock = threading.Lock()
        self._init_sqlite()
        self._vector_path = os.path.join(self.vector_dir, "vectors.npy")
        self._meta_path = os.path.join(self.vector_dir, "meta.jsonl")

    # ---------------- 初始化 ----------------
    def _init_sqlite(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS profile (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS episodic (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                role TEXT,
                content TEXT,
                tags TEXT
            )
        """)
        # meta：存放不属于"画像key-value"、也不属于"单条事件流水"的持久状态，
        # 比如跨会话滚动累积的长期摘要、最近一次自动摘要处理到了第几条episodic。
        # 这是解决"重启后只剩最近6条原始对话，记忆很稀薄"问题的关键：
        # 长期摘要不依赖语义检索命中与否，每次对话都会被无条件注入system prompt。
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )
        """)
        self.conn.commit()

    # ---------------- meta / 长期摘要 ----------------
    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, time.time()),
            )
            self.conn.commit()

    def long_term_summary(self) -> str:
        return self.get_meta("long_term_summary", "")

    def episodic_count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM episodic").fetchone()
        return row[0] if row else 0

    def episodic_since_id(self, since_id: int) -> list:
        """取 id > since_id 的所有事件，用于增量摘要，避免每次都重新摘要全部历史"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, timestamp, role, content FROM episodic WHERE id > ? ORDER BY id ASC",
                (since_id,),
            ).fetchall()
        return rows

    # ---------------- 画像记忆 ----------------
    def set_profile(self, key: str, value: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO profile (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, time.time()),
            )
            self.conn.commit()

    def get_all_profile(self) -> dict:
        with self._lock:
            rows = self.conn.execute("SELECT key, value FROM profile").fetchall()
        return {k: v for k, v in rows}

    def profile_summary_text(self) -> str:
        profile = self.get_all_profile()
        if not profile:
            return "（暂无画像记忆，还在了解你）"
        return "\n".join(f"- {k}: {v}" for k, v in profile.items())

    # ---------------- 事件记忆 ----------------
    def add_episodic(self, role: str, content: str, tags: str = ""):
        with self._lock:
            self.conn.execute(
                "INSERT INTO episodic (timestamp, role, content, tags) VALUES (?, ?, ?, ?)",
                (time.time(), role, content, tags),
            )
            self.conn.commit()
        # 同步写入语义向量库，供以后检索
        self._add_vector(content, meta={"role": role, "timestamp": time.time(), "tags": tags})

    def recent_episodic(self, n: int = 10) -> list:
        with self._lock:
            rows = self.conn.execute(
                "SELECT timestamp, role, content FROM episodic ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return list(reversed(rows))

    def recent_by_tag(self, tag: str, n: int = 5) -> list:
        """
        按 tags 字段做子串匹配，取最近 n 条——目前主要给硬件观测事件用
        （core/agent.py::_on_hardware_event 写入时 tags="hardware"），
        独立于 recent_episodic() 用的"最近若干轮对话"这条查询路径，
        避免硬件观测被混进对话轮次回放里、被误当成Kai自己说过的话。
        """
        with self._lock:
            rows = self.conn.execute(
                "SELECT timestamp, role, content FROM episodic "
                "WHERE tags LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{tag}%", n),
            ).fetchall()
        return list(reversed(rows))

    # ---------------- 语义记忆（向量检索） ----------------
    def _add_vector(self, text: str, meta: dict):
        vec = self.embedder.embed(text)
        with self._lock:
            if os.path.exists(self._vector_path):
                existing = np.load(self._vector_path)
                vectors = np.vstack([existing, vec[None, :]])
            else:
                vectors = vec[None, :]
            np.save(self._vector_path, vectors)

            meta_with_text = {**meta, "text": text}
            with open(self._meta_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(meta_with_text, ensure_ascii=False) + "\n")

    def search_semantic(self, query: str, top_k: int = None) -> list:
        """返回和 query 语义最相关的历史记忆，用于把"相关记忆"塞进当前对话的上下文"""
        top_k = top_k or self.top_k
        with self._lock:
            if not os.path.exists(self._vector_path):
                return []
            vectors = np.load(self._vector_path)
            metas = []
            with open(self._meta_path, "r", encoding="utf-8") as f:
                for line in f:
                    metas.append(json.loads(line))

        query_vec = self.embedder.embed(query)
        sims = [self.embedder.cosine_sim(query_vec, v) for v in vectors]
        top_idx = np.argsort(sims)[::-1][:top_k]

        results = []
        for i in top_idx:
            if i < len(metas) and sims[i] > 0.15:  # 过滤掉完全不相关的
                results.append({**metas[i], "score": float(sims[i])})
        return results

    def close(self):
        self.conn.close()
