from playwright.async_api import Page
import hashlib
import json
import logging
from typing import Dict, Optional
import asyncio
import time

logger = logging.getLogger(__name__)

class StateDetector:
    """
    detects ui state changes by monitoring page signals.
    """
    
    def __init__(self, page: Page):
        """initialize with playwright page."""
        self.page = page
        self.previous_signature: Optional[str] = None
    
    async def capture_state_signature(self) -> str:
        """
        capture current ui state as a hash signature.
        
        returns:
            hash string representing current state
        """
        try:
            signals = await self.page.evaluate('''() => {
                return {
                    url: window.location.href,
                    title: document.title,
                    
                    // count modals
                    modalCount: document.querySelectorAll(
                        '[role="dialog"], .modal, [class*="Modal"], [class*="modal"]'
                    ).length,
                    
                    // count overlays
                    overlayCount: document.querySelectorAll(
                        '[class*="overlay"], [class*="backdrop"], [class*="Overlay"]'
                    ).length,
                    
                    // active element
                    activeElement: document.activeElement ? {
                        tag: document.activeElement.tagName,
                        type: document.activeElement.type || null,
                        id: document.activeElement.id || null,
                    } : null,
                    
                    // visible forms
                    visibleForms: Array.from(document.querySelectorAll('form')).filter(
                        f => f.offsetParent !== null
                    ).length,
                    
                    // loading indicators
                    loadingCount: document.querySelectorAll(
                        '[class*="loading"], [class*="spinner"], [class*="Loading"], [class*="Spinner"]'
                    ).length,
                    
                    // menus
                    menuCount: document.querySelectorAll(
                        '[role="menu"], [role="listbox"]'
                    ).length,
                    
                    // dom structure
                    bodyStructure: document.body ? {
                        childCount: document.body.children.length,
                        classes: document.body.className
                    } : null,
                };
            }''')
            
            # convert to json and hash
            json_str = json.dumps(signals, sort_keys=True)
            signature = hashlib.sha256(json_str.encode()).hexdigest()
            
            logger.debug(
                f"state: {signature[:8]}... "
                f"modals: {signals['modalCount']}, "
                f"menus: {signals['menuCount']}"
            )
            
            return signature
            
        except Exception as e:
            logger.error(f"error capturing state signature: {e}")
            return ""
    
    async def has_state_changed(self) -> bool:
        """
        check if ui state has changed since last check.
        
        returns:
            true if state changed, false otherwise
        """
        current_signature = await self.capture_state_signature()
        
        if self.previous_signature is None:
            # first time
            self.previous_signature = current_signature
            return True
        
        changed = current_signature != self.previous_signature
        
        if changed:
            logger.info("ui state has changed")
            self.previous_signature = current_signature
        
        return changed
    
    async def wait_for_state_change(self, timeout: int = 10000, poll_interval: float = 0.5) -> bool:
        """
        wait until ui state changes or timeout.
        
        args:
            timeout: maximum time to wait in milliseconds
            poll_interval: how often to check in seconds
            
        returns:
            true if state changed within timeout, false if timed out
        """
        start_time = time.time()
        timeout_seconds = timeout / 1000
        
        initial_signature = await self.capture_state_signature()
        
        logger.debug("waiting for ui state change...")
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                logger.debug("timeout waiting for ui state change")
                return False
            
            await asyncio.sleep(poll_interval)
            
            current_signature = await self.capture_state_signature()
            if current_signature != initial_signature:
                logger.info("ui state change detected")
                self.previous_signature = current_signature
                return True
    
    async def detect_modal_state(self) -> Dict:
        """
        check for modals/dialogs.
        
        returns:
            dict with modal presence and info
        """
        return await self.page.evaluate('''() => {
            const modals = document.querySelectorAll(
                '[role="dialog"], .modal, [class*="Modal"]'
            );
            
            const visibleModals = Array.from(modals).filter(
                m => m.offsetParent !== null
            );
            
            return {
                hasModal: visibleModals.length > 0,
                modalCount: visibleModals.length,
                modalInfo: visibleModals.map(m => ({
                    title: m.querySelector('[role="heading"]')?.textContent || null,
                    hasForm: m.querySelector('form') !== null,
                    buttons: Array.from(m.querySelectorAll('button')).map(
                        b => b.textContent.trim()
                    )
                }))
            };
        }''')
    
    async def detect_menu_state(self) -> Dict:
        """
        check for open menus/dropdowns.
        
        returns:
            dict with menu presence and info
        """
        return await self.page.evaluate('''() => {
            const menus = document.querySelectorAll(
                '[role="menu"], [role="listbox"]'
            );
            
            const visibleMenus = Array.from(menus).filter(
                m => m.offsetParent !== null
            );
            
            return {
                hasMenu: visibleMenus.length > 0,
                menuCount: visibleMenus.length,
                menuInfo: visibleMenus.map(m => ({
                    items: Array.from(m.querySelectorAll('[role="menuitem"]')).map(
                        item => item.textContent.trim()
                    ).slice(0, 10)
                }))
            };
        }''')