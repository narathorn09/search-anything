"""Prepare a release: set the version, commit, and tag it (run on main).

    python tools/release.py 1.1.0
    git push origin main v1.1.0

Pushing the tag makes CI build the Windows installer and macOS disk images
and publish them as GitHub release v1.1.0; installed apps then offer the
update (Settings > เกี่ยวกับและอัปเดต). CI refuses tags whose commit is not on
main or whose number differs from search_anything/__version__.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "search_anything" / "__init__.py"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        print(__doc__)
        return 2
    version = sys.argv[1]
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        print(f"releases are made on main (you are on {branch})")
        return 1
    if git("status", "--porcelain", "--untracked-files=no"):
        print("commit or stash your changes first")
        return 1
    current = re.search(r'__version__ = "([^"]+)"', INIT.read_text()).group(1)
    if tuple(map(int, version.split("."))) <= tuple(map(int, current.split("."))):
        print(f"{version} must be newer than the current {current}")
        return 1
    INIT.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', INIT.read_text()))
    git("commit", "-am", f"Release v{version}")
    git("tag", "-a", f"v{version}", "-m", f"Search Anything {version}")
    print(f"Ready. Publish with:\n\n    git push origin main v{version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
