import asyncio
import sys
import os
sys.path.append(os.path.dirname(__file__))
from dotenv import load_dotenv
from workflow_capturer import WorkflowCapturer
from typing import List, Dict
import json
from datetime import datetime
from pathlib import Path

load_dotenv()

class WorkflowDemo:
    """
    demo runner for workflow capture system.
    """
    
    def __init__(self, output_dir: str = "demo_dataset"):
        self.output_dir = output_dir
        self.capturer = None
        self.results = []
    
    async def initialize(self):
        """initialize workflow capturer."""
        self.capturer = WorkflowCapturer(output_dir=self.output_dir)
        await self.capturer.initialize()
        print("workflow capturer initialized")
    
    async def run_workflow(self, workflow: Dict) -> Dict:
        """run single workflow and capture it."""
        print(f"\n{'='*60}")
        print(f"starting: {workflow['task_id']}")
        print(f"query: {workflow['query']}")
        print(f"{'='*60}\n")
        
        try:
            result = await self.capturer.capture_workflow(
                query=workflow['query'],
                app_url=workflow['url'],
                task_id=workflow['task_id']
            )
            
            print(f"\ncompleted: {workflow['task_id']}")
            print(f"  steps captured: {len(result['steps'])}")
            
            return {
                "status": "success",
                "task_id": workflow['task_id'],
                "steps_captured": len(result['steps']),
                "workflow": result
            }
            
        except Exception as e:
            print(f"\nfailed: {workflow['task_id']}")
            print(f"  error: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return {
                "status": "failed",
                "task_id": workflow['task_id'],
                "error": str(e)
            }
    
    async def run_all_workflows(self, workflows: List[Dict], wait_between: int = 3):
        """run all workflows sequentially."""
        print(f"\nrunning {len(workflows)} workflows...")
        print(f"output directory: {self.output_dir}\n")
        
        for i, workflow in enumerate(workflows, 1):
            print(f"\n[{i}/{len(workflows)}] ", end="")
            result = await self.run_workflow(workflow)
            self.results.append(result)
            
            if i < len(workflows):
                print(f"\nwaiting {wait_between} seconds before next workflow...")
                await asyncio.sleep(wait_between)
        
        self._print_summary()
        self._save_summary()
    
    def _print_summary(self):
        """print summary of all runs."""
        print("\n" + "="*60)
        print("workflow capture summary")
        print("="*60)
        
        successful = [r for r in self.results if r['status'] == 'success']
        failed = [r for r in self.results if r['status'] == 'failed']
        
        print(f"\ntotal workflows: {len(self.results)}")
        print(f"successful: {len(successful)}")
        print(f"failed: {len(failed)}")
        
        if successful:
            print("\nsuccessful workflows:")
            for result in successful:
                print(f"  - {result['task_id']}: {result['steps_captured']} steps")
        
        if failed:
            print("\nfailed workflows:")
            for result in failed:
                print(f"  - {result['task_id']}: {result['error'][:100]}")
        
        print(f"\ndataset saved to: {self.output_dir}/")
        print("="*60 + "\n")
    
    def _save_summary(self):
        """save summary to json."""
        summary = {
            "run_timestamp": datetime.now().isoformat(),
            "total_workflows": len(self.results),
            "successful": len([r for r in self.results if r['status'] == 'success']),
            "failed": len([r for r in self.results if r['status'] == 'failed']),
            "results": self.results
        }
        
        summary_path = Path(self.output_dir) / "summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"summary saved to: {summary_path}")
    
    async def close(self):
        """cleanup resources."""
        if self.capturer:
            await self.capturer.close()


# example workflow definitions
NOTION_WORKFLOWS = [
    {
        "app": "notion",
        "task_id": "notion_create_page",
        "query": "how do i create a new page in notion?",
        "url": "https://www.notion.so"
    },
    {
        "app": "notion",
        "task_id": "notion_add_database",
        "query": "how do i add a database to a notion page?",
        "url": "https://www.notion.so"
    },
    {
        "app": "notion",
        "task_id": "notion_filter_database",
        "query": "how do i filter a database on notion?",
        "url":"https://www.notion.so/Monthly-Budget-6cdbcee8fd5b4e29b33a292f1482abbd"
    }
]

LINEAR_WORKFLOWS = [
    {
        "app": "linear",
        "task_id": "linear_create_issue",
        "query": "how do i create a new issue in linear?",
        "url": "https://linear.app"
    },
    {
        "app": "linear",
        "task_id": "linear_filter_issues",
        "query": "how do i filter issues in linear?",
        "url": "https://linear.app"
    },
]

ASANA_WORKFLOWS = [
    {
        "app": "asana",
        "task_id": "asana_create_task",
        "query": "how do i create a new task in asana?",
        "url": "https://app.asana.com"
    },
    {
        "app": "asana",
        "task_id": "asana_create_project",
        "query": "how do i create a new project in asana?",
        "url": "https://app.asana.com"
    },
]


async def main():
    """main execution."""
    print("\n" + "="*60)
    print("multi-agent workflow capture demo")
    print("="*60)
    
    print("\nselect workflow set:")
    print("1. notion workflows (2 tasks)")
    print("2. linear workflows (2 tasks)")
    print("3. asana workflows (2 tasks)")
    print("4. all workflows (6 tasks)")
    print("5. custom selection")
    
    choice = input("\nenter choice (1-5): ").strip()
    
    workflows = []
    if choice == "1":
        workflows = NOTION_WORKFLOWS
    elif choice == "2":
        workflows = LINEAR_WORKFLOWS
    elif choice == "3":
        workflows = ASANA_WORKFLOWS
    elif choice == "4":
        workflows = NOTION_WORKFLOWS + LINEAR_WORKFLOWS + ASANA_WORKFLOWS
    elif choice == "5":
        print("\navailable workflows:")
        all_workflows = NOTION_WORKFLOWS + LINEAR_WORKFLOWS + ASANA_WORKFLOWS
        for i, w in enumerate(all_workflows, 1):
            print(f"  {i:2d}. [{w['app']:6s}] {w['task_id']}")
        
        indices = input("\nenter workflow numbers (comma-separated, e.g., 1,3,6): ").strip()
        
        for idx in indices.split(','):
            try:
                idx = int(idx.strip()) - 1
                if 0 <= idx < len(all_workflows):
                    workflows.append(all_workflows[idx])
            except ValueError:
                print(f"invalid index: {idx}")
        
        print(f"\nselected: {len(workflows)} workflows")
    else:
        print("invalid choice. exiting.")
        return
    
    if not workflows:
        print("no workflows selected. exiting.")
        return
    
    # show what will be captured
    print("\nworkflows to capture:")
    for i, w in enumerate(workflows, 1):
        print(f"  {i}. {w['task_id']}: {w['query']}")
    
    # confirm
    confirm = input("\ncontinue? (y/n): ").strip().lower()
    if confirm != 'y':
        print("cancelled.")
        return
    
    # get api key
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not api_key:
        print("\nerror: AZURE_OPENAI_API_KEY environment variable not set")
        print("please set it with: export AZURE_OPENAI_API_KEY=your_key_here")
        return
    
    # initialize runner
    runner = WorkflowDemo(output_dir="demo_dataset")
    
    try:
        await runner.initialize()
        
        # navigate to first app
        app_name = workflows[0]['app']
        start_url = workflows[0]['url']
        
        print(f"\nopening {app_name}...")
        await runner.capturer.browser.navigate_to(start_url)
        await asyncio.sleep(3)
        
        # prompt for login
        print("\nmanual login required")
        print(f"\nthe browser is now showing {app_name}.")
        print("\nplease:")
        print("1. log in to your account (if not already logged in)")
        print("2. navigate to your workspace/dashboard")
        print("3. make sure you're on the main page")
        print("4. come back here and press enter to start capturing")
        print("\ntip: your session will be saved for next time!")
        
        input("\npress enter when ready to start: ")
        
        print("\nstarting workflow capture...\n")
        
        # run workflows
        await runner.run_all_workflows(workflows, wait_between=3)
        
        print("\nall workflows completed!")
        print(f"\ncheck your dataset at: demo_dataset/")
        
    except KeyboardInterrupt:
        print("\n\ninterrupted by user")
    except Exception as e:
        print(f"\n\nerror: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\ncleaning up...")
        await runner.close()
        print("done!\n")


if __name__ == "__main__":
    asyncio.run(main())