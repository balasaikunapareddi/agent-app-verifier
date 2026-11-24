import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_app_verifier.spec import AppSpec  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "specs" / "todo.yaml"


def load_spec() -> AppSpec:
    return AppSpec.from_file(SPEC_PATH)
