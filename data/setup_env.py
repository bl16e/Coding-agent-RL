#!/usr/bin/env python3
"""
自动为 SWE-bench 任务构建 Docker 环境
"""
import pandas as pd
import subprocess
import json

def build_environment(instance_id, repo, base_commit):
    """为指定任务构建 Docker 镜像"""

    image_name = f"swebench-{instance_id.replace('/', '-').replace('__', '-')}"

    print(f"Building Docker image for {instance_id}...")
    print(f"  Repo: {repo}")
    print(f"  Commit: {base_commit}")

    # 构建 Docker 镜像
    cmd = [
        "docker", "build",
        "-t", image_name,
        "-f", "Dockerfile.template",
        "--build-arg", f"REPO_URL={repo}",
        "--build-arg", f"BASE_COMMIT={base_commit}",
        "."
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✓ Image built: {image_name}")
        return image_name
    else:
        print(f"✗ Build failed: {result.stderr}")
        return None

def run_container(image_name):
    """运行容器"""
    cmd = ["docker", "run", "-it", "--rm", image_name]
    subprocess.run(cmd)

if __name__ == "__main__":
    # 加载数据
    df = pd.read_parquet('dev-00000-of-00001.parquet')

    # 显示所有任务
    print(f"\n总共 {len(df)} 个任务:\n")
    for idx, row in df.iterrows():
        print(f"{idx}. {row['instance_id']} - {row['repo']}")

    # 选择任务
    choice = input("\n输入任务编号构建环境 (或按 Enter 构建第一个): ").strip()
    idx = int(choice) if choice else 0

    task = df.iloc[idx]
    image_name = build_environment(
        task['instance_id'],
        task['repo'],
        task['base_commit']
    )

    if image_name:
        print(f"\n运行容器: docker run -it --rm {image_name}")
