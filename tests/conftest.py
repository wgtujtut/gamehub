import os
import sys
import tempfile
from pathlib import Path

# тесты никогда не трогают настоящую папку данных (%APPDATA%\GameHub)
os.environ["GAMEHUB_DATA"] = tempfile.mkdtemp(prefix="gamehub-test-")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
