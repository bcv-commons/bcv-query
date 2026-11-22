"""Entry point of the Hebrew levels builders (internal-docs/source-examples-spec/levels/SPEC-levels.md).

  shoresh/.venv/bin/python -I shoresh/macula/build_levels.py --build pilot-1 --stage 42
      [--root DIR]      the folder that holds the build (default shoresh/macula/data/hebrew-levels)
      [--sample PATH]   where the reader's sample goes (default internal-docs/source-examples-work/levels/sample-42.md)

Reads build i1 of the source examples only; writes only into <root>/<build>/ and the sample file.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from levels_common import DOCS, LEVELS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True)
    ap.add_argument("--stage", required=True, type=int)
    ap.add_argument("--root", default=str(LEVELS))
    ap.add_argument("--sample", default=None)
    a = ap.parse_args()
    out = Path(a.root) / a.build
    if a.stage == 42:
        import levels_stage42
        counts = levels_stage42.run(out, Path(a.sample) if a.sample else DOCS / "sample-42.md")
        print(json.dumps(counts, ensure_ascii=False, indent=1))
    elif a.stage == 43:
        import levels_stage43
        counts = levels_stage43.run(out, Path(a.sample) if a.sample else DOCS / "sample-43.md")
        print(json.dumps(counts, ensure_ascii=False, indent=1))
    else:
        sys.exit(f"stage {a.stage} is not built by this version")


if __name__ == "__main__":
    main()
