import os, sys
sys.path.append(os.path.dirname(__file__))
from openai import AzureOpenAI
import json
from typing import Dict
import logging
from dotenv import load_dotenv
import asyncio
from typing import Optional, Dict, List

load_dotenv()

logger = logging.getLogger(__name__)

class TaskParser:
    """
    parse natural language queries with application-specific optimizations.
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        api_version: str = "2024-08-01-preview",
        deployment_name: Optional[str] = None
    ):
        """initialize azure openai client."""
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        self.azure_endpoint = azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        self.deployment_name = deployment_name or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        
        if not self.api_key:
            raise ValueError("AZURE_OPENAI_API_KEY not found in environment!")
        if not self.azure_endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT not found in environment!")
        if not self.deployment_name:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT not found in environment!")
        
        self.client = AzureOpenAI(
            api_key=self.api_key,
            api_version=api_version,
            azure_endpoint=self.azure_endpoint
        )
        
        logger.info(f"task parser initialized with azure openai deployment: {self.deployment_name}")
    
    async def parse_query(
        self, 
        query: str, 
        app_name: str = "any",
        current_url: Optional[str] = None,
        page_context: Optional[Dict] = None
    ) -> Dict:
        """
        parse natural language query into clean, direct workflow steps.
        """
        logger.info(f"parsing query: {query} for app: {app_name}")
        
        # detect application from url if not specified
        if current_url and app_name == "any":
            if "notion.so" in current_url:
                app_name = "notion"
            elif "asana.com" in current_url:
                app_name = "asana"
            elif "linear.app" in current_url:
                app_name = "linear"
        
        # build context-aware prompt
        prompt = self._build_parsing_prompt(query, app_name, current_url, page_context)
        
        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": "you are a workflow automation expert that creates clean, direct workflows without trial-and-error. always respond with valid json only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,  # lower for more consistent, direct workflows
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            
            parsed_data = self._extract_json(response.choices[0].message.content)
            
            # validate steps
            if not parsed_data.get('steps') or len(parsed_data.get('steps', [])) == 0:
                logger.warning("no steps generated - using fallback")
                return self._create_fallback_plan(query, app_name)
            
            logger.info(f"parsed: {parsed_data.get('action')} {parsed_data.get('entity')}")
            logger.info(f"steps: {len(parsed_data.get('steps', []))}")
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"failed to parse query: {e}")
            return self._create_fallback_plan(query, app_name)
    
    def _build_parsing_prompt(
        self,
        query: str,
        app_name: str,
        current_url: Optional[str],
        page_context: Optional[Dict]
    ) -> str:
        """build context-aware prompt for clean workflow generation."""
        
        context_section = ""
        if current_url:
            context_section += f"\nCURRENT URL: {current_url}"
        
        if page_context:
            # simplified context
            formatted_context = {
                "buttons": page_context.get('buttons', [])[:10],
                "inputs": page_context.get('inputs', [])[:5],
                "menuItems": page_context.get('menuItems', [])[:10],
            }
            context_section += f"\n\nPAGE ELEMENTS:\n{json.dumps(formatted_context, indent=2)}"
        
        # application-specific knowledge
        app_specific = self._get_app_specific_patterns(app_name)
        
        prompt = f"""you are a workflow automation expert. create a CLEAN, DIRECT workflow without trial-and-error.

QUERY: {query}
APPLICATION: {app_name}
{context_section}

{app_specific}

CRITICAL RULES:

1. CLEAN WORKFLOWS ONLY:
   - generate the DIRECT path to complete the task
   - NO trial-and-error steps
   - NO fallback options
   - each step should succeed on first try

2. STOP AT CONFIGURATION POINTS:
   For tasks requiring user-specific input:
   - filter/search: stop after opening filter panel
   - settings: stop after opening settings
   - forms with unknown values: stop after opening form
   
3. USE EXACT ELEMENT NAMES:
   - use the exact text from page context when available
   - for menus: use the exact menu item text (case-sensitive)
   - avoid generic descriptions

4. SLASH COMMANDS (NOTION):
   - typing "/" opens a block menu
   - menu contains: Database, Table, List, Heading, etc.
   - select items by their exact name from the menu

5. ACTION TYPES:
   - click: for buttons, links (not menu items)
   - select_menu: for choosing from visible menus/dropdowns
   - fill: for text input (only on actual input fields)
   - wait: after triggering UI changes (0.5 seconds)
   - hover: rarely needed

WORKFLOW STRUCTURE:
{{
  "app": "application name",
  "action": "verb (create, filter, edit, etc.)",
  "entity": "noun (task, database, page, etc.)",
  "steps": [
    {{
      "action_type": "click|select_menu|fill|wait",
      "target": "specific element from page OR typical location",
      "value": "value for fill/wait",
      "description": "clear, concise step description"
    }}
  ]
}}

EXAMPLES OF CLEAN WORKFLOWS:

NOTION - ADD DATABASE:
{{
  "app": "notion",
  "action": "create",
  "entity": "database",
  "steps": [
    {{"action_type": "click", "target": "contenteditable area", "value": null, "description": "focus page editor"}},
    {{"action_type": "fill", "target": "contenteditable area", "value": "/database", "description": "type slash command"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for menu"}},
    {{"action_type": "select_menu", "target": "Database", "value": null, "description": "select Database from menu"}}
  ]
}}

NOTION - FILTER DATABASE:
{{
  "app": "notion",
  "action": "filter",
  "entity": "database",
  "steps": [
    {{"action_type": "click", "target": "Filter button", "value": null, "description": "open filter panel"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for panel"}}
  ]
}}
Note: stops here - user configures filter criteria

ASANA - CREATE TASK:
{{
  "app": "asana",
  "action": "create",
  "entity": "task",
  "steps": [
    {{"action_type": "click", "target": "Create", "value": null, "description": "open create menu"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for menu"}},
    {{"action_type": "select_menu", "target": "Task", "value": null, "description": "select Task from menu"}}
  ]
}}

LINEAR - CREATE ISSUE:
{{
  "app": "linear",
  "action": "create",
  "entity": "issue",
  "steps": [
    {{"action_type": "click", "target": "New issue", "value": null, "description": "open new issue modal"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for modal"}}
  ]
}}
Note: Linear opens modal directly, no menu selection needed

LINEAR - FILTER ISSUES:
{{
  "app": "linear",
  "action": "filter",
  "entity": "issues",
  "steps": [
    {{"action_type": "click", "target": "Issues", "value": null, "description": "navigate to issues view"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for page load"}},
    {{"action_type": "click", "target": "Filter", "value": null, "description": "open filter panel"}},
    {{"action_type": "wait", "target": null, "value": "0.5", "description": "wait for panel"}}
  ]
}}
Note: Must be on issues page, click Filter button (not search)

CRITICAL REMINDERS:
- use simple, exact target names (not verbose descriptions)
- for notion slash commands: select by exact menu text (Database, NOT "Table - Inline")
- stop workflows at user configuration points
- each step should work on first attempt
- NO steps for "try alternative" or "if that fails"

now generate a CLEAN workflow:
"""
        
        return prompt
    
    def _get_app_specific_patterns(self, app_name: str) -> str:
        """get application-specific workflow patterns."""
        
        patterns = {
            "notion": """
NOTION-SPECIFIC PATTERNS:

SLASH COMMANDS:
- typing "/" in editor opens block menu
- block menu contains: Database, Table, Heading, Bullet list, etc.
- ALWAYS use exact menu item names (case-sensitive)
- "Database" creates an inline database (NOT "Table - Inline")

COMMON WORKFLOWS:
- create page: click "Add a page" → done
- add database: type "/database" → select "Database" → done
- filter database: click "Filter" → stop (user configures)
- add block: type "/[blocktype]" → select from menu → done

ELEMENT LOCATIONS:
- editor: contenteditable with aria-label "Start typing to edit text"
- sidebar: left side, contains "Add a page" button
- database tools: top of database view (Filter, Sort, etc.)
""",
            
            "asana": """
ASANA-SPECIFIC PATTERNS:

CREATION MENU:
- "Create" button opens dropdown menu
- menu contains: Task, Project, Portfolio, etc.
- select by exact text

COMMON WORKFLOWS:
- create task: click "Create" → select "Task" → done
- create project: click "Create" → select "Project" → done
- assign task: click assignee field → select person → done
""",
            
            "linear": """
LINEAR-SPECIFIC PATTERNS:

CREATION:
- "C" keyboard shortcut opens create dialog directly (fastest)
- OR click "New issue" button in sidebar/toolbar
- Creates issue in modal, no menu selection needed

FILTERING:
- MUST be on issues page first (navigate if needed)
- Filter button is in issues view toolbar (top right area)
- Click "Filter" button to open filter panel
- NOT the search bar - that's different

NAVIGATION:
- Issues page: https://linear.app/team/issues
- Click "Issues" in sidebar to navigate to issues view

COMMON WORKFLOWS:
- create issue: 
  1. press "C" key OR click "New issue" button
  2. modal opens (done - user fills form)
  
- filter issues:
  1. navigate to Issues view (if not there)
  2. click "Filter" button in toolbar
  3. configure filters (done - user sets criteria)

KEY ELEMENTS:
- "New issue" button (NOT "New" - be specific)
- "Issues" navigation link
- "Filter" button (in issues toolbar, NOT search)
"""
        }
        
        return patterns.get(app_name, "")
    
    def _extract_json(self, text: str) -> Dict:
        """extract json from llm response."""
        try:
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            text = text.strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"failed to parse json: {e}")
            logger.error(f"text: {text[:500]}")
            raise
    
    def _create_fallback_plan(self, query: str, app_name: str) -> Dict:
        """create fallback plan based on query patterns."""
        logger.warning("using fallback plan")
        
        query_lower = query.lower()
        
        # detect action and entity
        action = "interact"
        entity = "element"
        
        if "create" in query_lower or "add" in query_lower or "new" in query_lower:
            action = "create"
            if "task" in query_lower:
                entity = "task"
            elif "project" in query_lower:
                entity = "project"
            elif "page" in query_lower:
                entity = "page"
            elif "database" in query_lower or "table" in query_lower:
                entity = "database"
        elif "filter" in query_lower:
            action = "filter"
            entity = "database"
        elif "search" in query_lower:
            action = "search"
        
        # generate basic steps
        steps = [
            {
                "action_type": "wait",
                "target": None,
                "value": "1.0",
                "description": f"preparing to {action} {entity}"
            }
        ]
        
        return {
            "app": app_name,
            "action": action,
            "entity": entity,
            "steps": steps
        }
    
    async def refine_step(
        self,
        step: Dict,
        page_state: Dict,
        previous_steps: List[Dict]
    ) -> Dict:
        """refine step based on actual page state."""
        logger.info(f"refining step: {step.get('description')}")
        
        prompt = f"""refine this workflow step based on actual page state.

CURRENT PAGE STATE:
{json.dumps(page_state, indent=2)}

STEP TO REFINE:
{json.dumps(step, indent=2)}

INSTRUCTIONS:
1. find the closest matching element from page state
2. use exact element text/aria-label from page state
3. if element not found, suggest closest alternative
4. keep step simple and direct

return json:
{{
  "action_type": "click|fill|select_menu|wait",
  "target": "exact element from page state",
  "value": "value if needed",
  "description": "clear description",
  "confidence": "high|medium|low"
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": "you are a workflow expert. refine steps based on actual page elements. respond with valid json only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            refined = self._extract_json(response.choices[0].message.content)
            logger.info(f"refined: {refined.get('description')}")
            return refined
        except Exception as e:
            logger.error(f"refinement failed: {e}")
            return step