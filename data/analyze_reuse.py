import pandas as pd
from collections import Counter

# 加载两个数据集
dev_df = pd.read_parquet('dev-00000-of-00001.parquet')
test_df = pd.read_parquet('test-00000-of-00001.parquet')

print("=" * 60)
print("环境复用分析")
print("=" * 60)

# 分析 repo 分布
all_repos = list(dev_df['repo']) + list(test_df['repo'])
repo_counts = Counter(all_repos)

print(f"\n总任务数: {len(dev_df) + len(test_df)}")
print(f"不同仓库数: {len(repo_counts)}")
print(f"\n每个仓库的任务数量:")
print("-" * 60)

for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
    print(f"{repo:40s} {count:3d} 个任务")
