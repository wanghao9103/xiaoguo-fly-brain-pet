"""Small synthetic experiments on disposable FlyBrain clones; no files or GUI.

Training deliberately provides feedback for every action, rather than pretending
to be on-policy learning from a pet or a real user. Evaluation never calls choose,
and probe randomness uses an independent RNG. Returned objects contain JSON data.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Sequence

from brain import ACTIONS, FlyBrain

EXPERIMENTS = {
    "association": "两种情境的关联学习",
    "reversal": "偏好反转与旧情境保持",
    "noise": "陌生扰动与局部泛化",
    "interference": "新习惯对旧习惯的干扰",
    "sensitivity": "局部特征敏感性",
}
PRESETS = {
    "tired": [.08, .90, .20, .10, .10, .95, .85, .05, .85, .90, .10, .95],
    "lively": [.95, .10, .90, .95, .90, .15, .10, .90, .05, .05, .90, .20],
    "social": [.75, .80, .08, .45, .95, .95, .20, .10, .10, .50, .65, .35],
}
BASE_FEATURE_LABELS = [
    "精力", "饱腹程度", "社交满足", "好奇程度", "鼠标接近", "鼠标缓慢",
    "靠近边缘", "最近抚摸", "最近进食", "闲置程度", "日间光照", "原地陪伴",
]
TRAIN_ROUNDS = 48
NOISE_LEVELS = (0.0, .02, .08, .15)
NOISE_SAMPLES_PER_CONTEXT = 30
INTERFERENCE_ROUNDS = 64


def _finite(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}必须是有限数字")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name}必须是有限数字") from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}必须位于{low}与{high}之间")
    return value


def to_features(base: Sequence[float]) -> list[float]:
    """Validate 12 base values and create 24 [value, 1-value] paired features."""
    if not isinstance(base, (list, tuple)) or len(base) != 12:
        raise ValueError("基础特征必须是包含12个数字的列表")
    values = [_finite(value, BASE_FEATURE_LABELS[i], 0, 1) for i, value in enumerate(base)]
    return [part for value in values for part in (value, 1.0 - value)]


def perturb_features(base: Sequence[float], amplitude: float,
                     rng: random.Random) -> list[float]:
    """Uniformly perturb base coordinates, clip, then rebuild complement pairs."""
    validated = to_features(base)[::2]
    amplitude = _finite(amplitude, "扰动幅度", 0, 1)
    if not isinstance(rng, random.Random):
        raise ValueError("扰动需要独立的random.Random实例")
    perturbed = [min(1.0, max(0.0, value + rng.uniform(-amplitude, amplitude)))
                 for value in validated]
    return to_features(perturbed)


def _clone(brain: FlyBrain) -> FlyBrain:
    return FlyBrain.from_dict(brain.to_dict())


def _teach_round(brain: FlyBrain, features: Sequence[float], target: str) -> None:
    for action in ACTIONS:
        brain.learn(features, action, 1.0 if action == target else -.6, source="intrinsic")


def _train_pair(brain: FlyBrain, rounds: int = TRAIN_ROUNDS) -> int:
    before = brain.updates
    for _ in range(rounds):
        _teach_round(brain, to_features(PRESETS["tired"]), "rest")
        _teach_round(brain, to_features(PRESETS["lively"]), "play")
    return brain.updates - before


def _probability(brain: FlyBrain, features: Sequence[float], target: str) -> float:
    return brain.probabilities(features)[ACTIONS.index(target)]


def _active(brain: FlyBrain, features: Sequence[float]) -> set[int]:
    return {index for index, value in enumerate(brain.encode(features)) if value > 0}


def _metric(label: str, value: float, format: str = "percent") -> dict:
    return {"label": label, "value": value, "format": format}


def _column(key: str, label: str, format: str = "percent") -> dict:
    return {"key": key, "label": label, "format": format}


def _result(kind: str, description: str) -> dict:
    return {
        "id": kind, "title": EXPERIMENTS[kind], "description": description,
        "summary": "", "metrics": [],
        "chart": {"x_label": "指导反馈次数", "y_label": "目标行动概率", "series": []},
        "table": {"columns": [], "rows": []}, "notes": [], "elapsed_seconds": 0.0,
    }


def _association(brain: FlyBrain, seed: int) -> dict:
    result = _result("association", "用相反的两种情境，观察指导反馈如何改变行动倾向。")
    tired, lively = (to_features(PRESETS[key]) for key in ("tired", "lively"))
    checkpoints = (0, 1, 2, 4, 8, 16, 32, TRAIN_ROUNDS)
    initial_updates = brain.updates
    rows = []
    for round_number in range(TRAIN_ROUNDS + 1):
        if round_number:
            _teach_round(brain, tired, "rest")
            _teach_round(brain, lively, "play")
        if round_number in checkpoints:
            rows.append({"updates": brain.updates - initial_updates,
                         "tired_rest": _probability(brain, tired, "rest"),
                         "lively_play": _probability(brain, lively, "play")})
    first, last = rows[0], rows[-1]
    result["summary"] = (f"完成{last['updates']}次指导反馈后，疲劳情境的休息概率从{first['tired_rest']:.1%}"
                         f"变为{last['tired_rest']:.1%}，活跃情境的玩耍概率从{first['lively_play']:.1%}"
                         f"变为{last['lively_play']:.1%}。")
    result["metrics"] = [_metric("疲劳→休息", last["tired_rest"]),
                         _metric("活跃→玩耍", last["lively_play"]),
                         _metric("新增指导反馈", last["updates"], "number")]
    result["chart"]["series"] = [
        {"name": label, "points": [[row["updates"], row[key]] for row in rows]}
        for key, label in (("tired_rest", "疲劳→休息"), ("lively_play", "活跃→玩耍"))]
    result["table"] = {"columns": [_column("updates", "新增反馈", "number"),
                                   _column("tired_rest", "疲劳→休息"),
                                   _column("lively_play", "活跃→玩耍")], "rows": rows}
    result["notes"] = ["每轮向两个固定情境的四个行动分别提供已知反馈，共8次更新；目标行动奖励为1，其余为−0.6。",
                       "曲线只检查训练过的两个情境，不能当作未见情境的泛化成绩。"]
    return result


def _reversal(brain: FlyBrain, seed: int) -> dict:
    result = _result("reversal", "先学习两种偏好，再只改变活跃情境的反馈，检查反转与保留。")
    pretraining_updates = _train_pair(brain)
    tired, lively = (to_features(PRESETS[key]) for key in ("tired", "lively"))
    initial_updates = brain.updates
    rows = []
    for round_number in range(41):
        if round_number:
            _teach_round(brain, lively, "approach")
        if round_number in (0, 1, 2, 4, 8, 16, 24, 40):
            rows.append({"updates": brain.updates - initial_updates,
                         "new_preference": _probability(brain, lively, "approach"),
                         "old_preference": _probability(brain, lively, "play"),
                         "other_context": _probability(brain, tired, "rest")})
    first, last = rows[0], rows[-1]
    result["summary"] = (f"{last['updates']}次反转反馈后，活跃情境的靠近概率为{last['new_preference']:.1%}，"
                         f"原玩耍概率为{last['old_preference']:.1%}；另一个疲劳情境的休息概率"
                         f"从{first['other_context']:.1%}变为{last['other_context']:.1%}。")
    result["metrics"] = [_metric("活跃→新偏好靠近", last["new_preference"]),
                         _metric("活跃→原偏好玩耍", last["old_preference"]),
                         _metric("疲劳→休息保留", last["other_context"])]
    result["chart"]["x_label"] = "新增反转反馈次数"
    result["chart"]["series"] = [
        {"name": label, "points": [[row["updates"], row[key]] for row in rows]}
        for key, label in (("new_preference", "活跃→靠近"), ("old_preference", "活跃→玩耍"),
                           ("other_context", "疲劳→休息"))]
    result["table"] = {"columns": [_column("updates", "反转反馈", "number"),
                                   _column("new_preference", "活跃→靠近"),
                                   _column("old_preference", "活跃→玩耍"),
                                   _column("other_context", "疲劳→休息")], "rows": rows}
    result["notes"] = [f"先进行{pretraining_updates}次两情境指导反馈，再只对活跃情境进行160次反转反馈。",
                       "旧情境能否保留取决于表示的重叠与学习规则；本例只有两个差异较大的情境。"]
    return result


def _noise(brain: FlyBrain, seed: int) -> dict:
    result = _result("noise", "在训练原型附近生成扰动输入，与不追加训练的冻结副本进行配对比较。")
    frozen = _clone(brain)
    training_updates = _train_pair(brain)
    rng = random.Random(seed)
    rows = []
    for amplitude in NOISE_LEVELS:
        totals = {"trained_probability": 0.0, "frozen_probability": 0.0,
                  "trained_greedy": 0, "frozen_greedy": 0}
        for preset, target in (("tired", "rest"), ("lively", "play")):
            for _ in range(NOISE_SAMPLES_PER_CONTEXT):
                features = perturb_features(PRESETS[preset], amplitude, rng)
                for name, model in (("trained", brain), ("frozen", frozen)):
                    probabilities = model.probabilities(features)
                    totals[f"{name}_probability"] += probabilities[ACTIONS.index(target)]
                    greedy = max(range(len(ACTIONS)), key=probabilities.__getitem__)
                    totals[f"{name}_greedy"] += int(ACTIONS[greedy] == target)
        count = 2 * NOISE_SAMPLES_PER_CONTEXT
        rows.append({"amplitude": amplitude, "samples": count,
                     **{key: value / count for key, value in totals.items()}})
    selected = rows[2]
    result["summary"] = (f"在±0.08扰动的{selected['samples']}个输入上，目标行动平均概率为"
                         f"{selected['trained_probability']:.1%}，冻结对照为{selected['frozen_probability']:.1%}；"
                         f"训练副本的最高概率行动命中率为{selected['trained_greedy']:.1%}。")
    result["metrics"] = [_metric("±0.08目标平均概率", selected["trained_probability"]),
                         _metric("±0.08冻结对照概率", selected["frozen_probability"]),
                         _metric("±0.08最高概率命中率", selected["trained_greedy"])]
    result["chart"]["x_label"] = "基础特征扰动幅度"
    result["chart"]["y_label"] = "平均目标行动概率"
    result["chart"]["series"] = [
        {"name": label, "points": [[row["amplitude"], row[key]] for row in rows]}
        for key, label in (("trained_probability", "追加指导训练"), ("frozen_probability", "冻结初始副本"))]
    result["table"] = {"columns": [_column("amplitude", "扰动幅度", "number"),
                                   _column("samples", "输入数", "number"),
                                   _column("trained_probability", "训练后目标概率"),
                                   _column("frozen_probability", "冻结目标概率"),
                                   _column("trained_greedy", "训练后最高概率命中"),
                                   _column("frozen_greedy", "冻结最高概率命中")], "rows": rows}
    result["notes"] = [f"追加训练{training_updates}次。每档两个原型各{NOISE_SAMPLES_PER_CONTEXT}个输入，共240个；双方使用完全相同的探针。",
                       "非零扰动探针未用于本次追加训练；0扰动只是训练原型复测。导入模型的既往训练历史不可知。",
                       "对12个基础值独立施加均匀扰动并裁剪到0～1，再生成互补项；这里检验原型附近的局部泛化。",
                       "命中率使用最高概率行动，并列时固定取行动顺序最前者；这不是实际随机抽样行动的准确率。",
                       "无初始模型时冻结对照没有训练，概率均为25%；两个目标类别上的固定并列选择可能产生50%的最高概率命中率。"]
    return result


def _interference(brain: FlyBrain, seed: int) -> dict:
    result = _result("interference", "学习与旧情境相似的新情境，比较只学新内容、交替复习与冻结。")
    a = to_features(PRESETS["tired"])
    b_base = [.75 * old + .25 * new for old, new in zip(PRESETS["tired"], PRESETS["lively"])]
    b = to_features(b_base)
    before_pretraining = brain.updates
    for _ in range(TRAIN_ROUNDS):
        _teach_round(brain, a, "rest")
    pretraining_updates = brain.updates - before_pretraining
    models = {"new_only": _clone(brain), "rehearsal": _clone(brain), "frozen": _clone(brain)}
    labels = {"new_only": "只学新情境", "rehearsal": "同预算交替复习", "frozen": "冻结旧模型"}
    initial_updates = brain.updates
    initial_a, initial_b = _probability(brain, a, "rest"), _probability(brain, b, "play")
    active_a, active_b = _active(brain, a), _active(brain, b)
    union = active_a | active_b
    overlap = len(active_a & active_b) / len(union) if union else 1.0
    curves = {(branch, target): [] for branch in models for target in ("a", "b")}
    for round_number in range(INTERFERENCE_ROUNDS + 1):
        if round_number:
            _teach_round(models["new_only"], b, "play")
            # Equal TOTAL feedback counts: half of rehearsal's budget returns to A.
            if round_number % 2:
                _teach_round(models["rehearsal"], a, "rest")
            else:
                _teach_round(models["rehearsal"], b, "play")
        if round_number in (0, 4, 8, 16, 32, 48, INTERFERENCE_ROUNDS):
            for branch, model in models.items():
                curves[branch, "a"].append([round_number * len(ACTIONS), _probability(model, a, "rest")])
                curves[branch, "b"].append([round_number * len(ACTIONS), _probability(model, b, "play")])
    rows = []
    for branch, model in models.items():
        updates = model.updates - initial_updates
        a_updates = updates // 2 if branch == "rehearsal" else 0
        rows.append({"branch": labels[branch], "updates": updates,
                     "a_updates": a_updates, "b_updates": updates - a_updates,
                     "a_probability": _probability(model, a, "rest"),
                     "b_probability": _probability(model, b, "play"),
                     "a_change": _probability(model, a, "rest") - initial_a})
    new_only, rehearsal, frozen = rows
    result["summary"] = (f"仅学新情境后，旧情境休息概率从{initial_a:.1%}变为{new_only['a_probability']:.1%}，"
                         f"新情境玩耍概率为{new_only['b_probability']:.1%}；同预算复习后分别为"
                         f"{rehearsal['a_probability']:.1%}与{rehearsal['b_probability']:.1%}。")
    result["metrics"] = [_metric("两情境活跃集合重叠", overlap),
                         _metric("仅新学习·旧情境概率", new_only["a_probability"]),
                         _metric("交替复习·旧情境概率", rehearsal["a_probability"]),
                         _metric("冻结·旧情境概率", frozen["a_probability"])]
    result["chart"]["x_label"] = "训练进度（计划反馈次数）"
    result["chart"]["series"] = [
        {"name": f"{labels[branch]}·{'旧情境休息' if target == 'a' else '新情境玩耍'}", "points": points}
        for (branch, target), points in curves.items()]
    result["table"] = {"columns": [_column("branch", "分支", "text"),
                                   _column("updates", "实际新增反馈", "number"),
                                   _column("a_updates", "旧情境反馈", "number"),
                                   _column("b_updates", "新情境反馈", "number"),
                                   _column("a_probability", "旧情境休息"),
                                   _column("b_probability", "新情境玩耍"),
                                   _column("a_change", "旧情境概率变化", "pp")], "rows": rows}
    result["notes"] = [f"先对A进行{pretraining_updates}次指导反馈；B的每项基础特征等于75%的疲劳原型加25%的活跃原型。",
                       f"分支起点一致，起点A休息概率{initial_a:.1%}、B玩耍概率{initial_b:.1%}；两训练分支各256次反馈。",
                       "交替复习把128次反馈用于A、128次用于B；只学新情境把256次全部用于B，比较的是固定总预算下的取舍。",
                       "冻结分支实际新增反馈为0，曲线横轴只用于对齐训练进度；读取概率不更新权重或消耗行动随机数。",
                       "重叠为活跃集合交集数量除以并集数量。这里只观察合成情境的训练干扰，不能推断人的记忆或时间遗忘。",
                       "当前模型在没有学习调用时不会自行随时间遗忘。"]
    return result


def _sensitivity(brain: FlyBrain, seed: int) -> dict:
    result = _result("sensitivity", "在疲劳原型附近逐项改变输入，检查休息概率及活跃单元的局部变化。")
    training_updates = _train_pair(brain)
    base = PRESETS["tired"][:]
    features = to_features(base)
    original_probability = _probability(brain, features, "rest")
    original_active = _active(brain, features)
    rows = []
    for index, label in enumerate(BASE_FEATURE_LABELS):
        row = {"feature": label, "base": base[index]}
        for name, delta in (("minus", -.05), ("plus", .05)):
            changed = base[:]
            changed[index] = min(1.0, max(0.0, changed[index] + delta))
            probe = to_features(changed)
            probability = _probability(brain, probe, "rest")
            row[f"{name}_probability"] = probability
            row[f"{name}_delta"] = probability - original_probability
            row[f"{name}_changes"] = len(original_active ^ _active(brain, probe))
        rows.append(row)
    strongest = max(rows, key=lambda row: max(abs(row["minus_delta"]), abs(row["plus_delta"])))
    largest_change = max(abs(strongest["minus_delta"]), abs(strongest["plus_delta"]))
    result["summary"] = (f"原情境的休息概率为{original_probability:.1%}。在本次±0.05扰动中，"
                         f"{strongest['feature']}对应的局部变化幅度最大，为{largest_change * 100:.2f}个百分点；"
                         "这是输入敏感度，不是行动的因果解释。")
    result["metrics"] = [_metric("原情境休息概率", original_probability),
                         _metric("最大绝对概率变化", largest_change, "pp"),
                         _metric("检查基础特征数", len(rows), "number")]
    result["chart"]["x_label"] = "基础特征"
    result["table"] = {"columns": [_column("feature", "基础特征", "text"),
                                   _column("base", "原值", "number"),
                                   _column("minus_probability", "减少后休息概率"),
                                   _column("plus_probability", "增加后休息概率"),
                                   _column("minus_delta", "减少后概率变化", "pp"),
                                   _column("plus_delta", "增加后概率变化", "pp"),
                                   _column("minus_changes", "减少后单元变化", "number"),
                                   _column("plus_changes", "增加后单元变化", "number")], "rows": rows}
    result["notes"] = [f"先进行{training_updates}次两情境指导反馈，再评估疲劳原型及24个单项扰动探针。",
                       "每次只改变一个基础值并同步更新互补项；越过0或1的部分被裁剪。原始输入为共同对照。",
                       "单元变化数是扰动前后活跃集合的对称差数量，包含退出与进入的单元；不等同于替换对数。",
                       "TopK竞争会产生跳变；这个点附近的敏感度不代表全局重要性、单调关系或生物因果机制。",
                       "本表不修改权重，不根据探针结果重新训练，也不要求所有特征都有明显效果。"]
    return result


def run_experiment(kind: str, seed: int = 42, initial: dict | None = None) -> dict:
    """Run an isolated experiment; initial and its saved RNG are never mutated.

    With initial=None, seed selects the projection. With an imported brain,
    its exact projection/readout/RNG state is cloned; seed only selects probes.
    elapsed_seconds is the only intentionally non-reproducible result field.
    """
    if not isinstance(kind, str) or kind not in EXPERIMENTS:
        raise ValueError("未知实验类型")
    if type(seed) is not int or not -(2**63) <= seed <= 2**63 - 1:
        raise ValueError("实验种子必须是64位范围内的整数")
    started = time.perf_counter()
    brain = FlyBrain(seed=seed) if initial is None else FlyBrain.from_dict(initial)
    functions = {"association": _association, "reversal": _reversal, "noise": _noise,
                 "interference": _interference, "sensitivity": _sensitivity}
    result = functions[kind](brain, seed)
    result["notes"].insert(0, f"实验种子为{seed}；网络宽度{brain.width}、每单元输入{brain.fan_in}个、保留{brain.k}个。"
                           + ("从独立新模型开始。" if initial is None else "从传入模型的完整内存副本开始，原模型不受影响。"))
    result["notes"].append("这是小规模合成实验；指导训练给每个行动提供已知反馈，不代表真实用户互动或自主策略采样。")
    result["notes"].append("概率包含模型的探索混合，不是成功率保证；没有访问、保存或训练桌面宠物的正式存档。")
    result["elapsed_seconds"] = time.perf_counter() - started
    return result
