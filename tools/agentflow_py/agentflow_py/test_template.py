from pathlib import Path
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "agentflow/dashboard/templates"
print(f"Templates dir: {TEMPLATES_DIR}")
print(f"Exists: {TEMPLATES_DIR.exists()}")
print(f"dashboard.html exists: {(TEMPLATES_DIR / 'dashboard.html').exists()}")

try:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    print(f"Jinja2Templates OK: {templates}")
except Exception as e:
    print(f"Jinja2Templates FAILED: {e}")
