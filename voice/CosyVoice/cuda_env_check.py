import os
import subprocess
import torch


def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as e:
        return f"Execution failed: {e}"


print("\n1. Hardware & NVIDIA Driver Check")
gpu_info = run_cmd("nvidia-smi -L")
print(f"GPU Status: {gpu_info if 'GPU 0' in gpu_info else '❌ NVIDIA GPU not detected'}")
print(f"Driver Version: {run_cmd('nvidia-smi --query-gpu=driver_version --format=csv,noheader')}")
print(f"Max Supported CUDA: {run_cmd('nvidia-smi --query-cuda-version --format=csv,noheader')}")

print("\n2. CUDA Toolkit Check")
nvcc_ver = run_cmd("nvcc --version")
if "release" in nvcc_ver:
    print(f"NVCC Version: {[l for l in nvcc_ver.splitlines() if 'release' in l][-1]}")
else:
    print("NVCC Status: ❌ nvcc command not found, check PATH configuration")

print("\n3. PyTorch CUDA Compatibility Check")
print(f"PyTorch Version: {torch.__version__} (CUDA {torch.version.cuda})")
cuda_available = torch.cuda.is_available()
print(f"CUDA Available: {'✅ Normal' if cuda_available else '❌ Unavailable'}")
if cuda_available:
    cap = torch.cuda.get_device_capability(0)
    print(f"Current GPU: {torch.cuda.get_device_name(0)}")
    print(f"GPU Compute Capability: sm_{cap[0]}{cap[1]}")
    if cap == (12, 0):
        print("✅ RTX 50 series sm_120 architecture detected, PyTorch Nightly CUDA12.8 is required")
    torch.ones(3, 3).cuda()
    print("GPU Tensor Test: ✅ Executed successfully")

print("\n4. cuDNN Dependency Check")
cudnn_found = any(
    "CUDA" in path and "bin" in path and os.path.isdir(path)
    and any(f.startswith("cudnn64_") and f.endswith(".dll") for f in os.listdir(path))
    for path in os.environ.get("PATH", "").split(";")
)
print(f"cuDNN Status: {'✅ cuDNN library deployed' if cudnn_found else '❌ cuDNN not found'}")

print("\n✅ All validation steps completed")
