import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Isolated, throw-away site-knowledge folder and a known admin token for every test run.
os.environ["LOCAL_DIR"] = tempfile.mkdtemp(prefix="fa-local-")
os.environ["ADMIN_TOKEN"] = "test-token"
os.environ["LLM_PROVIDER"] = "none"
