"""Component-level Tk smoke test. Uses temporary memory and never controls other apps."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from app import DesktopPet, enable_dpi
from brain import ACTIONS
from engine import PetEngine
from storage import PetStore
from verify_learning import run_verification


def run():
    enable_dpi()
    checks = {}
    with tempfile.TemporaryDirectory() as directory:
        store = PetStore(directory)
        engine = PetEngine()
        app = DesktopPet(engine, store)
        try:
            app.root.withdraw()
            app.show_panel()
            app.panel.update_idletasks()
            layout = {"panel_size": [app.panel.winfo_width(), app.panel.winfo_height()],
                      "panel_requested": [app.panel.winfo_reqwidth(), app.panel.winfo_reqheight()],
                      "panel_content_height": app.panel_content.winfo_reqheight(),
                      "render_scale": app.render_scale,
                      "pet_size": [app.width, app.height],
                      "pet_canvas_items": len(app.canvas.find_all()),
                      "pet_canvas_bounds": app.canvas.bbox("all")}
            region = [float(n) for n in app.panel_viewport.cget("scrollregion").split()]
            checks["panel_content_accessible_by_scroll"] = region[3] >= layout["panel_content_height"]
            app.panel.withdraw()
            initial = engine.brain.user_updates
            app.interact("praise")
            checks["feedback_callback_updates_weights"] = engine.brain.user_updates == initial + 1
            checks["feedback_is_saved"] = store.read(store.path).brain.weights == engine.brain.weights
            app.toggle("frozen")
            frozen_weights = engine.brain.to_dict()["weights"]
            app.interact("feed")
            checks["freeze_callback_blocks_learning"] = engine.brain.weights == frozen_weights
            app.toggle("paused")
            action = engine.action
            app.interact("pet")
            checks["paused_interaction_does_not_choose_new_action"] = action == engine.action
            checks["paused_feedback_is_not_learned"] = not engine.memory[-1]["learned"]
            updates = engine.brain.updates
            for _ in range(10):
                engine.advance(1)
            checks["paused_clock_does_not_learn"] = engine.brain.updates == updates
            app.toggle("paused")
            app.toggle("frozen")
            # Exercise the actual drag handlers with a synthetic local event fixture.
            user_updates = engine.brain.user_updates
            app.press(SimpleNamespace(x_root=100, y_root=100))
            app.drag(SimpleNamespace(x_root=140, y_root=115))
            app.release(SimpleNamespace(x=90, y=90))
            checks["drag_does_not_reward_action"] = engine.brain.user_updates == user_updates
            app.update_panel()
            checks["panel_reports_actual_update_count"] = str(engine.brain.updates) in app.learning_var.get()
            checks["canvas_has_pet_drawing"] = layout["pet_canvas_items"] >= 25
            checks["canvas_drawing_fits"] = (layout["pet_canvas_bounds"][0] >= 0 and
                                           layout["pet_canvas_bounds"][1] >= 0 and
                                           layout["pet_canvas_bounds"][2] <= app.width and
                                           layout["pet_canvas_bounds"][3] <= app.height)
            unchanged_brain = engine.brain.to_dict()
            checks["size_changes_keep_learning"] = True
            for size, pixels in (("mini", 156), ("medium", 280), ("small", 208)):
                app.set_size(size)
                app.root.update_idletasks()
                checks["size_changes_keep_learning"] &= (app.width == pixels and app.height == pixels and
                                                          engine.brain.to_dict() == unchanged_brain)
            checks["size_preference_persisted"] = json.loads((store.directory / "display.json").read_text())["size"] == "small"
            saved_action = engine.action
            checks["all_action_poses_fit_canvas"] = True
            for action in ACTIONS:
                engine.action = action
                for phase in (0, .15, .8, 1.5, 3.2):
                    app.elapsed = phase
                    app.draw()
                    x0, y0, x1, y1 = app.canvas.bbox("all")
                    checks["all_action_poses_fit_canvas"] &= x0 >= 0 and y0 >= 0 and x1 <= app.width and y1 <= app.height
            engine.action = saved_action
            app.save()
            checks["round_trip_business_state"] = store.read(store.path).to_dict() == engine.to_dict()
        finally:
            if not app.closing:
                app.close()
    evidence = run_verification()
    return {"ui_scope": "Tk component layout/callback checks, not native screenshot review",
            "checks": checks, "layout": layout, "learning": evidence,
            "passed": all(checks.values()) and evidence["passed"]}


if __name__ == "__main__":
    report = run()
    output = Path(__file__).resolve().parent / "qa"
    output.mkdir(exist_ok=True)
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["checks"], "layout": report["layout"]},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
