import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent / "plugins" / "rederive" / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
