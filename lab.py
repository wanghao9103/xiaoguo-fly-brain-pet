"""Local-only learning laboratory. Every mutation stays inside a cloned model."""
import argparse
import copy
from datetime import datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import time
import webbrowser

from brain import ACTIONS, ACTION_LABELS, FEATURE_NAMES, FlyBrain
from experiments import BASE_FEATURE_LABELS, EXPERIMENTS, PRESETS, run_experiment, to_features

ROOT = Path(__file__).resolve().parent


def require_int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} 必须在 {low}–{high} 之间")
    return value


class LabSession:
    def __init__(self, initial=None):
        self.lock = threading.RLock()
        self.pet_snapshot = copy.deepcopy(initial)
        if initial is not None:
            FlyBrain.from_dict(self.pet_snapshot)
        self.last_result = None
        self.last_origin = None
        self.revision = 0
        self.reset("fresh", 42)

    def reset(self, source, seed=42):
        require_int(seed, "种子", 0, 2**31 - 1)
        if source == "fresh":
            self.brain = FlyBrain(seed=seed)
            self.source_label = f"空白实验脑 · 种子 {seed}"
        elif source == "pet" and self.pet_snapshot is not None:
            self.brain = FlyBrain.from_dict(copy.deepcopy(self.pet_snapshot))
            self.source_label = "打开实验室时的小果副本"
        else:
            raise ValueError("没有可用的小果副本，请从宠物菜单打开实验室")
        self.base = list(PRESETS["tired"])
        self.local_updates = 0
        self.history = []
        self.last_update = None
        self.last_result = None
        self.last_origin = None
        self.revision = 0
        self._record()

    def _probabilities(self):
        return dict(zip(ACTIONS, self.brain.probabilities(to_features(self.base))))

    def _record(self):
        self.history.append({"step": self.local_updates, "probabilities": self._probabilities()})
        self.history = self.history[-121:]

    def state(self):
        features = to_features(self.base)
        encoded = self.brain.encode(features)
        return {"source": self.source_label, "can_copy_pet": self.pet_snapshot is not None,
                "base": self.base[:], "feature_labels": list(BASE_FEATURE_LABELS),
                "presets": PRESETS, "actions": list(ACTIONS), "action_labels": ACTION_LABELS,
                "experiments": EXPERIMENTS, "probabilities": self._probabilities(),
                "scores": dict(zip(ACTIONS, self.brain.scores(features))),
                "active": [i for i, value in enumerate(encoded) if value > 0],
                "width": self.brain.width, "k": self.brain.k,
                "model_config": dict(self.brain.to_dict()["config"]),
                "local_updates": self.local_updates, "total_updates": self.brain.updates,
                "history": copy.deepcopy(self.history), "last_update": self.last_update,
                "experiment_matches_current": self.last_origin is not None and self.last_origin["revision"] == self.revision}

    def origin_summary(self):
        if self.last_origin is None:
            return None
        return {key: value for key, value in self.last_origin.items() if key not in ("model", "base")}

    def command(self, name, payload):
        if not isinstance(payload, dict):
            raise ValueError("请求必须是对象")
        with self.lock:
            if name == "context":
                values = payload.get("values")
                features = to_features(values)
                self.base = features[::2]
                self.revision += 1
                self.history = []
                self._record()
            elif name == "train":
                action = payload.get("action")
                if action not in ACTIONS:
                    raise ValueError("请选择一个有效行动")
                reward = payload.get("reward")
                if type(reward) not in (int, float) or reward not in (-1, 1):
                    raise ValueError("奖励只能为 +1 或 -1")
                steps = require_int(payload.get("steps", 1), "训练次数", 1, 200)
                features = to_features(self.base)
                for _ in range(steps):
                    self.last_update = self.brain.learn(features, action, reward, source="user")
                    self.local_updates += 1
                    self._record()
                self.revision += 1
            elif name == "reset":
                self.reset(payload.get("source", "fresh"), payload.get("seed", 42))
            elif name == "sample":
                count = require_int(payload.get("count", 100), "抽样次数", 1, 1000)
                counts = dict.fromkeys(ACTIONS, 0)
                for _ in range(count):
                    counts[self.brain.choose(to_features(self.base))] += 1
                self.revision += 1
                return {"state": self.state(), "sample": counts, "count": count}
            elif name == "experiment":
                experiment_id = payload.get("id")
                if experiment_id not in EXPERIMENTS:
                    raise ValueError("未知实验")
                seed = require_int(payload.get("seed", 42), "种子", 0, 2**31 - 1)
                if self.brain.width > 1024:
                    raise ValueError("快速实验支持最多 1024 个扩展单元，请改用空白实验脑")
                snapshot = self.brain.to_dict()
                origin = {"source": self.source_label, "manual_updates": self.local_updates,
                          "revision": self.revision, "probe_seed": seed, "base": self.base[:],
                          "model": copy.deepcopy(snapshot),
                          "fingerprint": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}
                # The tested object is detached, including its RNG. No mutation leaks back.
                self.last_result = run_experiment(experiment_id, seed=seed, initial=snapshot)
                self.last_origin = origin
                return {"state": self.state(), "experiment": copy.deepcopy(self.last_result),
                        "experiment_origin": self.origin_summary()}
            else:
                raise ValueError("未知操作")
            return {"state": self.state()}

    def export(self):
        with self.lock:
            return {"schema_version": 1, "scope": "isolated synthetic learning experiments",
                    "current_manual_state": self.state(), "experiment": copy.deepcopy(self.last_result),
                    "experiment_start": copy.deepcopy(self.last_origin)}


class LabService:
    def __init__(self, initial=None, port=0, report_dir=None):
        self.session = LabSession(initial)
        self.report_dir = Path(report_dir) if report_dir is not None else ROOT / "lab_reports"
        self.token = secrets.token_urlsafe(32)
        self.last_seen = time.monotonic()
        self.stopping = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, status, data):
                body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def allowed(self, api=False):
                port = self.server.server_port
                hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
                if self.headers.get("Host") not in hosts:
                    self.send_json(403, {"error": "只接受本机实验室请求"})
                    return False
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{host}" for host in hosts}:
                    self.send_json(403, {"error": "请求来源不匹配"})
                    return False
                if api and not hmac.compare_digest(self.headers.get("X-Lab-Token", "").encode("utf-8"), owner.token.encode("ascii")):
                    self.send_json(403, {"error": "请重新打开实验室页面"})
                    return False
                owner.last_seen = time.monotonic()
                return True

            def do_GET(self):
                api = self.path.startswith("/api/")
                if not self.allowed(api):
                    return
                if self.path == "/":
                    page = (ROOT / "lab.html").read_text(encoding="utf-8")
                    boot = json.dumps({"token": owner.token}, ensure_ascii=False).replace("<", "\\u003c")
                    body = page.replace("__BOOT__", boot).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Frame-Options", "DENY")
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/state":
                    with owner.session.lock:
                        self.send_json(200, {"state": owner.session.state()})
                elif self.path == "/api/export":
                    self.send_json(200, owner.session.export())
                elif self.path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                else:
                    self.send_json(404, {"error": "没有这个页面"})

            def do_POST(self):
                if not self.allowed(api=True):
                    return
                if self.headers.get_content_type() != "application/json":
                    self.send_json(415, {"error": "需要 JSON 格式"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        self.send_json(413, {"error": "请求大小不合适"})
                        return
                    payload = json.loads(self.rfile.read(length))
                    if not self.path.startswith("/api/"):
                        self.send_json(404, {"error": "未知操作"})
                        return
                    if self.path == "/api/export-report":
                        if payload != {}:
                            raise ValueError("保存报告不接受文件路径参数")
                        report = owner.session.export()
                        owner.report_dir.mkdir(parents=True, exist_ok=True)
                        filename = "experiment-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".json"
                        destination = owner.report_dir / filename
                        with destination.open("x", encoding="utf-8") as handle:
                            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
                        result = {"saved_to": str(destination.resolve())}
                    else:
                        result = owner.session.command(self.path.removeprefix("/api/"), payload)
                    self.send_json(200, result)
                except (ValueError, TypeError, KeyError, OverflowError) as error:
                    self.send_json(400, {"error": str(error)})
                except Exception:
                    self.send_json(500, {"error": "实验执行失败，原小果数据未改动"})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .2},
                                       name="fly-brain-lab", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        if self.thread is not None and self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    service = LabService(port=args.port).start()
    if sys.stdout is not None:
        print(f"LAB_URL={service.url}", flush=True)
    if not args.no_browser:
        webbrowser.open(service.url)
    try:
        while service.thread.is_alive():
            service.thread.join(timeout=1)
            if time.monotonic() - service.last_seen > 1800:
                break
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()


if __name__ == "__main__":
    main()
