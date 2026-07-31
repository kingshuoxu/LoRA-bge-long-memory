"""Smoke test:确认 torch-directml 能调用 AMD GPU 做前向+反向计算。"""
import importlib.metadata
import time

import torch
import torch_directml


def main():
    dml_ver = importlib.metadata.version("torch-directml")
    print(f"torch: {torch.__version__}, torch_directml: {dml_ver}")

    device = torch_directml.device()
    try:
        print(f"GPU 名称: {torch_directml.device_name(device.index)}")
    except Exception:
        print("GPU 名称: (device_name 不可用,继续)")

    # 1) 矩阵乘:GPU vs CPU 粗测
    n = 4096
    a_cpu = torch.randn(n, n)
    b_cpu = torch.randn(n, n)
    t0 = time.perf_counter()
    (a_cpu @ b_cpu).sum().item()
    cpu_t = time.perf_counter() - t0
    print(f"CPU matmul {n}x{n}: {cpu_t:.3f}s")

    a = a_cpu.to(device)
    b = b_cpu.to(device)
    (a @ b).sum().item()  # warmup
    t0 = time.perf_counter()
    (a @ b).sum().item()
    gpu_t = time.perf_counter() - t0
    print(f"GPU matmul {n}x{n}: {gpu_t:.3f}s (加速 {cpu_t / gpu_t:.1f}x)")

    # 2) 前向 + 反向:验证 autograd 在 GPU 上工作
    model = torch.nn.Sequential(
        torch.nn.Linear(512, 1024), torch.nn.ReLU(), torch.nn.Linear(1024, 512)
    ).to(device)
    x = torch.randn(64, 512, device=device)
    loss = model(x).square().mean()
    loss.backward()
    grad_norm = model[0].weight.grad.norm().item()
    print(f"前向+反向 OK, loss={loss.item():.4f}, 首层梯度范数={grad_norm:.4f}")
    assert grad_norm > 0, "梯度为 0,反向传播异常"

    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
