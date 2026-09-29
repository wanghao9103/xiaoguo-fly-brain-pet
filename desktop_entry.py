"""Single executable entry point for the pet and its optional laboratory."""
import sys


def main():
    if "--self-test" in sys.argv[1:]:
        import argparse
        from pathlib import Path
        from packaged_smoke import run
        parser = argparse.ArgumentParser(description="Verify the bundled app using temporary save data")
        parser.add_argument("--self-test", type=Path, required=True, metavar="REPORT_JSON")
        args = parser.parse_args()
        return run(args.self_test)
    if "--lab" in sys.argv[1:] or "--games" in sys.argv[1:]:
        if "--lab" in sys.argv:
            sys.argv.remove("--lab")
        from lab import main as start
    else:
        from app import main as start
    start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
