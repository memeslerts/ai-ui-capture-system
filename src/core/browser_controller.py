from playwright.async_api import async_playwright, Page, Browser, BrowserContext
import asyncio
from typing import Optional, Dict, Any, List
from pathlib import Path
import logging
import json

logger = logging.getLogger(__name__)

class BrowserController:
    """
    browser automation controller with persistent session support.
    """
    
    def __init__(self, headless: bool = False, session_file: str = None):
        """initialize browser controller."""
        self.headless = headless
        self.session_file = session_file or "./browser_session.json"
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.user_data_dir = "./browser_data"  # persistent user data
    
    async def initialize(self):
        """start browser and create page with persistent session."""
        logger.info("starting browser...")
        
        self.playwright = await async_playwright().start()
        
        # create user data directory
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)
        
        # launch with persistent context to save cookies/storage
        self.context = await self.playwright.chromium.launch_persistent_context(
            self.user_data_dir,
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ],
            viewport={'width': 1900, 'height': 1000},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            accept_downloads=True,
            ignore_https_errors=True
        )
        
        # get the first page or create one
        if len(self.context.pages) > 0:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        
        self.page.set_default_timeout(30000)
        
        logger.info("browser started successfully with persistent session")
        
        # check if already logged in
        await self._check_login_status()
    
    async def _check_login_status(self):
        """check if user is already logged in based on saved session."""
        try:
            # check for auth cookies
            cookies = await self.context.cookies()
            auth_cookies = [c for c in cookies if 'session' in c.get('name', '').lower() 
                           or 'auth' in c.get('name', '').lower()
                           or 'token' in c.get('name', '').lower()]
            
            if auth_cookies:
                logger.info(f"found {len(auth_cookies)} authentication cookies - likely logged in")
            else:
                logger.info("no authentication cookies found - may need to log in")
        except Exception as e:
            logger.debug(f"could not check login status: {e}")
    
    async def navigate_to(self, url: str, wait_until: str = 'networkidle'):
        """navigate to url."""
        logger.info(f"navigating to {url}...")
        
        try:
            await self.page.goto(url, wait_until=wait_until)
            await self.wait_for_stability()
            logger.info(f"navigation to {url} completed")
        except Exception as e:
            logger.error(f"failed to navigate to {url}: {e}")
            raise
    
    async def wait_for_stability(self, timeout: int = 5000):
        """wait for page to become stable."""
        logger.debug("waiting for page stability...")
        try:
            await self.page.wait_for_load_state('networkidle', timeout=timeout)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"page did not stabilize: {e}")
    
    async def click(self, locator, description: str = "element") -> bool:
        """click an element with smart handling."""
        try:
            logger.info(f"clicking {description}")
            
            # scroll into view
            await locator.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            
            # wait for element to be ready
            await locator.wait_for(state='visible', timeout=5000)
            
            # try regular click
            await locator.click(timeout=5000)
            
            # wait for any reactions
            await asyncio.sleep(0.5)
            await self.wait_for_stability(timeout=3000)
            
            logger.info(f"clicked {description} successfully")
            return True
            
        except Exception as e:
            logger.warning(f"regular click failed: {e}, trying force click")
            
            try:
                # try force click
                await locator.click(force=True, timeout=5000)
                await asyncio.sleep(0.5)
                logger.info(f"force clicked {description} successfully")
                return True
            except Exception as e2:
                logger.error(f"click failed on {description}: {e2}")
                return False
    
    async def fill(self, locator, value: str, description: str = "field") -> bool:
        """fill input field with smart handling."""
        try:
            logger.info(f"filling {description} with: {value[:50]}")
            
            # scroll into view
            await locator.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            
            # check if it's contenteditable
            is_contenteditable = await locator.evaluate(
                'el => el.getAttribute("contenteditable") === "true"'
            )
            
            if is_contenteditable:
                # handle contenteditable differently
                await locator.click()
                await asyncio.sleep(0.2)
                
                # clear existing content
                await self.page.keyboard.press('Control+a')
                await self.page.keyboard.press('Backspace')
                
                # type new content
                await locator.type(value, delay=50)
                
            else:
                # regular input
                await locator.clear()
                await locator.fill(value)
            
            await asyncio.sleep(0.3)
            logger.info(f"filled {description} successfully")
            return True
            
        except Exception as e:
            logger.error(f"fill failed on {description}: {e}")
            return False
    
    async def type_sequence(self, text: str, delay: int = 50) -> bool:
        """type text with keyboard."""
        try:
            logger.info(f"typing sequence: {text[:50]}")
            await self.page.keyboard.type(text, delay=delay)
            await asyncio.sleep(0.3)
            logger.info("typed sequence successfully")
            return True
        except Exception as e:
            logger.error(f"type sequence failed: {e}")
            return False
    
    async def keyboard_navigate_menu(
        self,
        target_text: str,
        max_attempts: int = 10
    ) -> bool:
        """navigate a menu using arrow keys."""
        try:
            logger.info(f"navigating menu with keyboard to find: {target_text}")
            
            await asyncio.sleep(0.5)
            
            for attempt in range(max_attempts):
                # get currently highlighted item
                highlighted = await self.page.evaluate('''() => {
                    const focused = document.activeElement;
                    if (focused) return focused.textContent;
                    
                    const selected = document.querySelector('[aria-selected="true"]');
                    if (selected) return selected.textContent;
                    
                    const highlighted = document.querySelector('[class*="highlight"], [class*="selected"]');
                    if (highlighted) return highlighted.textContent;
                    
                    return '';
                }''')
                
                logger.debug(f"attempt {attempt + 1}: current item = {highlighted[:50] if highlighted else 'none'}")
                
                # check if we found our target
                if highlighted and target_text.lower() in highlighted.lower():
                    logger.info(f"found target item: {highlighted[:50]}")
                    await self.page.keyboard.press('Enter')
                    await asyncio.sleep(0.5)
                    return True
                
                # press down arrow to move to next item
                await self.page.keyboard.press('ArrowDown')
                await asyncio.sleep(0.2)
            
            logger.warning(f"could not find menu item: {target_text}")
            return False
            
        except Exception as e:
            logger.error(f"keyboard menu navigation failed: {e}")
            return False
    
    async def hover(self, locator, description: str = "element") -> bool:
        """hover over element."""
        try:
            logger.info(f"hovering over {description}")
            
            await locator.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            
            await locator.hover()
            await asyncio.sleep(0.5)
            
            logger.info(f"hovered over {description} successfully")
            return True
            
        except Exception as e:
            logger.error(f"hover failed on {description}: {e}")
            return False
    
    async def press_key(self, key: str, locator=None) -> bool:
        """press keyboard key."""
        try:
            if locator:
                await locator.press(key)
            else:
                await self.page.keyboard.press(key)
            
            await asyncio.sleep(0.3)
            logger.info(f"pressed key: {key}")
            return True
            
        except Exception as e:
            logger.error(f"key press failed: {e}")
            return False
    
    async def wait(self, seconds: float):
        """wait for specified time."""
        logger.info(f"waiting {seconds} seconds")
        await asyncio.sleep(seconds)
    
    async def save_session(self):
        """save browser session (already persistent with launch_persistent_context)."""
        logger.info("session automatically saved with persistent context")
        # cookies and storage are automatically saved to user_data_dir
    
    def has_saved_session(self) -> bool:
        """check if saved session exists."""
        user_data_path = Path(self.user_data_dir)
        return user_data_path.exists() and any(user_data_path.iterdir())
    
    async def clear_session(self):
        """delete saved session."""
        import shutil
        user_data_path = Path(self.user_data_dir)
        if user_data_path.exists():
            shutil.rmtree(user_data_path)
            logger.info(f"session data deleted: {self.user_data_dir}")
        else:
            logger.info("no session data to delete")
    
    async def get_page_state(self) -> Dict:
        """get current page state for decision making."""
        try:
            state = await self.page.evaluate('''() => {
                const isVisible = (el) => {
                    return el.offsetParent !== null && 
                           window.getComputedStyle(el).visibility !== 'hidden' &&
                           window.getComputedStyle(el).display !== 'none';
                };
                
                return {
                    url: window.location.href,
                    title: document.title,
                    has_modal: document.querySelectorAll('[role="dialog"]').length > 0,
                    has_menu: document.querySelectorAll('[role="menu"]').length > 0,
                    input_count: Array.from(document.querySelectorAll('input, textarea')).filter(isVisible).length,
                    button_count: Array.from(document.querySelectorAll('button')).filter(isVisible).length
                };
            }''')
            return state
        except:
            return {}
    
    async def close(self):
        """close browser and cleanup."""
        logger.info("closing browser...")
        # session is automatically saved with persistent context
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("browser closed - session persisted")