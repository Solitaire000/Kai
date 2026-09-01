import os


def run(params, ctx):
    rel_path = params.get("path") or "."
    real_path = ctx.resolve_path(rel_path)

    if not os.path.isdir(real_path):
        raise FileNotFoundError(f"目录不存在: {rel_path}")

    entries = []
    for name in sorted(os.listdir(real_path)):
        full = os.path.join(real_path, name)
        entries.append({
            "name": name,
            "type": "dir" if os.path.isdir(full) else "file",
            "size_bytes": os.path.getsize(full) if os.path.isfile(full) else None,
        })
    return {"path": rel_path, "entries": entries}
