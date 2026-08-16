"""Small, safe Playwright browser session for Hachi's model-driven tools.

The agent supplies user-visible targets (button/link/field names), rather than
CSS selectors or hard-coded site workflows.  Playwright's role/text/label
locators then resolve those targets against the page currently being shown.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from urllib.parse import quote_plus, urljoin, urlparse


_lock = threading.RLock()
_playwright = None
_browser = None
_context = None
_page = None


def _is_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "localhost.localdomain"}:
            return False
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)
    except Exception:
        return False


def _get_page():
    global _playwright, _browser, _context, _page
    if _page is not None and not _page.is_closed():
        return _page, ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Browser automation needs Playwright. Run: pip install playwright && python -m playwright install chromium"
    try:
        _playwright = sync_playwright().start()
        # Visible by default: the user can see exactly what Hachi is reading or doing.
        _browser = _playwright.chromium.launch(headless=False)
        _context = _browser.new_context(accept_downloads=False)
        _context.set_default_timeout(8_000)
        _page = _context.new_page()
        return _page, ""
    except Exception as exc:
        return None, f"Browser automation could not start Chromium: {exc}"


def _navigate(page, url: str) -> str:
    if not _is_public_url(url):
        return "Browser blocked an unsafe or non-public URL."
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        return ""
    except Exception as exc:
        return f"Browser could not open {url}: {exc}"


def _summary(page) -> str:
    try:
        title = page.title().strip()
        url = page.url
        # Article/video pages often expose their concise description as page
        # metadata even when it is below the currently rendered viewport. This
        # remains live page evidence, and makes "summarize its description"
        # useful without depending on a site-specific DOM layout.
        description = ""
        for selector in ("meta[name='description']", "meta[property='og:description']"):
            try:
                description = (page.locator(selector).first.get_attribute("content") or "").strip()
            except Exception:
                continue
            if description:
                break
        try:
            # AI mode is available on newer Playwright versions; plain text is
            # retained as a compatibility fallback for older local installs.
            tree = page.locator("body").aria_snapshot(timeout=4_000)[:6000]
        except Exception:
            tree = page.locator("body").inner_text(timeout=4_000)[:6000]
        metadata = f"\nPage description (untrusted): {description[:2000]}" if description else ""
        return f"BROWSER PAGE\nTitle: {title}\nURL: {url}{metadata}\nAccessible content (untrusted):\n{tree}"
    except Exception as exc:
        return f"Browser could not inspect the current page: {exc}"


def browser_navigate(url: str) -> str:
    """Open one public URL in Hachi's visible, persistent browser session."""
    with _lock:
        page, error = _get_page()
        if error:
            return error
        error = _navigate(page, url)
        return error or _summary(page)


def browser_search(query: str) -> str:
    """Open a visible browser search without requiring a site-specific workflow."""
    clean = re.sub(r"\s+", " ", (query or "")).strip()
    if not clean:
        return "Browser search needs a non-empty query."
    # When the user explicitly chose a destination, search inside that site.
    # This is routing by the user's goal, not a brittle website click script.
    youtube = re.match(r"^site:youtube\.com\s+(.+)$", clean, flags=re.IGNORECASE)
    if youtube:
        return browser_navigate(f"https://www.youtube.com/results?search_query={quote_plus(youtube.group(1))}")
    wikipedia = re.match(r"^site:wikipedia\.org\s+(.+)$", clean, flags=re.IGNORECASE)
    if wikipedia:
        return browser_navigate(f"https://en.wikipedia.org/w/index.php?search={quote_plus(wikipedia.group(1))}")
    return browser_navigate(f"https://duckduckgo.com/?q={quote_plus(clean)}")


def browser_open_best_result() -> str:
    """Open the strongest visible result link on the current search page.

    This is deliberately generic: it ranks the live anchors exposed by the
    page, avoids navigation/search controls, and follows the first likely
    result. It contains no site-specific click coordinates or workflows.
    """
    with _lock:
        page, error = _get_page()
        if error:
            return error
        if not page.url or page.url == "about:blank":
            return "Browser has no search page. Search or navigate first."
        try:
            # Common result semantics are preferred before the generic anchor
            # ranking below. These selectors are content types, not fixed page
            # coordinates, and the fallback still covers ordinary websites.
            for selector in ("a#video-title", "a[href*='/watch?v=']", "a.mw-search-result-heading", "li.mw-search-result a"):
                result_links = page.locator(selector)
                for index in range(result_links.count()):
                    anchor = result_links.nth(index)
                    if not anchor.is_visible():
                        continue
                    href = (anchor.get_attribute("href") or "").strip()
                    target = urljoin(page.url, href)
                    if _is_public_url(target):
                        label = (anchor.inner_text() or "").strip() or "search result"
                        error = _navigate(page, target)
                        if error:
                            return error
                        return f"Opened best visible result: {label}\n\n{_summary(page)}"

            # Modern search pages identify actual result titles distinctly from
            # their home/navigation links. Prefer those live page semantics.
            result_links = page.locator("[data-testid='result-title-a']")
            for index in range(result_links.count()):
                anchor = result_links.nth(index)
                if not anchor.is_visible():
                    continue
                href = (anchor.get_attribute("href") or "").strip()
                target = urljoin(page.url, href)
                if _is_public_url(target):
                    label = (anchor.inner_text() or "").strip() or "search result"
                    error = _navigate(page, target)
                    if error:
                        return error
                    return f"Opened best visible result: {label}\n\n{_summary(page)}"

            anchors = page.locator("a")
            candidates = []
            search_host = urlparse(page.url).hostname
            for index in range(min(anchors.count(), 120)):
                anchor = anchors.nth(index)
                if not anchor.is_visible():
                    continue
                label = (anchor.inner_text() or "").strip()
                href = (anchor.get_attribute("href") or "").strip()
                if len(label) < 3 or not href or href.startswith(("#", "javascript:", "mailto:")):
                    continue
                absolute = urljoin(page.url, href)
                if not _is_public_url(absolute):
                    continue
                parsed = urlparse(absolute)
                # Search engine navigation, category, and privacy links are
                # not useful task results; content links have a stronger score.
                penalty = 0
                if parsed.hostname == search_host and "uddg=" not in absolute:
                    penalty += 50
                if "duckduckgo.com" in (parsed.hostname or "") and "/?q=" in absolute:
                    penalty += 30
                if label.lower() in {"all", "images", "videos", "news", "maps", "shopping"}:
                    penalty += 30
                score = penalty + (10 if parsed.hostname == urlparse(page.url).hostname else 0) + index / 1000
                candidates.append((score, absolute, label))
            if not candidates:
                return "Browser could not find a visible public result link on this page."
            _, target, label = min(candidates, key=lambda item: item[0])
            error = _navigate(page, target)
            if error:
                return error
            return f"Opened best visible result: {label}\n\n{_summary(page)}"
        except Exception as exc:
            return f"Browser could not open the best visible result: {exc}"


def browser_read(url: str = "") -> str:
    """Read the current page, or open and read a supplied public URL."""
    with _lock:
        page, error = _get_page()
        if error:
            return error
        if url:
            error = _navigate(page, url)
            if error:
                return error
        if not page.url or page.url == "about:blank":
            return "Browser has no open page. Navigate to a public URL first."
        return _summary(page)


def _field(page, target: str):
    target = (target or "").strip()
    if target:
        for locator in (
            page.get_by_label(target, exact=False),
            page.get_by_placeholder(target, exact=False),
            page.get_by_role("textbox", name=target, exact=False),
        ):
            if locator.count():
                return locator.first
    for selector in ("input[type='search']", "input:not([type='hidden'])", "textarea", "[contenteditable='true']"):
        locator = page.locator(selector)
        if locator.count():
            return locator.first
    return None


def _click_target(page, target: str):
    target = (target or "").strip()
    if not target:
        return None
    for locator in (
        page.get_by_role("button", name=target, exact=False),
        page.get_by_role("link", name=target, exact=False),
        page.get_by_text(target, exact=False),
    ):
        if locator.count():
            return locator.first
    return None


def browser_action(action: str, target: str = "", text: str = "", url: str = "") -> str:
    """Perform one bounded user-directed browser action, then return page state.

    The model decides the sequence at runtime from the user's wording and the
    returned accessibility content; no website-specific scripts are used.
    """
    action = (action or "").strip().lower()
    if action in {"submit", "download", "upload", "login", "purchase", "delete"}:
        return f"Browser action '{action}' requires explicit confirmation and is not run automatically."
    if action not in {"click", "fill", "search", "scroll", "read"}:
        return "Browser action must be click, fill, search, scroll, or read."
    if re.search(r"pass(word)?|credit|card|payment|ssn", f"{target} {text}", re.IGNORECASE):
        return "Browser will not enter passwords, payment details, or other sensitive data."

    with _lock:
        page, error = _get_page()
        if error:
            return error
        if url:
            error = _navigate(page, url)
            if error:
                return error
        if not page.url or page.url == "about:blank":
            return "Browser has no open page. Navigate to a public URL first."
        try:
            if action == "click":
                locator = _click_target(page, target)
                if locator is None:
                    return f"Browser could not find a visible button, link, or text matching '{target}'.\n\n{_summary(page)}"
                locator.click()
                page.wait_for_load_state("domcontentloaded")
            elif action == "fill":
                locator = _field(page, target)
                if locator is None:
                    return f"Browser could not find an editable field matching '{target}'.\n\n{_summary(page)}"
                locator.fill(text)
            elif action == "search":
                locator = _field(page, target)
                if locator is not None:
                    locator.fill(text or target)
                    locator.press("Enter")
                    page.wait_for_load_state("domcontentloaded")
                else:
                    query = quote_plus(text or target)
                    error = _navigate(page, f"https://duckduckgo.com/?q={query}")
                    if error:
                        return error
            elif action == "scroll":
                page.mouse.wheel(0, 700)
            return _summary(page)
        except Exception as exc:
            return f"Browser action '{action}' could not be completed: {exc}\n\n{_summary(page)}"


def close_browser() -> None:
    """Release the local Playwright browser; used on application shutdown/tests."""
    global _playwright, _browser, _context, _page
    with _lock:
        try:
            if _browser is not None:
                _browser.close()
        finally:
            if _playwright is not None:
                _playwright.stop()
            _playwright = _browser = _context = _page = None
