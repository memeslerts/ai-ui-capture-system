from playwright.async_api import Page, Locator
from typing import Optional, List, Dict, Tuple
import logging
import re
import asyncio

logger = logging.getLogger(__name__)

class ElementLocator:
    """
    advanced element locator with specialized menu handling.
    """
    
    def __init__(self, page: Page):
        """initialize with a playwright page."""
        self.page = page
        self.cache = {}
    
    async def find_element(
        self, 
        description: str, 
        context: Optional[Dict] = None,
        element_type_hint: Optional[str] = None,
        in_menu: bool = False
    ) -> Optional[Locator]:
        """
        find an element using multiple strategies.
        
        args:
            description: natural language description
            context: additional context about what we're looking for
            element_type_hint: hint about element type (button, input, etc.)
            in_menu: whether to search specifically in menu/dropdown context
            
        returns:
            playwright locator or none
        """
        logger.info(f"locating: {description} (in_menu={in_menu})")
        
        # if searching in menu, use specialized menu finder
        if in_menu or self._looks_like_menu_item(description):
            locator = await self._find_in_menu(description)
            if locator:
                return locator
        
        # extract keywords and type
        keywords = self._extract_keywords(description)
        inferred_type = element_type_hint or self._infer_element_type(description)
        
        # try strategies in order of reliability
        strategies = [
            ("exact_match", self._find_by_exact_match),
            ("accessibility", self._find_by_accessibility),
            ("semantic_text", self._find_by_semantic_text),
            ("structure", self._find_by_structure),
            ("visual_context", self._find_by_visual_context),
            ("fuzzy_match", self._find_by_fuzzy_match)
        ]
        
        for strategy_name, strategy_func in strategies:
            try:
                locator = await strategy_func(description, keywords, inferred_type)
                if locator and await self._is_valid_locator(locator):
                    logger.info(f"found via {strategy_name}")
                    return locator
            except Exception as e:
                logger.debug(f"{strategy_name} failed: {e}")
                continue
        
        logger.warning(f"could not locate: {description}")
        return None
    
    async def _find_in_menu(self, description: str) -> Optional[Locator]:
        """
        specialized finder for menu items in dropdowns/popovers.
        handles dynamic menus that appear after clicking buttons.
        """
        logger.info(f"searching in menus for: {description}")
        
        # wait briefly for menu to be visible
        await asyncio.sleep(0.3)
        
        # get all visible menu containers
        menu_containers = await self.page.evaluate('''() => {
            const menuSelectors = [
                '[role="menu"]',
                '[role="listbox"]',
                '[class*="menu"]',
                '[class*="Menu"]',
                '[class*="dropdown"]',
                '[class*="Dropdown"]',
                '[class*="popover"]',
                '[class*="Popover"]',
                '[data-testid*="menu"]',
                '[data-testid*="dropdown"]'
            ];
            
            const containers = [];
            menuSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    const rect = el.getBoundingClientRect();
                    const isVisible = rect.width > 0 && rect.height > 0 && 
                                     window.getComputedStyle(el).visibility !== 'hidden' &&
                                     window.getComputedStyle(el).display !== 'none';
                    if (isVisible) {
                        containers.push({
                            selector: selector,
                            html: el.outerHTML.substring(0, 500),
                            text: el.textContent.substring(0, 500)
                        });
                    }
                });
            });
            return containers;
        }''')
        
        if not menu_containers:
            logger.debug("no visible menu containers found")
            return None
        
        logger.debug(f"found {len(menu_containers)} menu containers")
        
        keywords = self._extract_keywords(description)
        
        # strategy 1: find by exact text match in menu items
        menu_item_selectors = [
            '[role="menuitem"]',
            '[role="option"]',
            '[class*="MenuItem"]',
            '[class*="menu-item"]',
            '[class*="DropdownItem"]',
            '[class*="dropdown-item"]',
            'li[role="presentation"] a',
            'li[role="presentation"] button',
            'li[role="presentation"] div'
        ]
        
        for selector in menu_item_selectors:
            # try exact text
            for keyword in [description] + keywords:
                locator = self.page.locator(selector).filter(has_text=re.compile(f"^{re.escape(keyword)}$", re.IGNORECASE))
                if await self._is_valid_locator(locator):
                    logger.info(f"found menu item via exact match: {keyword}")
                    return locator.first
                
                # try contains
                locator = self.page.locator(selector).filter(has_text=re.compile(re.escape(keyword), re.IGNORECASE))
                if await self._is_valid_locator(locator):
                    logger.info(f"found menu item via contains: {keyword}")
                    return locator.first
        
        # strategy 2: find by scanning all menu items
        menu_items = await self.page.evaluate('''() => {
            const items = [];
            const itemSelectors = [
                '[role="menuitem"]',
                '[role="option"]',
                '[class*="MenuItem"]',
                '[class*="menu-item"]',
                'li[role="presentation"] a',
                'li[role="presentation"] button',
                'li[role="presentation"] div'
            ];
            
            itemSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach((el, idx) => {
                    const rect = el.getBoundingClientRect();
                    const isVisible = rect.width > 0 && rect.height > 0 && 
                                     window.getComputedStyle(el).visibility !== 'hidden' &&
                                     window.getComputedStyle(el).display !== 'none';
                    if (isVisible) {
                        items.push({
                            text: el.textContent.trim(),
                            ariaLabel: el.getAttribute('aria-label'),
                            classes: el.className,
                            id: el.id,
                            index: idx
                        });
                    }
                });
            });
            return items;
        }''')
        
        logger.debug(f"found {len(menu_items)} menu items: {[item['text'][:30] for item in menu_items[:5]]}")
        
        # score and find best match
        best_match = None
        best_score = 0
        
        for item in menu_items:
            score = self._calculate_menu_item_score(item, description, keywords)
            if score > best_score:
                best_score = score
                best_match = item
        
        if best_match and best_score > 0.5:
            logger.info(f"best menu match: {best_match['text'][:50]} (score: {best_score})")
            
            # try to build locator for this item
            if best_match.get('id'):
                locator = self.page.locator(f'#{best_match["id"]}')
                if await self._is_valid_locator(locator):
                    return locator.first
            
            # try by text
            text = best_match['text']
            for selector in menu_item_selectors:
                locator = self.page.locator(selector).filter(has_text=text)
                if await self._is_valid_locator(locator):
                    return locator.first
        
        logger.debug("no matching menu item found")
        return None
    
    def _looks_like_menu_item(self, description: str) -> bool:
        """check if description suggests a menu item."""
        menu_indicators = [
            'option', 'choice', 'item', 'in menu', 'in dropdown', 
            'from menu', 'from dropdown', 'menu item'
        ]
        desc_lower = description.lower()
        return any(indicator in desc_lower for indicator in menu_indicators)
    
    def _calculate_menu_item_score(self, item: Dict, description: str, keywords: List[str]) -> float:
        """calculate match score for menu item."""
        score = 0.0
        
        text = (item.get('text') or '').lower().strip()
        aria_label = (item.get('ariaLabel') or '').lower()
        
        desc_lower = description.lower()
        
        # exact match is best
        if text == desc_lower:
            return 1.0
        
        # check if description is contained in text
        if desc_lower in text:
            score += 0.7
        
        # check keyword matches
        keyword_matches = sum(1 for kw in keywords if kw in text or kw in aria_label)
        if keyword_matches > 0:
            score += 0.3 * (keyword_matches / len(keywords))
        
        # check if text starts with any keyword
        for kw in keywords:
            if text.startswith(kw):
                score += 0.2
                break
        
        # prefer shorter matches (more specific)
        if len(text) < 50 and keyword_matches > 0:
            score += 0.1
        
        return min(score, 1.0)
    
    async def find_elements(
        self,
        description: str,
        max_results: int = 5
    ) -> List[Locator]:
        """find multiple elements matching description."""
        logger.info(f"locating multiple: {description}")
        
        keywords = self._extract_keywords(description)
        inferred_type = self._infer_element_type(description)
        
        # get all interactive elements
        elements = await self._get_all_interactive_elements()
        
        # score each element
        scored = []
        for elem in elements:
            score = self._calculate_match_score(elem, description, keywords, inferred_type)
            if score > 0.3:
                scored.append((score, elem))
        
        # sort by score
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # build locators for top matches
        results = []
        for score, elem in scored[:max_results]:
            try:
                selector = self._build_selector_for_element(elem)
                locator = self.page.locator(selector).first
                if await self._is_valid_locator(locator):
                    results.append(locator)
            except:
                continue
        
        logger.info(f"found {len(results)} matching elements")
        return results
    
    async def get_page_context(self) -> Dict:
        """
        get structured information about current page state.
        """
        context = await self.page.evaluate('''() => {
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && 
                       window.getComputedStyle(el).visibility !== 'hidden' &&
                       window.getComputedStyle(el).display !== 'none';
            };
            
            // get all interactive elements with details
            const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
                .filter(isVisible)
                .map(b => ({
                    type: 'button',
                    text: b.textContent.trim().substring(0, 100),
                    ariaLabel: b.getAttribute('aria-label'),
                    classes: b.className,
                    id: b.id
                }))
                .slice(0, 30);
            
            const links = Array.from(document.querySelectorAll('a'))
                .filter(isVisible)
                .map(a => ({
                    type: 'link',
                    text: a.textContent.trim().substring(0, 100),
                    href: a.href,
                    ariaLabel: a.getAttribute('aria-label')
                }))
                .slice(0, 20);
            
            const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
                .filter(isVisible)
                .map(i => ({
                    type: 'input',
                    inputType: i.type || 'contenteditable',
                    placeholder: i.placeholder,
                    ariaLabel: i.getAttribute('aria-label'),
                    name: i.name,
                    id: i.id
                }))
                .slice(0, 20);
            
            const selects = Array.from(document.querySelectorAll('select, [role="combobox"], [role="listbox"]'))
                .filter(isVisible)
                .map(s => ({
                    type: 'select',
                    ariaLabel: s.getAttribute('aria-label'),
                    name: s.name,
                    id: s.id
                }))
                .slice(0, 10);
            
            // detect ui patterns
            const modals = Array.from(document.querySelectorAll('[role="dialog"]')).filter(isVisible);
            const menus = Array.from(document.querySelectorAll('[role="menu"], [role="listbox"]')).filter(isVisible);
            
            // capture menu items
            const menuItems = Array.from(document.querySelectorAll('[role="menuitem"], [role="option"]'))
                .filter(isVisible)
                .map(item => ({
                    type: 'menuitem',
                    text: item.textContent.trim().substring(0, 100),
                    ariaLabel: item.getAttribute('aria-label'),
                    role: item.getAttribute('role')
                }))
                .slice(0, 30);
            
            const headings = Array.from(document.querySelectorAll('h1, h2, h3'))
                .filter(isVisible)
                .map(h => h.textContent.trim().substring(0, 100))
                .slice(0, 5);
            
            return {
                url: window.location.href,
                title: document.title,
                buttons: buttons,
                links: links,
                inputs: inputs,
                selects: selects,
                menuItems: menuItems,
                headings: headings,
                ui_state: {
                    has_modal: modals.length > 0,
                    has_menu: menus.length > 0,
                    modal_count: modals.length,
                    menu_count: menus.length
                }
            };
        }''')
        
        return context
    
    def _extract_keywords(self, description: str) -> List[str]:
        """extract meaningful keywords from description."""
        stopwords = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during',
            'option', 'button', 'field', 'input', 'menu', 'item'
        }
        
        # extract words
        words = re.findall(r'\w+', description.lower())
        
        # remove stopwords
        keywords = [w for w in words if w not in stopwords and len(w) > 1]
        
        return keywords if keywords else [description.lower()]
    
    def _infer_element_type(self, description: str) -> str:
        """infer element type from description."""
        desc_lower = description.lower()
        
        type_patterns = {
            'button': ['button', 'btn', 'submit', 'click', 'press'],
            'link': ['link', 'href', 'anchor', 'navigate'],
            'input': ['input', 'field', 'textbox', 'enter', 'type', 'fill'],
            'select': ['select', 'dropdown', 'choose', 'picker'],
            'checkbox': ['checkbox', 'check', 'toggle'],
            'menu': ['menu', 'dropdown', 'list'],
            'menuitem': ['option', 'choice', 'item'],
            'modal': ['modal', 'dialog', 'popup']
        }
        
        for elem_type, patterns in type_patterns.items():
            if any(pattern in desc_lower for pattern in patterns):
                return elem_type
        
        return 'any'
    
    async def _find_by_exact_match(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """find by exact text match."""
        logger.debug("trying exact match")
        
        # try exact text
        locator = self.page.get_by_text(description, exact=True)
        if await self._is_valid_locator(locator):
            return locator.first
        
        # try case-insensitive exact match
        locator = self.page.get_by_text(re.compile(f"^{re.escape(description)}$", re.IGNORECASE))
        if await self._is_valid_locator(locator):
            return locator.first
        
        return None
    
    async def _find_by_accessibility(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """find using accessibility attributes."""
        logger.debug("trying accessibility")
        
        # try aria-label exact
        locator = self.page.locator(f'[aria-label="{description}" i]')
        if await self._is_valid_locator(locator):
            return locator.first
        
        # try aria-label with keywords
        for keyword in keywords:
            locator = self.page.locator(f'[aria-label*="{keyword}" i]')
            if await self._is_valid_locator(locator):
                return locator.first
        
        # try by role with accessible name
        roles = self._get_roles_for_type(element_type)
        for role in roles:
            try:
                locator = self.page.get_by_role(role, name=description, exact=False)
                if await self._is_valid_locator(locator):
                    return locator.first
                
                # try with keywords
                for keyword in keywords:
                    locator = self.page.get_by_role(
                        role,
                        name=re.compile(keyword, re.IGNORECASE)
                    )
                    if await self._is_valid_locator(locator):
                        return locator.first
            except:
                continue
        
        return None
    
    async def _find_by_semantic_text(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """find by visible text content."""
        logger.debug("trying semantic text")
        
        selectors = self._get_selectors_for_type(element_type)
        
        # try exact text in appropriate elements
        for selector in selectors:
            locator = self.page.locator(f'{selector}:has-text("{description}")')
            if await self._is_valid_locator(locator):
                return locator.first
        
        # try keyword matching
        for keyword in keywords:
            for selector in selectors:
                locator = self.page.locator(selector).filter(
                    has_text=re.compile(keyword, re.IGNORECASE)
                )
                if await self._is_valid_locator(locator):
                    return locator.first
        
        # try playwright's text locator
        locator = self.page.get_by_text(description, exact=False)
        if await self._is_valid_locator(locator):
            return locator.first
        
        return None
    
    async def _find_by_structure(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """find by structural attributes."""
        logger.debug("trying structural")
        
        attributes = ['id', 'name', 'placeholder', 'data-testid', 'class', 'title']
        
        for attr in attributes:
            for keyword in keywords:
                locator = self.page.locator(f'[{attr}*="{keyword}" i]')
                if await self._is_valid_locator(locator):
                    return locator.first
        
        return None
    
    async def _find_by_visual_context(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """find using visual/spatial context."""
        logger.debug("trying visual context")
        
        # look for positional hints
        position_hints = {
            'top': 'top',
            'bottom': 'bottom',
            'left': 'left',
            'right': 'right',
            'sidebar': 'left',
            'header': 'top',
            'footer': 'bottom'
        }
        
        position = None
        for hint, pos in position_hints.items():
            if hint in description.lower():
                position = pos
                break
        
        if position:
            elements = await self._get_all_interactive_elements()
            viewport_size = self.page.viewport_size
            
            for elem in elements:
                text_match = any(kw in elem.get('text', '').lower() for kw in keywords)
                aria_match = any(kw in (elem.get('ariaLabel') or '').lower() for kw in keywords)
                
                if text_match or aria_match:
                    pos = elem.get('position', {})
                    
                    is_positioned = False
                    if position == 'top' and pos.get('y', 999) < viewport_size['height'] * 0.2:
                        is_positioned = True
                    elif position == 'bottom' and pos.get('y', 0) > viewport_size['height'] * 0.8:
                        is_positioned = True
                    elif position == 'left' and pos.get('x', 999) < viewport_size['width'] * 0.2:
                        is_positioned = True
                    elif position == 'right' and pos.get('x', 0) > viewport_size['width'] * 0.8:
                        is_positioned = True
                    
                    if is_positioned:
                        selector = self._build_selector_for_element(elem)
                        locator = self.page.locator(selector).first
                        if await self._is_valid_locator(locator):
                            return locator
        
        return None
    
    async def _find_by_fuzzy_match(
        self,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> Optional[Locator]:
        """fuzzy matching as last resort."""
        logger.debug("trying fuzzy match")
        
        elements = await self._get_all_interactive_elements()
        
        if not elements:
            return None
        
        best_match = None
        best_score = 0
        
        for elem in elements:
            score = self._calculate_match_score(elem, description, keywords, element_type)
            if score > best_score:
                best_score = score
                best_match = elem
        
        if best_match and best_score > 0.4:
            selector = self._build_selector_for_element(best_match)
            locator = self.page.locator(selector).first
            if await self._is_valid_locator(locator):
                return locator
        
        return None
    
    def _calculate_match_score(
        self,
        element: Dict,
        description: str,
        keywords: List[str],
        element_type: str
    ) -> float:
        """calculate how well an element matches the description."""
        score = 0.0
        
        text = (element.get('text') or '').lower()
        aria_label = (element.get('ariaLabel') or '').lower()
        placeholder = (element.get('placeholder') or '').lower()
        tag = (element.get('tag') or '').lower()
        
        searchable = f"{text} {aria_label} {placeholder}"
        
        # keyword matching
        keyword_matches = sum(1 for kw in keywords if kw in searchable)
        if keyword_matches > 0:
            score += 0.5 * (keyword_matches / len(keywords))
        
        # exact phrase match
        if description.lower() in searchable:
            score += 0.3
        
        # element type match
        if self._element_matches_type(tag, element_type):
            score += 0.2
        
        # prefer shorter text (more specific)
        if len(text) < 50 and keyword_matches > 0:
            score += 0.1
        
        # boost if aria-label matches
        if any(kw in aria_label for kw in keywords):
            score += 0.1
        
        return min(score, 1.0)
    
    def _element_matches_type(self, tag: str, element_type: str) -> bool:
        """check if element tag matches expected type."""
        tag = tag.lower()
        
        type_map = {
            'button': lambda t: t == 'button' or 'button' in t,
            'link': lambda t: t == 'a',
            'input': lambda t: t in ['input', 'textarea'],
            'select': lambda t: t == 'select',
            'checkbox': lambda t: t == 'input',
            'menu': lambda t: t in ['nav', 'ul', 'ol', 'div'],
            'modal': lambda t: t in ['div', 'dialog'],
            'any': lambda t: True
        }
        
        check_func = type_map.get(element_type, lambda t: True)
        return check_func(tag)
    
    def _build_selector_for_element(self, element: Dict) -> str:
        """build css selector for an element."""
        if element.get('id'):
            return f'#{element["id"]}'
        
        if element.get('ariaLabel'):
            return f'[aria-label="{element["ariaLabel"]}"]'
        
        if element.get('testid'):
            return f'[data-testid="{element["testid"]}"]'
        
        tag = element.get('tag', 'div').lower()
        
        if element.get('classes'):
            classes = element['classes'].split()
            if classes:
                return f'{tag}.{classes[0]}'
        
        if element.get('text'):
            text = element['text'][:30]
            return f'{tag}:has-text("{text}")'
        
        return tag
    
    def _get_roles_for_type(self, element_type: str) -> List[str]:
        """get aria roles for element type."""
        role_map = {
            'button': ['button', 'menuitem'],
            'link': ['link', 'menuitem'],
            'input': ['textbox', 'searchbox'],
            'select': ['combobox', 'listbox'],
            'checkbox': ['checkbox'],
            'menu': ['menu', 'navigation'],
            'menuitem': ['menuitem', 'option'],
            'modal': ['dialog'],
            'any': ['button', 'link', 'textbox', 'menuitem', 'combobox', 'option']
        }
        return role_map.get(element_type, role_map['any'])
    
    def _get_selectors_for_type(self, element_type: str) -> List[str]:
        """get css selectors for element type."""
        selector_map = {
            'button': ['button', '[role="button"]', 'a.btn', 'input[type="submit"]'],
            'link': ['a', '[role="link"]'],
            'input': ['input', 'textarea', '[contenteditable="true"]', '[role="textbox"]'],
            'select': ['select', '[role="combobox"]', '[role="listbox"]'],
            'checkbox': ['input[type="checkbox"]', '[role="checkbox"]'],
            'menu': ['[role="menu"]', 'nav', 'ul', 'ol'],
            'menuitem': ['[role="menuitem"]', '[role="option"]', 'li', 'div[role="option"]'],
            'modal': ['[role="dialog"]', 'dialog'],
            'any': ['button', 'a', 'input', 'textarea', 'select', '[role="button"]', '[role="link"]', '[role="menuitem"]', '[role="option"]']
        }
        return selector_map.get(element_type, selector_map['any'])
    
    async def _is_valid_locator(self, locator: Locator) -> bool:
        """check if locator points to valid visible element."""
        try:
            count = await locator.count()
            if count == 0:
                return False
            
            is_visible = await locator.first.is_visible()
            return is_visible
        except:
            return False
    
    async def _get_all_interactive_elements(self) -> List[Dict]:
        """get all interactive elements on page."""
        elements = await self.page.evaluate('''() => {
            const interactive = document.querySelectorAll(
                'button, a, input, textarea, select, [role="button"], [role="link"], [role="menuitem"], [role="option"], [contenteditable="true"], [onclick]'
            );
            
            return Array.from(interactive).map(el => {
                const rect = el.getBoundingClientRect();
                const isVisible = rect.width > 0 && rect.height > 0 && 
                                 window.getComputedStyle(el).visibility !== 'hidden' &&
                                 window.getComputedStyle(el).display !== 'none';
                return {
                    tag: el.tagName,
                    type: el.type || null,
                    text: el.textContent.trim().substring(0, 100),
                    ariaLabel: el.getAttribute('aria-label'),
                    id: el.id || null,
                    classes: el.className,
                    placeholder: el.placeholder || null,
                    testid: el.getAttribute('data-testid'),
                    visible: isVisible,
                    position: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                };
            }).filter(el => el.visible);
        }''')
        
        return elements