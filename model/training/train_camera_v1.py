#!/usr/bin/env python3
"""train_camera_v1.py — camera-v1 手势模型训练（RF + 交叉验证 + 规则版对比）

输入：export_windows.py 导出的 npz
  X           (n, 24) float32   — 24 维特征（FEATURE_NAMES 顺序）
  y           (n,)   str        — 9 个 canonical 标签
  ts          (n,)   float64    — 窗口时间戳
  rule_pred   (n,)   str        — 逐窗规则版预测（用于精度对比）
  feature_names / feature_version — 导出侧契约（训练前强校验）

输出（pickle.dump 三件套，GestureClassifier 加载契约）：
  model/models/gesture_classifier.pkl
  {"feature_version": "camera-v1", "model": <sklearn RF>, "feature_names": [...]}

用法：
  python model/training/train_camera_v1.py                      # 用最新导出的 npz
  python model/training/train_camera_v1.py --data <npz> --grid  # 网格搜索
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

# 防御：管道/重定向到 GBK 环境时 ⚠ 等字符不让 print 崩
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score)
from sklearn.model_selection import (GridSearchCV, StratifiedKFold,
                                     cross_val_score, train_test_split)

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from model.inference import (  # noqa: E402
    CANONICAL_GESTURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    GestureClassifier,
)

DEFAULT_OUTPUT = _REPO_ROOT / "model" / "models" / "gesture_classifier.pkl"
MIN_PER_CLASS = 2  # stratify 下限；<30 仅警告


def _latest_npz() -> Path:
    candidates = sorted(
        (_REPO_ROOT / "data" / "processed").glob("gesture_windows*.npz"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise SystemExit("data/processed/ 下没有 gesture_windows*.npz，"
                         "先跑 export_windows.py --sessions")
    return candidates[-1]


def load_dataset(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.load(path, allow_pickle=False)
    version = str(data["feature_version"])
    if version != FEATURE_VERSION:
        raise SystemExit(f"feature_version 不符：{version!r} != {FEATURE_VERSION!r}")
    names = [str(n) for n in data["feature_names"]]
    if names != list(FEATURE_NAMES):
        raise SystemExit("feature_names 与 FEATURE_NAMES 不一致，导出侧有漂移")
    X = np.asarray(data["X"], dtype=np.float64)
    y = np.asarray(data["y"])
    rule_pred = np.asarray(data["rule_pred"])
    if X.shape[1] != len(FEATURE_NAMES):
        raise SystemExit(f"X 维度 {X.shape} 与 24 维契约不符")
    if not (len(X) == len(y) == len(rule_pred)):
        raise SystemExit("X / y / rule_pred 长度不一致")
    return X, y, rule_pred


def main() -> int:
    parser = argparse.ArgumentParser(description="camera-v1 手势模型训练")
    parser.add_argument("--data", type=Path, default=None,
                        help="导出 npz（默认 data/processed/ 下最新的 gesture_windows*）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"bundle 输出（默认 {DEFAULT_OUTPUT}）")
    parser.add_argument("--test-size", type=float, default=0.25)
    parser.add_argument("--cv", type=int, default=5, help="分层 K 折（默认 5）")
    parser.add_argument("--grid", action="store_true", help="启用 GridSearchCV 小网格")
    parser.add_argument("--allow-missing-classes", action="store_true",
                        help="显式允许数据集缺少部分手势类别（缺类将永远无法被预测！）")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_path = args.data or _latest_npz()
    X, y, rule_pred = load_dataset(data_path)

    print("=" * 64)
    print("  camera-v1 手势模型训练")
    print("=" * 64)
    print(f"  数据:   {data_path}")
    print(f"  样本:   {len(X)} × {X.shape[1]} 维")
    labels, counts = np.unique(y, return_counts=True)
    for lbl, cnt in sorted(zip(labels, counts), key=lambda kv: -kv[1]):
        flag = "  ⚠ 样本偏少" if cnt < 30 else ""
        print(f"    {lbl:15s} {cnt:5d}{flag}")
    too_few = [lbl for lbl, cnt in zip(labels, counts) if cnt < MIN_PER_CLASS]
    if too_few:
        raise SystemExit(f"类别样本 <{MIN_PER_CLASS}，无法分层切分: {too_few}")
    missing = [g for g in CANONICAL_GESTURES if g not in set(labels)]
    if missing and not args.allow_missing_classes:
        raise SystemExit(
            f"数据集缺少 {len(missing)} 个手势类别: {missing}\n"
            f"缺少的类别训练后将永远无法被预测（GestureClassifier 只映射 "
            f"model.classes_）！请补录后重新导出，或显式 --allow-missing-classes"
        )

    idx = np.arange(len(X))
    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, idx, test_size=args.test_size, random_state=args.seed, stratify=y,
    )
    print(f"\n  训练: {len(X_train)} | 测试: {len(X_test)} "
          f"(stratified, seed={args.seed})")

    base_rf = RandomForestClassifier(
        n_estimators=300,
        class_weight="balanced_subsample",
        random_state=args.seed,
        n_jobs=-1,
    )

    t0 = time.time()
    if args.grid:
        param_grid = {
            "max_depth": [8, 16, None],
            "min_samples_leaf": [1, 2, 4],
        }
        search = GridSearchCV(
            base_rf, param_grid,
            cv=StratifiedKFold(args.cv, shuffle=True, random_state=args.seed),
            scoring="f1_weighted", n_jobs=-1,
        )
        search.fit(X_train, y_train)
        model = search.best_estimator_
        cv_best = search.best_score_
        print(f"  网格:   最优 {search.best_params_} | CV f1w {cv_best:.4f}")
    else:
        model = base_rf
        cv_scores = cross_val_score(
            model, X_train, y_train,
            cv=StratifiedKFold(args.cv, shuffle=True, random_state=args.seed),
            scoring="f1_weighted", n_jobs=-1,
        )
        cv_best = float(cv_scores.mean())
        print(f"  CV:     {args.cv} 折 f1w {cv_best:.4f} ± {cv_scores.std():.4f}")
        model.fit(X_train, y_train)
    print(f"  训练耗时: {time.time() - t0:.1f}s")

    # ── 测试集评估 ─────────────────────────────────────────────────────
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average="weighted")
    print("\n" + "-" * 64)
    print(f"  测试集: accuracy {acc:.4f} | f1w {f1:.4f}")
    print("-" * 64)
    label_order = [g for g in CANONICAL_GESTURES if g in set(y)]
    print(classification_report(y_test, y_pred, labels=label_order,
                                zero_division=0))
    print("  混淆矩阵（行=真实，列=预测）:")
    print(f"  标签序: {label_order}")
    print(confusion_matrix(y_test, y_pred, labels=label_order))

    # ── 规则版对比（同一批测试窗）─────────────────────────────────────
    rule_test = rule_pred[idx_test]
    rule_acc = accuracy_score(y_test, rule_test)
    rule_f1 = f1_score(y_test, rule_test, average="weighted", zero_division=0)
    rule_full_acc = accuracy_score(y, rule_pred)
    print("\n" + "=" * 64)
    print("  模型 vs 规则版")
    print("=" * 64)
    print(f"  测试集:  RF acc {acc:.4f} / f1w {f1:.4f}"
          f"   vs   规则 acc {rule_acc:.4f} / f1w {rule_f1:.4f}")
    print(f"  全量集:  规则 acc {rule_full_acc:.4f}（RF 全量拟合不在此比较，防过拟合假象）")
    if acc < rule_acc:
        print("  ⚠ 测试集上 RF 不如规则版：检查样本量/标注质量，或继续采数据")

    # ── 特征重要性 ─────────────────────────────────────────────────────
    print("\n  Top 12 特征重要性:")
    importances = model.feature_importances_
    for rank, fi in enumerate(np.argsort(importances)[::-1][:12], 1):
        print(f"    {rank:2d}. {FEATURE_NAMES[fi]:24s} {importances[fi]:.4f}")

    # ── 保存 bundle（三件套契约）───────────────────────────────────────
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "feature_version": FEATURE_VERSION,
        "model": model,
        "feature_names": list(FEATURE_NAMES),
    }
    with open(args.output, "wb") as f:
        pickle.dump(bundle, f)
    print(f"\n  [SAVE] bundle → {args.output}")

    # 回读验收：走 GestureClassifier 真实加载路径
    probe = GestureClassifier(model_path=str(args.output))
    if probe.mode != "model":
        raise SystemExit("回读失败：GestureClassifier 未进入 model 模式")
    probe_probs = probe._model.predict_proba(X_test[:2])  # noqa: SLF001
    if probe_probs.shape[0] != 2:
        raise SystemExit("回读失败：predict_proba 输出异常")
    print("  [OK] 回读验收通过（mode=model，predict_proba 正常）")

    report = {
        "data": str(data_path),
        "output": str(args.output),
        "trained_at": time.time(),
        "n_samples": int(len(X)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "label_counts": {str(k): int(v) for k, v in zip(labels, counts)},
        "cv_f1_weighted": cv_best,
        "test_accuracy": float(acc),
        "test_f1_weighted": float(f1),
        "rules_test_accuracy": float(rule_acc),
        "rules_test_f1_weighted": float(rule_f1),
        "grid": bool(args.grid),
        "seed": args.seed,
    }
    report_path = args.output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"  [SAVE] 训练报告 → {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
