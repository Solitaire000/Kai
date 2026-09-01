import os

MAX_CHARS = 8000  # 避免大文件把整个模型上下文塞爆


def run(params, ctx):
    rel_path = params["path"]
    real_path = ctx.resolve_path(rel_path)

    if not os.path.isfile(real_path):
        raise FileNotFoundError(f"文件不存在: {rel_path}")
    if os.path.getsize(real_path) > 2 * 1024 * 1024:
        raise ValueError("文件超过2MB，为避免占满上下文，暂不支持直接读取这么大的文件")

    with open(real_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    truncated = len(content) > MAX_CHARS
    return {
        "path": rel_path,
        "content": content[:MAX_CHARS],
        "truncated": truncated,
    }
