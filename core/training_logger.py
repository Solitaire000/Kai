"""
训练数据采集器 (Training Logger)
================================
这是"日常使用 -> 本地模型持续变强"这条闭环的第一块地基。

设计原则：
1. 只蒸馏"老师"（外部在线大模型）的输出，不收 local_gguf 自己生成的回答——
   自己学自己的输出没有信息增量，反而会放大自己的错误/口癖。
2. degraded（离线降级）状态下产生的回答不收——那本身就是本地模型自己的输出。
3. 记录 rating 字段，给用户反馈（👍/👎、"重新生成"）留位置，为后续做 DPO
   偏好对齐做数据准备；本版先只用于"筛掉明确被点踩的样本"。
4. used_in_version 字段：一条样本被某次训练用过之后打上版本号，避免重复训练、
   也方便追溯"某个版本是用哪批数据训出来的"。
5. 和 memory.py 一样：纯本地 SQLite，不依赖任何模型厂商，换供应商/断网都不影响
   数据积累。
"""
import sqlite3
import os
import threading
import time


class TrainingLogger:
    def __init__(self, config: dict, base_dir: str):
        train_cfg = (config.get("training") or {})
        db_path = train_cfg.get("db_path", "memory/training_samples.db")
        self.db_path = os.path.join(base_dir, db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_sqlite()

    def _init_sqlite(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS training_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                agent TEXT,
                source TEXT,
                system_prompt TEXT,
                user_input TEXT,
                assistant_output TEXT,
                rating INTEGER DEFAULT 0,
                used_in_version TEXT DEFAULT NULL
            )
        """)
        self.conn.commit()

    # ---------------- 写入 ----------------
    def log_sample(self, agent: str, source: str, system_prompt: str,
                    user_input: str, assistant_output: str) -> int:
        """
        只应该在满足以下条件时被调用（由 agent.py 负责判断）：
        - source 是一个在线"教师"provider（不是 local_gguf / none）
        - 这轮回答不是离线降级产生的
        - 没有触发\"需要用户确认\"（那种半截对话不适合当训练样本）
        """
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO training_samples (ts, agent, source, system_prompt, "
                "user_input, assistant_output, rating) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (time.time(), agent, source, system_prompt, user_input, assistant_output),
            )
            self.conn.commit()
            return cur.lastrowid

    def set_rating(self, sample_id: int, rating: int):
        """rating: 1=用户点赞, -1=用户点踩/要求重新生成, 0=未评价（默认）"""
        with self._lock:
            self.conn.execute(
                "UPDATE training_samples SET rating = ? WHERE id = ?", (rating, sample_id)
            )
            self.conn.commit()

    # ---------------- 导出给训练脚本用 ----------------
    def export_unused(self, exclude_disliked: bool = True, limit: int = None):
        """
        导出还没被任何版本训练用过的样本。train/train_lora.py 会调这个方法
        （或者直接用 export_to_jsonl 落盘成文件，训练时不依赖 core/ 里的其它模块）。
        """
        sql = "SELECT id, agent, source, system_prompt, user_input, assistant_output " \
              "FROM training_samples WHERE used_in_version IS NULL"
        if exclude_disliked:
            sql += " AND rating >= 0"
        sql += " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql).fetchall()
        return [
            {"id": r[0], "agent": r[1], "source": r[2], "system_prompt": r[3],
             "user_input": r[4], "assistant_output": r[5]}
            for r in rows
        ]

    def export_all(self, exclude_disliked: bool = True, limit: int = None):
        """
        导出全部样本，不管有没有被用过——换 base model 重新训练时用这个，
        因为旧 adapter 换不了模型，但积累的文本数据跟模型架构无关，
        全量拿来重训一遍完全没问题（也不需要再 mark_used，version 记录里
        本来就分了 base_model 字段，能追溯是哪个模型训的）。
        """
        sql = "SELECT id, agent, source, system_prompt, user_input, assistant_output " \
              "FROM training_samples WHERE 1=1"
        if exclude_disliked:
            sql += " AND rating >= 0"
        sql += " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql).fetchall()
        return [
            {"id": r[0], "agent": r[1], "source": r[2], "system_prompt": r[3],
             "user_input": r[4], "assistant_output": r[5]}
            for r in rows
        ]

    def mark_used(self, sample_ids: list, version_tag: str):
        with self._lock:
            self.conn.executemany(
                "UPDATE training_samples SET used_in_version = ? WHERE id = ?",
                [(version_tag, sid) for sid in sample_ids],
            )
            self.conn.commit()

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM training_samples").fetchone()[0]
        unused = self.conn.execute(
            "SELECT COUNT(*) FROM training_samples WHERE used_in_version IS NULL AND rating >= 0"
        ).fetchone()[0]
        disliked = self.conn.execute(
            "SELECT COUNT(*) FROM training_samples WHERE rating < 0"
        ).fetchone()[0]
        by_source = self.conn.execute(
            "SELECT source, COUNT(*) FROM training_samples GROUP BY source"
        ).fetchall()
        return {
            "total": total, "unused_for_training": unused, "disliked": disliked,
            "by_source": {s: c for s, c in by_source},
        }

    def close(self):
        self.conn.close()
