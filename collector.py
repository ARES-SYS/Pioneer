#!/usr/bin/env python3
"""
collector.py — The Silent Collector
=======================================
Browses the web anonymously via Tor + SOCKS5.
Converts pages to Markdown. Organizes into folders.
Lock flag -1 for version control.

Usage:
  python collector.py https://target.com
  python collector.py --input urls.txt

Privacy:
  - All traffic routed through Tor SOCKS5 (127.0.0.1:9050)
  - Rotating common browser User-Agent
  - No JavaScript (HTML → MD only)
  - Respectful: random delay between requests
  - No persistent cookies
"""

import os
import sys
import time
import random
import hashlib
import argparse
import urllib.parse
import urllib.request
import urllib.error
import ssl
import socket
import html.parser
import re
from pathlib import Path

# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════

TOR_PROXY = os.environ.get("TOR_PROXY", "socks5://127.0.0.1:9050")
OUTPUT_DIR = os.environ.get("COOKIE_OUTPUT", os.path.expanduser("~/collector"))
DELAY_MIN = float(os.environ.get("COOKIE_DELAY_MIN", "2"))
DELAY_MAX = float(os.environ.get("COOKIE_DELAY_MAX", "6"))
TIMEOUT = int(os.environ.get("COOKIE_TIMEOUT", "30"))
LOCK_FLAG = "-1"
LOCK_SUFFIXES = [".lock", f"_{LOCK_FLAG}", ".no-touch"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════
# HTML → MARKDOWN (zero dependencies)
# ═══════════════════════════════════════════════════════

class HTMLToMarkdown(html.parser.HTMLParser):
    """Converts HTML to basic Markdown. No JS, no CSS."""

    def __init__(self):
        super().__init__()
        self.output = []
        self.skip_stack = 0
        self.list_depth = 0
        self.in_code = False
        self.in_pre = False
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Elements to completely ignore
        if tag in ("script", "style", "nav", "footer", "header", "noscript",
                    "iframe", "form", "button", "input", "select", "textarea",
                    "svg", "canvas", "video", "audio", "img"):
            self.skip_stack += 1
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.output.append(f"\n{'#' * level} ")
        elif tag == "p":
            self.output.append("\n\n")
        elif tag == "br":
            self.output.append("\n")
        elif tag == "li":
            self.output.append("\n" + "  " * self.list_depth + "- ")
        elif tag == "ul":
            self.list_depth += 1
        elif tag == "ol":
            self.list_depth += 1
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href and not href.startswith("#") and not href.startswith("javascript:"):
                self.output.append("[")
                self._link_url = href
            else:
                self._link_url = None
        elif tag == "strong" or tag == "b":
            self.output.append("**")
        elif tag == "em" or tag == "i":
            self.output.append("*")
        elif tag == "code":
            if not self.in_pre:
                self.output.append("`")
        elif tag == "pre":
            self.in_pre = True
            self.output.append("\n```\n")
        elif tag == "blockquote":
            self.output.append("\n> ")
        elif tag == "hr":
            self.output.append("\n\n---\n\n")
        elif tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "noscript",
                    "iframe", "form", "button", "input", "select", "textarea",
                    "svg", "canvas", "video", "audio", "img"):
            if self.skip_stack > 0:
                self.skip_stack -= 1
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.output.append("\n")
        elif tag == "ul":
            self.list_depth = max(0, self.list_depth - 1)
        elif tag == "ol":
            self.list_depth = max(0, self.list_depth - 1)
        elif tag == "a" and hasattr(self, '_link_url') and self._link_url:
            self.output.append(f"]({self._link_url})")
            self._link_url = None
        elif tag in ("strong", "b"):
            self.output.append("**")
        elif tag in ("em", "i"):
            self.output.append("*")
        elif tag == "code" and not self.in_pre:
            self.output.append("`")
        elif tag == "pre":
            self.in_pre = False
            self.output.append("\n```\n")
        elif tag == "title":
            self.in_title = False
        elif tag == "p":
            self.output.append("\n")

    def handle_data(self, data):
        if self.skip_stack > 0:
            return
        if self.in_title:
            self.title += data
        if data.strip() or (data == " " and self.output and self.output[-1] != " "):
            self.output.append(data)

    def get_markdown(self):
        text = "".join(self.output)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' +\n', '\n', text)
        return text.strip()


def html_to_markdown(html_content, url=""):
    parser = HTMLToMarkdown()
    parser.feed(html_content)
    md = parser.get_markdown()

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    header = f"---\nsource: {url}\ncollected: {timestamp}\nconverter: collector.py\n---\n\n"
    if parser.title:
        header = f"# {parser.title}\n\n" + header

    return header + md

# ═══════════════════════════════════════════════════════
# TOR PROXY HANDLER
# ═══════════════════════════════════════════════════════

def build_opener():
    """Create a urllib opener that uses Tor SOCKS5."""
    try:
        import socks
        import sockshandler
        handler = sockshandler.SocksiPyHandler(socks.SOCKS5, "127.0.0.1", 9050)
        return urllib.request.build_opener(handler)
    except ImportError:
        pass

    try:
        import socks as socks_module
        socks_module.set_default_proxy(socks_module.SOCKS5, "127.0.0.1", 9050)
        socket.socket = socks_module.socksocket
        return urllib.request.build_opener()
    except ImportError:
        pass

    print("[WARN] PySocks not found. Requests will NOT go through Tor.")
    print("[WARN] Install: pip install pysocks")
    return urllib.request.build_opener()

# ═══════════════════════════════════════════════════════
# COLLECTION
# ═══════════════════════════════════════════════════════

def domain_to_folder(url: str) -> str:
    """Convert a URL to a safe folder inside OUTPUT_DIR."""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace(":", "_")
    domain = re.sub(r'[^a-zA-Z0-9_.-]', '_', domain)
    path = parsed.path.strip("/").replace("/", "_")
    if not path:
        path = "index"
    folder = os.path.join(OUTPUT_DIR, domain, path)
    os.makedirs(folder, exist_ok=True)
    return folder


def url_to_filename(url: str) -> str:
    """Generate a unique filename based on URL hash."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    parsed = urllib.parse.urlparse(url)
    basename = parsed.path.split("/")[-1] if parsed.path.split("/")[-1] else "index"
    basename = re.sub(r'\.(html|htm|php|asp|aspx|jsp)$', '', basename)
    if not basename:
        basename = "index"
    return f"{basename}_{url_hash}.md"


def has_lock(folder: str) -> bool:
    """Check if folder has the -1 lock."""
    for suffix in LOCK_SUFFIXES:
        if os.path.exists(os.path.join(folder, suffix)):
            return True
    return False


def set_lock(folder: str) -> None:
    """Place the -1 lock on a folder."""
    lock_path = os.path.join(folder, f"_{LOCK_FLAG}")
    Path(lock_path).touch()


def fetch_url(url: str, opener) -> tuple:
    """Fetch a URL via Tor. Returns (content, content_type, error)."""
    user_agent = random.choice(USER_AGENTS)
    req = urllib.request.Request(url, headers={
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "")
            return content, content_type, None
    except urllib.error.HTTPError as e:
        return None, "", f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, "", f"URL Error: {e.reason}"
    except socket.timeout:
        return None, "", "Timeout"
    except Exception as e:
        return None, "", str(e)


def collect_url(url: str, opener, force: bool = False) -> str:
    """Collect a URL and save as Markdown. Returns the file path."""
    folder = domain_to_folder(url)

    if has_lock(folder) and not force:
        print(f"  [LOCK] {folder} has -1 lock. Skipping: {url}")
        return ""

    filename = url_to_filename(url)
    filepath = os.path.join(folder, filename)

    if os.path.exists(filepath) and not force:
        print(f"  [EXISTS] {filepath}")
        return filepath

    print(f"  [FETCH] {url}")
    content, content_type, error = fetch_url(url, opener)

    if error:
        print(f"  [ERROR] {error}")
        return ""

    if not content:
        return ""

    if b"<html" not in content[:1000].lower() and b"<!doctype" not in content[:1000].lower():
        print(f"  [SKIP] Not HTML ({len(content)} bytes)")
        return ""

    html = content.decode("utf-8", errors="replace")
    md = html_to_markdown(html, url)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md)

    set_lock(folder)

    print(f"  [OK] {filepath} ({len(md)} chars)")
    return filepath


def collect_from_file(filepath: str, opener) -> list:
    """Collect URLs from a text file (one URL per line)."""
    results = []
    with open(filepath, "r") as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    print(f"[INFO] {len(urls)} URLs in {filepath}")
    for url in urls:
        result = collect_url(url, opener)
        if result:
            results.append(result)
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        time.sleep(delay)
    return results

# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="collector.py — Silent collector via Tor",
        epilog="Example: python collector.py https://target.com"
    )
    parser.add_argument("target", nargs="+", help="URL(s) to collect or .txt file with URLs")
    parser.add_argument("--input", help="File with URL list (one per line)")
    parser.add_argument("--force", action="store_true", help="Ignore -1 lock")
    parser.add_argument("--no-tor", action="store_true", help="Skip Tor (local testing only)")
    args = parser.parse_args()

    if args.no_tor:
        opener = urllib.request.build_opener()
        print("[WARN] Tor disabled.")
    else:
        opener = build_opener()
        print(f"[INFO] Tor proxy: {TOR_PROXY}")

    print(f"[INFO] Output: {OUTPUT_DIR}")

    if args.input:
        collect_from_file(args.input, opener)
        return

    for target in args.target:
        if os.path.isfile(target):
            collect_from_file(target, opener)
        else:
            collect_url(target, opener, force=args.force)


if __name__ == "__main__":
    main()
