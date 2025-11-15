"""
Input cmd: python linkChecker.py "https:linkname.com/other"
"""
import argparse
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def get_rendered_html(url: str, timeout_ms: int = 30000) -> str:
    """
    Use Playwright (Chromium) to fully render a JS-heavy page and return the HTML.
    Works with React, Next.js, etc.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # wait unt il network is idle so that SPA/Next.js DOM is loaded
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        html = page.content()
        browser.close()
    return html


def is_http_url(href: str) -> bool:
    if not href:
        return False
    href = href.strip()
    parsed = urlparse(href)
    if parsed.scheme in ("http", "https"):
        return True
    if parsed.scheme == "" and not href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        # relative URL
        return True
    return False


def extract_links(html: str, base_url: str):
    """
    Extract all <a href="..."> links from rendered HTML and normalize to absolute URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    raw_count = 0

    for a in soup.find_all("a", href=True):
        raw_href = a.get("href")
        raw_count += 1
        if not is_http_url(raw_href):
            continue
        abs_url = urljoin(base_url, raw_href)
        links.add(abs_url)

    print(f"[INFO] Raw <a> tags with href found: {raw_count}")
    print(f"[INFO] Unique checkable HTTP(S) links: {len(links)}")
    return sorted(links)


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0 Safari/537.36"
        )
    })
    return session


def check_link(session: requests.Session, url: str, timeout: int = 10):
    """
    Returns (is_broken, info_string).
    is_broken: True if HTTP status >= 400 or request fails.
    info_string: status or error message.
    """
    try:
        # try HEAD first (cheap); fall back to GET if needed
        try:
            resp = session.head(url, allow_redirects=True, timeout=timeout)
            code = resp.status_code
            if code >= 400:
                return True, f"HTTP {code} (HEAD)"
            if code in (405, 403):
                raise requests.RequestException(f"HEAD not reliable: {code}")
            return False, f"HTTP {code} (HEAD)"
        except requests.RequestException:
            resp = session.get(url, allow_redirects=True, timeout=timeout)
            code = resp.status_code
            if code >= 400:
                return True, f"HTTP {code} (GET)"
            return False, f"HTTP {code} (GET)"
    except requests.RequestException as e:
        return True, f"Error: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Check all links on a webpage (including React/Next.js) and report broken ones."
    )
    parser.add_argument(
        "url",
        help="URL of the webpage to scan for links (e.g. https://example.com)",
    )
    parser.add_argument(
        "--no-js",
        action="store_true",
        help="Skip JS rendering and just download raw HTML with requests (for plain sites).",
    )
    args = parser.parse_args()

    url = args.url
    session = create_session()

    if args.no_js:
        # Raw HTML only (non-SPA)
        print(f"[INFO] Fetching raw HTML (no JS) from: {url}")
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except requests.RequestException as e:
            print(f"[ERROR] Could not fetch {url}: {e}")
            sys.exit(1)
    else:
        # JS-rendered (React/Next.js/etc.)
        print(f"[INFO] Rendering page with Playwright (Chromium): {url}")
        try:
            html = get_rendered_html(url)
        except Exception as e:
            print(f"[ERROR] Playwright failed to render page: {e}")
            sys.exit(1)

    print("[INFO] Extracting links from DOM...")
    links = extract_links(html, url)

    if not links:
        print("[WARN] 0 checkable links found after rendering. Inspect the HTML or relax filters.")
        sys.exit(0)

    broken_links = []
    total = len(links)
    print(f"[INFO] Starting HTTP checks for {total} link(s)...")

    for i, link in enumerate(links, start=1):
        print(f"[CHECK] ({i}/{total}) {link}")
        is_broken, info = check_link(session, link)
        if is_broken:
            print(f"  -> BROKEN: {info}")
            broken_links.append((link, info))
        else:
            print(f"  -> OK: {info}")

    print("\n=== SUMMARY ===")
    print(f"Total links checked: {total}")
    print(f"Broken links found: {len(broken_links)}")

    if broken_links:
        print("\nBroken links:")
        for link, info in broken_links:
            print(f"- {link}  [{info}]")


if __name__ == "__main__":
    main()
