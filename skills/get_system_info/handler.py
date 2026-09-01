import os
import platform
import shutil


def _bytes_to_gb(n):
    return round(n / (1024 ** 3), 1)


def run(params, ctx):
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }

    try:
        total, used, free = shutil.disk_usage(ctx.base_dir)
        info["disk_total_gb"] = _bytes_to_gb(total)
        info["disk_free_gb"] = _bytes_to_gb(free)
    except Exception as e:
        info["disk_error"] = str(e)

    # 内存信息优先用 psutil（如果装了），没装就走各平台简单兜底，实在拿不到就跳过
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["memory_total_gb"] = _bytes_to_gb(vm.total)
        info["memory_used_percent"] = vm.percent
    except ImportError:
        try:
            if platform.system() == "Linux":
                with open("/proc/meminfo") as f:
                    lines = {l.split(":")[0]: l.split(":")[1].strip() for l in f}
                total_kb = int(lines["MemTotal"].split()[0])
                avail_kb = int(lines.get("MemAvailable", "0 kB").split()[0])
                info["memory_total_gb"] = _bytes_to_gb(total_kb * 1024)
                if total_kb:
                    info["memory_used_percent"] = round((1 - avail_kb / total_kb) * 100, 1)
        except Exception:
            info["memory_note"] = "未安装psutil，且无法用系统文件兜底获取内存信息（可 pip install psutil 获得更完整信息）"

    return info
