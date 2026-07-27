#!/usr/bin/env python3
"""
Signal task completion. Call this when you have made all necessary changes
and verified they work correctly. Optionally include a summary of changes.

Parameters:
  --result (string, optional): Brief summary of changes made.
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Signal task completion."
    )
    parser.add_argument(
        "--result", default="", help="Optional summary of changes made."
    )
    args = parser.parse_args()

    print("<<<Finished>>>")
    if args.result:
        print(f"Submission: {args.result}")


if __name__ == "__main__":
    main()
