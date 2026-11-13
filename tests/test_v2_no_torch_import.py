"""The v2 runtime must stay torch-free so the CPU image can drop torch later."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_v2_modules_do_not_import_torch():
    code = (
        "import sys\n"
        "import app.services.v2.pronunciation_v2_service, app.services.v2.scorer\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('torch', 'torchaudio', 'transformers'))\n"
        "assert not bad, bad\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
