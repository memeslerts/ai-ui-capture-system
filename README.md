## Quick Start

### Prerequisites

```bash
Python 3.8+
pip
```

### Installation

```bash
# Clone repository
git clone https://github.com/memeslerts/ai-agent-workflow-capture.git
cd ai-ui-capture-system

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Set up environment variables
cp .env.example .env
# Add your AZURE_OPENAI_API_KEY to .env
```

### Run Demo

```bash
# Run the interactive demo
python test_workflow.py

# You'll be prompted to select workflows:
# 1. Notion workflows (3 tasks)
# 2. Linear workflows (2 tasks)
# 3. Asana workflows (2 tasks)
# 4. All workflows (7 tasks)
# 5. Custom selection

# The system will:
# - Open the browser
# - Ask you to log in once (session saved for future runs)
# - Automatically capture each workflow
# - Save all results to demo_dataset/
```

Example workflow captures:
- **Asana**: Dropdown menu selection (non-URL state)
- **Linear**: Modal dialog opening (non-URL state)
- **Notion**: Slash command inline menu (non-URL state)
