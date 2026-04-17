#!/usr/bin/env python3
"""
Usage:
  python digest.py <raw_id> --domain edge-ai
"""
import argparse
import os
import sys
from pathlib import Path

from src.digest import digest_raw


def main():
    parser = argparse.ArgumentParser(description="Digest a raw source into candidate pages")
    parser.add_argument("raw_id", help="Raw source ID (e.g. raw_20260416_153042_...)")
    parser.add_argument("--domain", required=True, help="Target domain (e.g. edge-ai)")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    raw_dir = Path("inbox/raw") / args.raw_id
    if not raw_dir.exists():
        print(f"Error: raw source not found at {raw_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Digesting {args.raw_id} into domain '{args.domain}' ...")
    candidates = digest_raw(args.raw_id, args.domain, repo_root=Path("."))

    if not candidates:
        print("Digest failed — check jobs/failed/ for details.", file=sys.stderr)
        sys.exit(1)

    print(f"Created {len(candidates)} candidate(s):")
    for c in candidates:
        print(f"  candidates/{args.domain}/pending/{c}")
    print("\nOpen http://127.0.0.1:5000 to review.")


if __name__ == "__main__":
    main()
