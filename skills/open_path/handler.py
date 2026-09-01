import os
import platform
import subprocess
import webbrowser


def run(params, ctx):
    target = params["target"]

    if target.startswith("http://") or target.startswith("https://"):
        webbrowser.open(target)
        return {"opened": target, "type": "url"}

    real_path = ctx.resolve_path(target)
    if not os.path.exists(real_path):
        raise FileNotFoundError(f"路径不存在: {target}")

    system = platform.system()
    if system == "Windows":
        os.startfile(real_path)  # noqa
    elif system == "Darwin":
        subprocess.run(["open", real_path], check=True)
    else:
        subprocess.run(["xdg-open", real_path], check=True)

    return {"opened": target, "type": "path"}
