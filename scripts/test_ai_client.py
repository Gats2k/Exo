from pathlib import Path
import os
import sys

# Load .env from project root if present
env_file = Path(__file__).parent.parent / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            v = v.strip().strip('"').strip("'")
            os.environ[k.strip()] = v

try:
    # Ensure project root is on sys.path so imports work when this script is run from scripts/
    project_root = Path(__file__).parent.parent.resolve()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import ai_config
    c = ai_config.get_ai_client()
    print('CLIENT_TYPE:', type(c))
    print('CLIENT_EXISTS:', bool(c))
except Exception as e:
    print('ERROR:', e)
    import traceback
    traceback.print_exc()
    sys.exit(1)

sys.exit(0)
