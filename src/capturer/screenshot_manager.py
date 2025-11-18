from playwright.async_api import Page, Locator
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import logging
import asyncio

logger = logging.getLogger(__name__)

class ScreenshotManager:
    """
    intelligent screenshot capture focusing on relevant ui changes.
    """
    
    def __init__(self, output_dir: str = "screenshots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def capture_state(
        self,
        page: Page,
        step_name: str,
        task_id: str,
        annotation: Optional[str] = None,
        highlight_element: Optional[Locator] = None
    ) -> Dict[str, str]:
        """
        capture current ui state intelligently.
        
        args:
            page: playwright page
            step_name: name of this step
            task_id: task identifier
            annotation: optional text annotation
            highlight_element: optional element to highlight
            
        returns:
            dict of captured screenshot paths
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        task_dir = self.output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        result = {}
        
        # detect what's visible
        ui_state = await self._detect_ui_elements(page)
        
        # capture modal if present
        # if ui_state['has_modal']:
        #     modal_path = await self._capture_modal(page, task_dir, step_name, timestamp)
        #     if modal_path:
        #         result['modal'] = modal_path
        #         logger.info(f"captured modal: {Path(modal_path).name}")
        
        # capture menu if present
        # if ui_state['has_menu']:
        #     menu_path = await self._capture_menu(page, task_dir, step_name, timestamp)
        #     if menu_path:
        #         result['menu'] = menu_path
        #         logger.info(f"captured menu: {Path(menu_path).name}")
        
        # priority 3: highlight element if provided
        if highlight_element:
            try:
                highlighted_path = await self._capture_with_highlight(
                    page, highlight_element, task_dir, step_name, timestamp, annotation or ""
                )
                if highlighted_path:
                    result['highlighted'] = highlighted_path
                    logger.info(f"captured highlighted: {Path(highlighted_path).name}")
            except Exception as e:
                logger.debug(f"highlight capture failed: {e}")
        
        # always capture viewport for context
        viewport_path = task_dir / f"{step_name}_{timestamp}_viewport.png"
        try:
            await page.screenshot(path=str(viewport_path), full_page=False)
            result['viewport'] = str(viewport_path)
            logger.info(f"captured viewport: {viewport_path.name}")
        except Exception as e:
            logger.error(f"viewport capture failed: {e}")
        
        # capture full page if nothing else captured
        if len(result) == 1:  # only viewport
            full_path = task_dir / f"{step_name}_{timestamp}_full.png"
            try:
                await page.screenshot(path=str(full_path), full_page=True)
                result['full_page'] = str(full_path)
                logger.info(f"captured full page: {full_path.name}")
            except:
                pass
        
        return result
    
    async def _detect_ui_elements(self, page: Page) -> Dict:
        """detect what ui elements are currently visible."""
        state = await page.evaluate('''() => {
            const isVisible = (el) => {
                return el.offsetParent !== null && 
                       window.getComputedStyle(el).visibility !== 'hidden' &&
                       window.getComputedStyle(el).display !== 'none';
            };
            
            const modals = Array.from(document.querySelectorAll(
                '[role="dialog"], .modal, [class*="Modal"], [class*="modal"]'
            )).filter(isVisible);
            
            const menus = Array.from(document.querySelectorAll(
                '[role="menu"], [role="listbox"], [class*="dropdown"]'
            )).filter(isVisible);
            
            const overlays = Array.from(document.querySelectorAll(
                '[class*="overlay"], [class*="backdrop"]'
            )).filter(isVisible);
            
            return {
                has_modal: modals.length > 0,
                has_menu: menus.length > 0,
                has_overlay: overlays.length > 0,
                modal_count: modals.length,
                menu_count: menus.length
            };
        }''')
        
        return state
    
    async def _capture_modal(
        self,
        page: Page,
        task_dir: Path,
        step_name: str,
        timestamp: str
    ) -> Optional[str]:
        """capture modal dialog."""
        try:
            # try multiple modal selectors
            selectors = [
                '[role="dialog"]',
                '.modal',
                '[class*="Modal"]',
                '[class*="modal"]'
            ]
            
            for selector in selectors:
                modal = page.locator(selector).first
                if await modal.count() > 0 and await modal.is_visible():
                    modal_path = task_dir / f"{step_name}_{timestamp}_modal.png"
                    await modal.screenshot(path=str(modal_path))
                    return str(modal_path)
            
        except Exception as e:
            logger.debug(f"modal capture failed: {e}")
        
        return None
    
    async def _capture_menu(
        self,
        page: Page,
        task_dir: Path,
        step_name: str,
        timestamp: str
    ) -> Optional[str]:
        """capture menu/dropdown."""
        try:
            selectors = [
                '[role="menu"]',
                '[role="listbox"]',
                '[class*="dropdown-menu"]',
                '[class*="Dropdown"]'
            ]
            
            for selector in selectors:
                menu = page.locator(selector).first
                if await menu.count() > 0 and await menu.is_visible():
                    menu_path = task_dir / f"{step_name}_{timestamp}_menu.png"
                    await menu.screenshot(path=str(menu_path))
                    return str(menu_path)
            
        except Exception as e:
            logger.debug(f"menu capture failed: {e}")
        
        return None
    
    async def _capture_with_highlight(
        self,
        page: Page,
        element: Locator,
        task_dir: Path,
        step_name: str,
        timestamp: str,
        description: str
    ) -> Optional[str]:
        """capture element with visual highlight."""
        try:
            # add highlight
            await element.evaluate('''(el, desc) => {
                el._originalStyle = {
                    outline: el.style.outline,
                    outlineOffset: el.style.outlineOffset,
                    boxShadow: el.style.boxShadow
                };
                
                el.style.outline = '3px solid #FF6B6B';
                el.style.outlineOffset = '2px';
                el.style.boxShadow = '0 0 10px rgba(255, 107, 107, 0.5)';
                
                if (desc) {
                    const label = document.createElement('div');
                    label.id = '_highlight_label';
                    label.textContent = desc;
                    label.style.cssText = `
                        position: absolute;
                        background: #FF6B6B;
                        color: white;
                        padding: 4px 8px;
                        border-radius: 4px;
                        font-size: 12px;
                        font-weight: bold;
                        z-index: 10000;
                        pointer-events: none;
                    `;
                    
                    const rect = el.getBoundingClientRect();
                    label.style.left = rect.left + 'px';
                    label.style.top = (rect.top - 30) + 'px';
                    
                    document.body.appendChild(label);
                }
            }''', description)
            
            # scroll into view
            await element.scroll_into_view_if_needed()
            await asyncio.sleep(0.3)
            
            # take screenshot
            highlighted_path = task_dir / f"{step_name}_{timestamp}_highlighted.png"
            await page.screenshot(path=str(highlighted_path))
            
            # remove highlight
            await element.evaluate('''el => {
                if (el._originalStyle) {
                    el.style.outline = el._originalStyle.outline;
                    el.style.outlineOffset = el._originalStyle.outlineOffset;
                    el.style.boxShadow = el._originalStyle.boxShadow;
                }
                const label = document.getElementById('_highlight_label');
                if (label) label.remove();
            }''')
            
            return str(highlighted_path)
            
        except Exception as e:
            logger.warning(f"highlight capture failed: {e}")
        
        return None
    
    async def capture_error_state(
        self,
        page: Page,
        step_name: str,
        task_id: str,
        error_msg: str
    ) -> Dict[str, str]:
        """capture state when error occurs."""
        logger.info(f"capturing error state: {error_msg[:100]}")
        return await self.capture_state(
            page,
            f"{step_name}_error",
            task_id,
            annotation=f"error: {error_msg[:50]}"
        )