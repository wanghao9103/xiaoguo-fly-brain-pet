"""Exercise bundled Tk, HTML, HTTP and persistence without using real pet data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from urllib.request import Request, urlopen


def run(destination):
    report = {"passed": False, "frozen": bool(getattr(sys, "frozen", False))}
    previous = os.environ.get("FLYBRAINPET_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory(prefix="xiaoguo-exe-test-") as directory:
            os.environ["FLYBRAINPET_DATA_DIR"] = str(Path(directory) / "FlyBrainPet")
            from verify_runtime import run as verify_runtime
            from lab import LabService
            report["runtime"] = verify_runtime()
            service = LabService(
                report_dir=None if report["frozen"] else Path(directory) / "reports",
                game_data_dir=Path(directory) / "chess").start()
            checks = {}
            try:
                def request(route, payload=None):
                    req = Request(service.url + route, headers={
                        "X-Lab-Token": service.token, "Content-Type": "application/json"},
                        data=None if payload is None else json.dumps(payload).encode())
                    return urlopen(req, timeout=20)

                for route in ("", "games"):
                    with request(route) as response:
                        page = response.read().decode("utf-8")
                    checks["html_" + (route or "lab")] = "__BOOT__" not in page and "</html>" in page
                with request("api/state") as response:
                    checks["lab_api"] = "state" in json.load(response)
                with request("api/games/state") as response:
                    state = json.load(response)["game"]
                with request("api/games/move", {"move": [7, 7], "revision": state["revision"]}) as response:
                    checks["chess_move"] = len(json.load(response)["game"]["history"]) == 2
                with request("api/export-report", {}) as response:
                    saved = Path(json.load(response)["saved_to"])
                checks["report_exists"] = saved.is_file()
                if report["frozen"]:
                    checks["report_outside_bundle"] = saved.parent == Path(directory) / "FlyBrainPet" / "lab_reports"
            finally:
                service.stop()
            checks["chess_saved"] = any((Path(directory) / "chess").glob("*.json"))
            report["bundle_checks"] = checks
            report["passed"] = report["runtime"]["passed"] and all(checks.values())
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if previous is None:
            os.environ.pop("FLYBRAINPET_DATA_DIR", None)
        else:
            os.environ["FLYBRAINPET_DATA_DIR"] = previous
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
