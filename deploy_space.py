r"""Stage and upload the app to a Hugging Face Space.

The Space needs the three application modules plus its own README (which carries the
required YAML frontmatter) and its own requirements.txt. Those two live in `space/`
rather than at the repo root so they cannot collide with the GitHub README.

Nothing is copied into the working tree: the staging directory is temporary, so the
Space can never drift from the modules it was built out of.

    .venv\Scripts\python.exe deploy_space.py <namespace>/<space-name>
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
MODULES = ("app.py", "dcf.py", "viz.py")
SPACE_FILES = ("README.md", "requirements.txt")


def stage(into: Path) -> None:
    for name in MODULES:
        shutil.copy2(ROOT / name, into / name)
    for name in SPACE_FILES:
        shutil.copy2(ROOT / "space" / name, into / name)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    repo_id = sys.argv[1]

    with tempfile.TemporaryDirectory(prefix="hf-space-") as tmp:
        staging = Path(tmp)
        stage(staging)
        print(f"staged {len(MODULES) + len(SPACE_FILES)} files -> {staging}")
        for f in sorted(staging.iterdir()):
            print(f"  {f.name:20s} {f.stat().st_size:>7,} bytes")

        hf = ROOT / ".venv" / "Scripts" / "hf.exe"
        # No --exclude: the staging directory is built from scratch and holds exactly
        # the files above, so there is nothing to filter. Passing a glob here is also
        # actively harmful -- under an MSYS shell (Git Bash) the runtime expands
        # "**/__pycache__/**" against the *local* directory before hf.exe sees it, and
        # the expansion lands in hf upload's third positional slot, path_in_repo. That
        # silently published every file into a subdirectory named after a .pyc.
        cmd = [str(hf) if hf.exists() else "hf", "upload", repo_id, str(staging),
               "--repo-type", "space",
               "--commit-message", "Deploy NVIDIA DCF valuation app"]
        print("\n$ " + " ".join(cmd))
        return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
