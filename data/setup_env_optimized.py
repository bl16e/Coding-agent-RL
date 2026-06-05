#!/usr/bin/env python3
"""
优化的 SWE-bench 环境管理：按仓库复用 Docker 镜像
"""
import pandas as pd
import subprocess
import json

def build_base_image(repo):
    """为仓库构建基础镜像（可复用）"""
    image_name = f"swebench-base-{repo.replace('/', '-')}"

    print(f"\n构建基础镜像: {image_name}")
    print(f"  仓库: {repo}")

    cmd = [
        "docker", "build",
        "-t", image_name,
        "-f", "Dockerfile.base",
        "--build-arg", f"REPO_URL={repo}",
        "."
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return image_name if result.returncode == 0 else None

def run_task_in_container(image_name, base_commit, instance_id):
    """在基础镜像中运行特定任务"""
    print(f"\n运行任务: {instance_id}")
    print(f"  切换到 commit: {base_commit[:8]}")

    cmd = [
        "docker", "run", "-it", "--rm",
        image_name,
        "bash", "-c",
        f"git checkout {base_commit} && bash"
    ]

    subprocess.run(cmd)

if __name__ == "__main__":
    df = pd.read_parquet('dev-00000-of-00001.parquet')

    # 获取所有唯一仓库
    repos = df['repo'].unique()

    print(f"发现 {len(repos)} 个不同的仓库")
    print(f"总共 {len(df)} 个任务")
    print(f"\n复用率: 每个镜像平均支持 {len(df)/len(repos):.1f} 个任务")

    # 选择操作
    print("\n选择操作:")
    print("1. 构建所有基础镜像")
    print("2. 构建单个仓库镜像")
    print("3. 运行指定任务")

    choice = input("\n输入选项: ").strip()

    if choice == "1":
        for repo in repos:
            build_base_image(repo)
    elif choice == "2":
        for i, repo in enumerate(repos):
            print(f"{i}. {repo}")
        idx = int(input("选择仓库: "))
        build_base_image(repos[idx])
    elif choice == "3":
        for i, row in df.iterrows():
            print(f"{i}. {row['instance_id']}")
        idx = int(input("选择任务: "))
        task = df.iloc[idx]
        image = f"swebench-base-{task['repo'].replace('/', '-')}"
        run_task_in_container(image, task['base_commit'], task['instance_id'])
