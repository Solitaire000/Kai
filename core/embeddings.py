"""
嵌入层：把文本变成向量，用于语义记忆检索。
和 model_router 一样坚持"离线也能用"原则：
  1. 优先尝试加载本地 sentence-transformers 模型（如 bge-small-zh-v1.5）
  2. 模型不存在/加载失败 -> 退化为哈希向量（质量较低但零依赖、绝不崩溃）
"""
import hashlib
import os
import numpy as np


class EmbeddingProvider:
    def __init__(self, model_path: str, base_dir: str, dim: int = 256):
        self.dim = dim
        self._st_model = None
        full_path = os.path.join(base_dir, model_path)
        self._model_available = os.path.exists(full_path)
        self._model_path = full_path

    def _load_st_model(self):
        if self._st_model is not None:
            return self._st_model
        try:
            from sentence_transformers import SentenceTransformer
            self._st_model = SentenceTransformer(self._model_path)
        except Exception:
            self._st_model = False  # 标记加载失败，别再重复尝试
        return self._st_model

    def embed(self, text: str) -> np.ndarray:
        if self._model_available:
            model = self._load_st_model()
            if model:
                vec = model.encode(text, normalize_embeddings=True)
                return np.array(vec, dtype=np.float32)
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> np.ndarray:
        """
        零依赖降级方案：用多个不同的哈希种子把文本词袋映射到固定维度向量。
        效果远不如真实embedding模型，但保证语义记忆功能"能用"而不是"崩溃"。
        建议：只要条件允许，尽快把 bge-small-zh-v1.5 放到 data/models 下启用真实embedding。
        """
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = list(text) if len(text) < 50 else text.split()
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    @staticmethod
    def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)
