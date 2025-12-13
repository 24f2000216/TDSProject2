# scraper.py
"""
Complete page scraper using Playwright.
Extracts HTML, screenshots, links, code blocks, and processes all resources.
"""

import asyncio
import base64
import logging
from io import BytesIO
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
import re

from playwright.async_api import async_playwright, Page
import httpx

logger = logging.getLogger(__name__)

class PageScraper:
    """Complete page scraper that extracts everything from a quiz page."""
    
    def __init__(self, browser_timeout_ms: int = 30000, fetch_timeout: int = 30, max_retries: int = 3):
        self.browser_timeout_ms = browser_timeout_ms
        self.fetch_timeout = fetch_timeout
        self.max_retries = max_retries
        self.playwright = None
        self.browser = None
        self.page = None
    
    async def launch_browser(self):
        """Launch Playwright browser."""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"]
            )
            self.page = await self.browser.new_page()
            self.page.set_default_timeout(self.browser_timeout_ms)
            logger.info("✅ Browser launched successfully")
        except Exception as e:
            logger.error(f"❌ Browser launch failed: {e}")
            raise
    
    async def close_browser(self):
        """Close browser and cleanup."""
        try:
            if self.page:
                await self.page.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("✅ Browser closed successfully")
        except Exception as e:
            logger.error(f"❌ Browser close error: {e}")
    
    async def fetch_resource(self, url: str) -> Optional[bytes]:
        """Fetch resource with retry logic."""
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.fetch_timeout) as client:
                    response = await client.get(url, follow_redirects=True)
                    response.raise_for_status()
                    logger.info(f"✅ Fetched: {url}")
                    return response.content
            except Exception as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1.0 * (2 ** attempt))  # Exponential backoff
                else:
                    logger.warning(f"❌ Failed to fetch after retries: {url}")
        return None
    
    def _get_base_url(self, url: str) -> str:
        """Get base URL without query params."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    async def scrape_everything(self, url: str) -> Dict[str, Any]:
        """
        Scrape entire page and all resources.
        
        Returns:
            Dictionary containing all extracted data
        """
        await self.launch_browser()
        
        try:
            logger.info(f"🔍 Scraping: {url}")
            
            # Navigate and wait for network idle
            await self.page.goto(url, wait_until="networkidle")
            
            # Extract HTML
            html = await self.page.content()
            logger.info("✅ Extracted HTML")
            
            # Capture screenshot
            screenshot_bytes = await self.page.screenshot()
            logger.info("✅ Captured screenshot")
            
            # Extract code blocks
            code_blocks = []
            elements = await self.page.query_selector_all("pre, code")
            for elem in elements:
                text = await elem.inner_text()
                if text.strip():
                    code_blocks.append(text.strip())
            logger.info(f"✅ Extracted {len(code_blocks)} code blocks")
            
            # Extract all links
            links = []
            base_url = self._get_base_url(self.page.url)
            
            for selector, attr in [("a", "href"), ("img", "src"), ("audio", "src"), 
                                   ("video", "src"), ("script", "src"), ("link", "href")]:
                elements = await self.page.query_selector_all(selector)
                for elem in elements:
                    value = await elem.get_attribute(attr)
                    if value:
                        absolute_url = urljoin(base_url, value)
                        links.append(absolute_url)
            
            logger.info(f"✅ Extracted {len(links)} links")
            
            # Extract text from page
            page_text = await self.page.inner_text("body")
            
            return {
                "url": url,
                "html": html,
                "screenshot_base64": base64.b64encode(screenshot_bytes).decode() if screenshot_bytes else "",
                "page_text": page_text,
                "code_blocks": code_blocks,
                "links": list(set(links)),  # Remove duplicates
            }
            
        except Exception as e:
            logger.error(f"❌ Scraping error: {e}")
            return None
        
        finally:
            await self.close_browser()

#use the above scraper function make make a requestion to a url to scrape it
