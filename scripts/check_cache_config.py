import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.cache_config import configure_project_cache


if __name__ == "__main__":
    print("[check_cache_config] configure project cache")
    configure_project_cache(PROJECT_ROOT)

