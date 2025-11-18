import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from core.browser_controller import BrowserController
from core.state_detector import StateDetector
from core.element_locator import ElementLocator
from capturer.screenshot_manager import ScreenshotManager
from parsers.task_parser import TaskParser

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WorkflowCapturer:
    """
    workflow capturer with proper completion detection that doesn't stop prematurely.
    """
    
    def __init__(self, output_dir: str = "output", api_key: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.browser = BrowserController(headless=False)
        self.task_parser = TaskParser(api_key=api_key)
        self.screenshot_manager = None
        self.state_detector = None
        self.element_locator = None
    
    async def initialize(self):
        """initialize browser and components."""
        logger.info("initializing workflow capturer...")
        await self.browser.initialize()
        self.state_detector = StateDetector(self.browser.page)
        self.element_locator = ElementLocator(self.browser.page)
        self.screenshot_manager = ScreenshotManager(
            output_dir=str(self.output_dir / "screenshots")
        )
        logger.info("initialization complete")
    
    async def capture_workflow(
        self,
        query: str,
        app_url: str,
        task_id: Optional[str] = None
    ) -> Dict:
        """capture workflow for natural language query."""
        if task_id is None:
            task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info(f"starting workflow capture: {task_id}")
        logger.info(f"query: {query}")
        
        await self.browser.navigate_to(app_url)
        await asyncio.sleep(2)
        
        page_context = await self.element_locator.get_page_context()
        
        task_plan = await self.task_parser.parse_query(
            query=query,
            app_name="unknown",
            current_url=app_url,
            page_context=page_context
        )
        
        logger.info(f"action: {task_plan.get('action')} {task_plan.get('entity')}")
        logger.info(f"planned steps: {len(task_plan.get('steps', []))}")
        
        workflow_data = {
            "task_id": task_id,
            "query": query,
            "app": task_plan.get("app", "unknown"),
            "action": task_plan.get("action", "unknown"),
            "entity": task_plan.get("entity", "unknown"),
            "captured_at": datetime.now().isoformat(),
            "start_url": app_url,
            "steps": []
        }
        
        logger.info("capturing initial state...")
        initial_screenshots = await self.screenshot_manager.capture_state(
            self.browser.page,
            "initial_state",
            task_id,
            annotation="starting state"
        )
        
        workflow_data["steps"].append({
            "step_number": 0,
            "name": "initial_state",
            "description": "initial page view",
            "screenshots": initial_screenshots,
            "timestamp": datetime.now().isoformat(),
            "url": self.browser.page.url
        })
        
        # execute ALL planned steps unless error occurs
        step_number = 1
        consecutive_errors = 0
        max_consecutive_errors = 2
        
        for step_index, planned_step in enumerate(task_plan.get("steps", [])):
            logger.info(f"\nstep {step_number}: {planned_step.get('description')}")
            
            try:
                step_data = await self._execute_step_intelligently(
                    planned_step,
                    step_number,
                    task_id,
                    workflow_data["steps"]
                )
                
                if step_data:
                    workflow_data["steps"].append(step_data)
                    
                    if step_data.get("error"):
                        consecutive_errors += 1
                        logger.warning(f"consecutive errors: {consecutive_errors}/{max_consecutive_errors}")
                        
                        if consecutive_errors >= max_consecutive_errors:
                            logger.warning("too many consecutive errors - stopping")
                            break
                    else:
                        consecutive_errors = 0
                    
                    step_number += 1
                
            except Exception as e:
                logger.error(f"step {step_number} failed: {e}")
                
                error_screenshots = await self.screenshot_manager.capture_error_state(
                    self.browser.page,
                    f"step_{step_number}",
                    task_id,
                    str(e)
                )
                
                workflow_data["steps"].append({
                    "step_number": step_number,
                    "description": f"error: {str(e)}",
                    "error": str(e),
                    "screenshots": error_screenshots,
                    "timestamp": datetime.now().isoformat(),
                    "action_attempted": planned_step
                })
                
                consecutive_errors += 1
                step_number += 1
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning("too many consecutive errors - stopping")
                    break
                
                logger.info("attempting to continue after error...")
                await asyncio.sleep(1)
        
        logger.info("saving workflow data...")
        workflow_file = self.output_dir / task_id / "workflow.json"
        workflow_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(workflow_file, 'w') as f:
            json.dump(workflow_data, f, indent=2)
        
        logger.info(f"workflow saved to {workflow_file}")
        logger.info(f"total steps captured: {len(workflow_data['steps'])}")
        
        return workflow_data
    
    async def _execute_step_intelligently(
        self,
        planned_step: Dict,
        step_number: int,
        task_id: str,
        previous_steps: List[Dict]
    ) -> Optional[Dict]:
        """execute a step with intelligent adaptation."""
        action_type = planned_step.get("action_type", "").lower()
        target = planned_step.get("target")
        value = planned_step.get("value")
        description = planned_step.get("description", "")
        
        if action_type == "wait":
            wait_time = float(value) if value else 1.0
            await self.browser.wait(wait_time)
            return {
                "step_number": step_number,
                "action_type": "wait",
                "description": description,
                "duration": wait_time,
                "timestamp": datetime.now().isoformat()
            }
        
        if action_type == "navigate":
            url = value or target
            await self.browser.navigate_to(url)
            
            screenshots = await self.screenshot_manager.capture_state(
                self.browser.page,
                f"step_{step_number}",
                task_id,
                annotation=description
            )
            
            return {
                "step_number": step_number,
                "action_type": "navigate",
                "url": url,
                "description": description,
                "screenshots": screenshots,
                "timestamp": datetime.now().isoformat()
            }
        
        if action_type in ["click", "fill", "hover", "select_menu"]:
            page_state = await self.element_locator.get_page_context()
            
            in_menu = page_state.get('ui_state', {}).get('has_menu', False)
            
            is_menu_action = (
                action_type == "select_menu" or
                "menu" in description.lower() or
                "option" in description.lower() or
                "from" in description.lower() or
                in_menu
            )
            
            logger.info(f"locating element: {target} (menu_context={is_menu_action})")
            element = await self.element_locator.find_element(
                description=target,
                context=page_state,
                in_menu=is_menu_action
            )
            
            if not element:
                logger.warning(f"element not found: {target}")
                
                if is_menu_action:
                    logger.info("waiting for menu to fully render...")
                    await asyncio.sleep(0.5)
                    element = await self.element_locator.find_element(
                        description=target,
                        context=page_state,
                        in_menu=True
                    )
                
                if not element:
                    if action_type == "fill":
                        logger.warning(f"skipping fill - element not fillable: {target}")
                        return {
                            "step_number": step_number,
                            "action_type": "fill",
                            "target": target,
                            "description": description,
                            "skipped": True,
                            "reason": "element not fillable",
                            "timestamp": datetime.now().isoformat()
                        }
                    
                    raise Exception(f"element not found: {target}")
            
            logger.info("capturing before state...")
            before_screenshots = await self.screenshot_manager.capture_state(
                self.browser.page,
                f"step_{step_number}_Abefore",
                task_id,
                annotation=f"before: {description}",
                highlight_element=element
            )
            
            success = False
            try:
                if action_type in ["click", "select_menu"]:
                    success = await self.browser.click(element, description=target)
                    
                    if success and not is_menu_action:
                        await asyncio.sleep(0.5)
                        new_state = await self.element_locator.get_page_context()
                        if new_state.get('ui_state', {}).get('has_menu', False):
                            logger.info("menu appeared after click")
                            menu_screenshots = await self.screenshot_manager.capture_state(
                                self.browser.page,
                                f"step_{step_number}_menu",
                                task_id,
                                annotation="menu opened"
                            )
                            before_screenshots.update(menu_screenshots)
                    
                elif action_type == "fill":
                    if not value:
                        value = "sample text"
                    
                    try:
                        success = await self.browser.fill(element, value, description=target)
                    except Exception as fill_error:
                        logger.warning(f"fill failed (custom element): {fill_error}")
                        return {
                            "step_number": step_number,
                            "action_type": "fill",
                            "target": target,
                            "description": description,
                            "skipped": True,
                            "reason": "custom ui element",
                            "screenshots_before": before_screenshots,
                            "timestamp": datetime.now().isoformat()
                        }
                        
                elif action_type == "hover":
                    success = await self.browser.hover(element, description=target)
                
                if not success:
                    raise Exception(f"action failed: {action_type} on {target}")
                
            except Exception as action_error:
                logger.error(f"action execution failed: {action_error}")
                return {
                    "step_number": step_number,
                    "action_type": action_type,
                    "target": target,
                    "description": description,
                    "error": str(action_error),
                    "screenshots_before": before_screenshots,
                    "timestamp": datetime.now().isoformat()
                }
            
            logger.info("waiting for ui response...")
            state_changed = await self.state_detector.wait_for_state_change(timeout=3000)
            
            if not state_changed:
                logger.debug("no state change detected")
            
            await self.browser.wait_for_stability(timeout=3000)
            
            logger.info("capturing after state...")
            after_screenshots = await self.screenshot_manager.capture_state(
                self.browser.page,
                f"step_{step_number}_Bafter",
                task_id,
                annotation=f"after: {description}"
            )
            
            return {
                "step_number": step_number,
                "action_type": action_type,
                "target": target,
                "value": value,
                "description": description,
                "screenshots_before": before_screenshots,
                "screenshots_after": after_screenshots,
                "state_changed": state_changed,
                "url": self.browser.page.url,
                "timestamp": datetime.now().isoformat()
            }
        
        logger.warning(f"unknown action type: {action_type}")
        return None
    
    async def close(self):
        """close browser and cleanup."""
        logger.info("closing workflow capturer...")
        await self.browser.close()
        logger.info("closed successfully")