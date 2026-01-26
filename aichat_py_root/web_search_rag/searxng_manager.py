import subprocess
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
# Assuming scripts are in aichat/scripts/searxng relative to repo root
# This file is in aichat/aichat_py_root/web_search_rag/
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../.."))
MANAGE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "searxng", "manage_searxng.sh")

def manage_searxng(action):
    if not os.path.exists(MANAGE_SCRIPT):
        print(f"Error: Management script not found at {MANAGE_SCRIPT}")
        return False
        
    try:
        # Ensure executable
        subprocess.run(["chmod", "+x", MANAGE_SCRIPT], check=True)
        result = subprocess.run([MANAGE_SCRIPT, action], check=True, text=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Error executing management script: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python searxng_manager.py <start|stop|status|restart>")
        sys.exit(1)
    
    action = sys.argv[1]
    if manage_searxng(action):
        sys.exit(0)
    else:
        sys.exit(1)
