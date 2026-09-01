import os


def run(params, ctx):
    rel_path = params["path"]
    content = params.get("content", "")
    append = bool(params.get("append", False))
    real_path = ctx.resolve_path(rel_path)

    os.makedirs(os.path.dirname(real_path), exist_ok=True)
    mode = "a" if append else "w"
    with open(real_path, mode, encoding="utf-8") as f:
        f.write(content)

    return {"path": rel_path, "bytes_written": len(content.encode("utf-8")), "mode": mode}
