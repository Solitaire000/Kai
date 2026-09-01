import re
import subprocess


def run(params, ctx):
    command = params["command"]
    sub_cfg = ctx.cfg.get("run_command", {}) or {}

    pattern = sub_cfg.get("allowlist_pattern")
    if pattern and not re.match(pattern, command.strip()):
        raise PermissionError(
            f"命令未通过白名单校验 (allowlist_pattern={pattern!r})。"
            f"去 config.yaml 的 skills.run_command.allowlist_pattern 调整白名单规则。"
        )

    timeout = sub_cfg.get("timeout_seconds", 15)
    proc = subprocess.run(
        command, shell=True, cwd=ctx.workspace_root,
        capture_output=True, text=True, timeout=timeout,
    )
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[:4000],
        "stderr": proc.stderr[:2000],
    }
