#!/usr/bin/env python3
"""
Usage:
  python ingest.py <url> [--domain edge-ai] [--title "My Title"]
"""
import argparse
import sys
from pathlib import Path

import httpx

from src.ingest import ingest_source


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch URL, return (title, content). Title guessed from <title> tag or URL."""
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    text = resp.text

    # Try to extract <title> from HTML
    title = url
    if "html" in content_type:
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()

    return title, text


def main():
    parser = argparse.ArgumentParser(description="Ingest a URL into 2brain inbox")
    parser.add_argument("url", help="URL to fetch and ingest")
    parser.add_argument("--domain", default=None, help="Domain hint (e.g. edge-ai)")
    parser.add_argument("--title", default=None, help="Override page title")
    args = parser.parse_args()

    print(f"Fetching {args.url} ...")
    try:
        fetched_title, content = fetch_url(args.url)
    except Exception as e:
        print(f"Error fetching URL: {e}", file=sys.stderr)
        sys.exit(1)

    title = args.title or fetched_title
    print(f"Title: {title}")

    raw_id = ingest_source(
        content=content,
        title=title,
        source_type="url",
        url=args.url,
        domain_hint=args.domain,
        repo_root=Path("."),
    )

    print(f"Ingested: {raw_id}")
    print(f"Location: inbox/raw/{raw_id}/")
    if args.domain:
        print(f"\nTo digest:  python digest.py {raw_id} --domain {args.domain}")
    else:
        print(f"\nTo digest:  python digest.py {raw_id} --domain <domain>")


if __name__ == "__main__":
    main()
