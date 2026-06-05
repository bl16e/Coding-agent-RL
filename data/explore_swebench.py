import pandas as pd

# Load the datasets
dev_df = pd.read_parquet('dev-00000-of-00001.parquet')
test_df = pd.read_parquet('test-00000-of-00001.parquet')

print("=" * 60)
print("DEV SET")
print("=" * 60)
print(f"Number of examples: {len(dev_df)}")
print(f"\nColumns: {list(dev_df.columns)}")
print(f"\nFirst example:")
print("-" * 60)

# Display first example's key fields
first = dev_df.iloc[0]
for col in dev_df.columns:
    value = first[col]
    if isinstance(value, str) and len(value) > 200:
        print(f"\n{col}: {value[:200]}...")
    else:
        print(f"\n{col}: {value}")

print("\n" + "=" * 60)
print("TEST SET")
print("=" * 60)
print(f"Number of examples: {len(test_df)}")
