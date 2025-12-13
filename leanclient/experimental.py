"""Experimental features with heavier dependencies.

This module provides advanced widget rendering capabilities using Playwright
for headless browser automation. These features are optional and require
installing the 'experimental' extras:

    pip install leanclient[experimental]

Example usage:
    from leanclient.experimental import render_widget_to_png, WidgetRenderer

    # One-shot rendering
    png_bytes = render_widget_to_png(widget_html)

    # Reusable renderer (faster for multiple renders)
    with WidgetRenderer() as renderer:
        png1 = renderer.render(html1)
        png2 = renderer.render(html2)
"""

from __future__ import annotations

import base64
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

logger = logging.getLogger(__name__)

# Lazy import check
_playwright_available: bool | None = None


def _check_playwright() -> bool:
    """Check if playwright is available and installed."""
    global _playwright_available
    if _playwright_available is not None:
        return _playwright_available
    try:
        from playwright.sync_api import sync_playwright
        _playwright_available = True
    except ImportError:
        _playwright_available = False
        logger.warning(
            "Playwright not installed. Install with: pip install leanclient[experimental]"
        )
    return _playwright_available


def _ensure_browsers_installed() -> bool:
    """Ensure Playwright browsers are installed."""
    if not _check_playwright():
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # Try to launch - this will fail if browsers aren't installed
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as e:
        logger.warning(
            f"Playwright browsers not installed. Run: playwright install chromium\n"
            f"Error: {e}"
        )
        return False


class WidgetRenderer:
    """Headless browser renderer for Lean widgets.

    Uses Playwright to render widget HTML to PNG images. Reuse a single
    renderer instance for multiple renders to avoid browser startup overhead.

    Example:
        with WidgetRenderer() as renderer:
            png_bytes = renderer.render("<div>Hello</div>")
            base64_str = renderer.render_to_base64("<div>World</div>")
    """

    def __init__(self, width: int = 800, height: int = 600):
        """Initialize renderer.

        Args:
            width: Default viewport width in pixels
            height: Default viewport height in pixels
        """
        if not _check_playwright():
            raise ImportError(
                "Playwright not installed. Install with: pip install leanclient[experimental]"
            )
        self.width = width
        self.height = height
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def __enter__(self) -> "WidgetRenderer":
        """Start the browser."""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._page = self._browser.new_page(
            viewport={"width": self.width, "height": self.height}
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the browser."""
        if self._page:
            self._page.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._browser = None
        self._playwright = None

    def render(
        self,
        html: str,
        *,
        width: int | None = None,
        height: int | None = None,
        wait_ms: int = 100,
        full_page: bool = False,
    ) -> bytes:
        """Render HTML to PNG bytes.

        Args:
            html: HTML content to render
            width: Override viewport width
            height: Override viewport height
            wait_ms: Time to wait for JS to execute before screenshot
            full_page: If True, capture full scrollable page

        Returns:
            PNG image as bytes
        """
        if self._page is None:
            raise RuntimeError("Renderer not started. Use 'with WidgetRenderer():'")

        # Wrap in basic HTML structure if needed
        if not html.strip().startswith("<!DOCTYPE") and not html.strip().startswith("<html"):
            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ margin: 0; padding: 8px; font-family: system-ui, sans-serif; }}
        * {{ box-sizing: border-box; }}
    </style>
</head>
<body>{html}</body>
</html>"""

        # Set viewport if custom size requested
        if width or height:
            self._page.set_viewport_size({
                "width": width or self.width,
                "height": height or self.height,
            })

        self._page.set_content(html)
        if wait_ms > 0:
            self._page.wait_for_timeout(wait_ms)

        return self._page.screenshot(full_page=full_page)

    def render_to_base64(self, html: str, **kwargs) -> str:
        """Render HTML to base64-encoded PNG string.

        Args:
            html: HTML content to render
            **kwargs: Additional arguments passed to render()

        Returns:
            Base64-encoded PNG string
        """
        png_bytes = self.render(html, **kwargs)
        return base64.b64encode(png_bytes).decode("utf-8")


@contextmanager
def _get_renderer(width: int = 800, height: int = 600):
    """Context manager for one-shot rendering."""
    renderer = WidgetRenderer(width=width, height=height)
    with renderer:
        yield renderer


def render_widget_to_png(
    html: str,
    *,
    width: int = 800,
    height: int = 600,
    wait_ms: int = 100,
) -> bytes:
    """Render widget HTML to PNG bytes (one-shot).

    For multiple renders, use WidgetRenderer directly to avoid
    repeated browser startup overhead.

    Args:
        html: HTML content to render
        width: Viewport width in pixels
        height: Viewport height in pixels
        wait_ms: Time to wait for JS execution

    Returns:
        PNG image as bytes
    """
    with _get_renderer(width, height) as renderer:
        return renderer.render(html, wait_ms=wait_ms)


def render_widget_to_base64(
    html: str,
    *,
    width: int = 800,
    height: int = 600,
    wait_ms: int = 100,
) -> str:
    """Render widget HTML to base64-encoded PNG string (one-shot).

    For multiple renders, use WidgetRenderer directly to avoid
    repeated browser startup overhead.

    Args:
        html: HTML content to render
        width: Viewport width in pixels
        height: Viewport height in pixels
        wait_ms: Time to wait for JS execution

    Returns:
        Base64-encoded PNG string
    """
    with _get_renderer(width, height) as renderer:
        return renderer.render_to_base64(html, wait_ms=wait_ms)


def extract_images_from_widget_props(props: dict) -> list[tuple[str, str]]:
    """Extract base64 images from widget props.

    Many Lean widgets embed images directly in their props as base64 data.
    This function extracts them without needing to render HTML.

    Args:
        props: Widget props dictionary

    Returns:
        List of (mime_type, base64_data) tuples
    """
    images = []

    def _search(obj, depth: int = 0):
        if depth > 20:  # Prevent infinite recursion
            return
        if isinstance(obj, dict):
            # Check for direct base64/image keys
            if "base64" in obj and "mimeType" in obj:
                images.append((obj["mimeType"], obj["base64"]))
            elif "image" in obj and isinstance(obj["image"], str):
                # Try to detect mime type from data
                img = obj["image"]
                if img.startswith("data:"):
                    # Parse data URL
                    if "," in img:
                        header, data = img.split(",", 1)
                        mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
                        images.append((mime, data))
                elif len(img) > 100:  # Likely base64
                    images.append(("image/png", img))
            # Recurse
            for v in obj.values():
                _search(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _search(item, depth + 1)

    _search(props)
    return images


# Convenience check for availability
def is_available() -> bool:
    """Check if experimental features are available.

    Returns:
        True if playwright is installed and browsers are available
    """
    return _check_playwright() and _ensure_browsers_installed()
