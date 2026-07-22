"""
Random Forest Gesture Classifier — Training Pipeline
=====================================================
1. Load raw data from collected CSVs
2. Extract features using SlidingWindowMerger
3. Train RandomForestClassifier with GridSearchCV
4. Evaluate and save model

Usage:
  python training/train_model.py --data data/raw/ --output models/gesture_classifier.pkl
"""

import os
import sys
import csv
import json
import argparse
import pickle
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.metrics import (classification_report, confusion_matrix,
                              accuracy_score, precision_recall_fscore_support)
from joblib import dump

# Add parent dir for imports
_script_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_script_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from feature_engineering.camera_features import CameraFeatureExtractor, CameraFeatureVector
from feature_engineering.accel_features import AccelFeatureExtractor, AccelFeatureVector
from feature_engineering.window_merger import SlidingWindowMerger
from microbit_receiver import AccelSample


# ============================================================
# Data Loading
# ============================================================

def load_recordings(data_dir: str) -> list[dict]:
    """
    Load all recording sessions from data directory.

    Returns list of session dicts:
      { 'label': str, 'landmarks_csv': Path, 'accel_csv': Path, 'meta_json': Path }
    """
    data_path = Path(data_dir)
    sessions = []
    seen_prefixes = set()

    for meta_file in sorted(data_path.glob("*_meta.json")):
        prefix = meta_file.stem.replace("_meta", "")
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)

        with open(meta_file) as f:
            meta = json.load(f)

        lm_file = data_path / f"{prefix}_landmarks.csv"
        accel_file = data_path / f"{prefix}_accel.csv"

        if lm_file.exists() and accel_file.exists():
            sessions.append({
                'label': meta['label'],
                'landmarks_csv': lm_file,
                'accel_csv': accel_file,
                'meta': meta,
            })

    print(f"[LOAD] Found {len(sessions)} recording sessions")
    label_counts = defaultdict(int)
    for s in sessions:
        label_counts[s['label']] += 1
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count} sessions")
    return sessions


def parse_landmarks_csv(csv_path: Path) -> list[tuple[float, list]]:
    """
    Parse landmarks CSV → list of (timestamp, hands_list).

    CSV format: timestamp, lm0_x, lm0_y, lm0_z, ..., num_hands
    """
    frames = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            ts = float(row[0])
            num_hands = int(row[-1])
            coords = [float(v) for v in row[1:-1]]  # 63 values for one hand

            hands_list = []
            if num_hands > 0 and len(coords) >= 63:
                hands_list.append(coords[:63])
            frames.append((ts, hands_list))
    return frames


def parse_accel_csv(csv_path: Path) -> list[AccelSample]:
    """
    Parse accelerometer CSV → list of AccelSample.

    CSV format: pc_ts, device_id, acc_x, acc_y, acc_z, timestamp_ms
    """
    samples = []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)  # skip header
        for row in reader:
            s = AccelSample(
                device_id=row[1],
                acc_x=float(row[2]),
                acc_y=float(row[3]),
                acc_z=float(row[4]),
                timestamp_ms=int(row[5]),
                pc_timestamp=float(row[0]),
            )
            samples.append(s)
    return samples


# ============================================================
# Feature Extraction from Recordings
# ============================================================

def extract_features(sessions: list[dict], window_ms: float = 500,
                     stride_ms: float = 250) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """
    Extract joint feature vectors from all recording sessions.

    Returns:
        X: feature matrix (n_samples × n_features)
        y: label array
        feature_names: list of feature names
    """
    all_features = []
    all_labels = []

    from feature_engineering.window_merger import JointFeatureVector

    for i, session in enumerate(sessions):
        label = session['label']
        print(f"  [{i+1}/{len(sessions)}] Processing '{label}'...")

        # Parse raw data
        cam_frames = parse_landmarks_csv(session['landmarks_csv'])
        accel_samples = parse_accel_csv(session['accel_csv'])

        if not cam_frames or not accel_samples:
            print(f"    WARN: Empty data, skipping")
            continue

        # Feed into sliding window merger
        merger = SlidingWindowMerger(
            window_ms=window_ms,
            stride_ms=stride_ms,
            camera_fps=session['meta'].get('landmark_fps', 30),
            accel_hz=session['meta'].get('accel_hz', 50),
        )

        for ts, hands in cam_frames:
            merger.add_camera_frame(hands, ts)

        for sample in accel_samples:
            merger.add_accel_sample(sample)

        # Extract windows
        windows = merger.extract_windows(label=label)
        print(f"    Extracted {len(windows)} windows")

        for jfv in windows:
            all_features.append(jfv.to_list())
            all_labels.append(label)

    X = np.array(all_features)
    y = np.array(all_labels)
    feature_names = JointFeatureVector.feature_names()

    print(f"\n[FEAT] Total: {len(all_features)} samples, {X.shape[1]} features")
    print(f"[FEAT] Labels: {sorted(set(all_labels))}")
    for lbl in sorted(set(all_labels)):
        count = sum(1 for l in all_labels if l == lbl)
        print(f"  {lbl}: {count}")

    return X, y, feature_names


# ============================================================
# Model Training
# ============================================================

def train_random_forest(X: np.ndarray, y: np.ndarray,
                        feature_names: list[str]) -> RandomForestClassifier:
    """
    Train Random Forest classifier with GridSearchCV.
    """
    print("\n" + "=" * 60)
    print("  Training Random Forest Classifier")
    print("=" * 60)

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\n  Train: {len(X_train)} samples")
    print(f"  Test:  {len(X_test)} samples")

    # Parameter grid
    param_grid = {
        'n_estimators': [100, 200, 300],
        'max_depth': [10, 20, 30, None],
        'min_samples_split': [2, 5, 10],
        'min_samples_leaf': [1, 2, 4],
        'class_weight': ['balanced', None],
    }

    print("\n  Running GridSearchCV...")
    base_rf = RandomForestClassifier(random_state=42, n_jobs=-1)
    grid = GridSearchCV(
        base_rf, param_grid,
        cv=3, scoring='f1_weighted',
        n_jobs=-1, verbose=1,
    )
    grid.fit(X_train, y_train)

    print(f"\n  Best params: {grid.best_params_}")
    print(f"  Best CV score: {grid.best_score_:.4f}")

    # Evaluate on test set
    best_model = grid.best_estimator_
    y_pred = best_model.predict(X_test)

    print("\n" + "-" * 40)
    print("  Test Set Evaluation")
    print("-" * 40)
    acc = accuracy_score(y_test, y_pred)
    prec, rec, f1, _ = precision_recall_fscore_support(y_test, y_pred, average='weighted')

    print(f"  Accuracy:  {acc:.4f}")
    print(f"  Precision: {prec:.4f}")
    print(f"  Recall:    {rec:.4f}")
    print(f"  F1 Score:  {f1:.4f}")

    print("\n  Classification Report:")
    print(classification_report(y_test, y_pred))

    print("  Confusion Matrix:")
    cm = confusion_matrix(y_test, y_pred)
    print(f"  Labels: {sorted(set(y))}")
    print(cm)

    # Feature importance
    print("\n" + "-" * 40)
    print("  Top 15 Feature Importances")
    print("-" * 40)
    importances = best_model.feature_importances_
    indices = np.argsort(importances)[::-1]
    for rank, idx in enumerate(indices[:15], 1):
        name = feature_names[idx] if idx < len(feature_names) else f"f{idx}"
        print(f"  {rank:2d}. {name:40s} = {importances[idx]:.4f}")

    return best_model


# ============================================================
# Generate Synthetic Training Data (for initial dev/testing)
# ============================================================

def generate_synthetic_data(n_samples_per_class: int = 100) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate synthetic feature vectors for initial model testing.
    Each gesture class has distinct patterns in camera + accel features.

    This allows us to train and test the pipeline BEFORE collecting real data.
    """
    np.random.seed(42)

    # Gesture definitions: (name, pattern parameters)
    gestures = {
        'beat_4_4':    dict(velocity_x=0.3, vertical_range=0.4, acc_norm=150, peak_count=4),
        'beat_3_4':    dict(velocity_x=0.2, vertical_range=0.3, acc_norm=120, peak_count=3),
        'beat_2_4':    dict(velocity_x=0.4, vertical_range=0.5, acc_norm=180, peak_count=2),
        'crescendo':   dict(velocity_x=0.1, vertical_range=0.6, acc_norm=200, peak_count=1),
        'diminuendo':  dict(velocity_x=0.1, vertical_range=0.5, acc_norm=100, peak_count=1),
        'cutoff':      dict(velocity_x=0.5, vertical_range=0.1, acc_norm=300, peak_count=1),
        'hold':        dict(velocity_x=0.05, vertical_range=0.05, acc_norm=20, peak_count=0),
        'upbeat':      dict(velocity_x=0.2, vertical_range=0.2, acc_norm=100, peak_count=1),
        'idle':        dict(velocity_x=0.02, vertical_range=0.02, acc_norm=10, peak_count=0),
    }

    cam_names = CameraFeatureVector.feature_names()
    accel_names = AccelFeatureVector.feature_names()
    all_names = cam_names + accel_names

    X_list = []
    y_list = []

    for label, params in gestures.items():
        for _ in range(n_samples_per_class):
            vec = []

            # Camera features (25)
            for name in cam_names:
                if 'velocity_x_mean' in name:
                    vec.append(np.random.normal(params['velocity_x'], 0.1))
                elif 'velocity_y_mean' in name:
                    vec.append(np.random.normal(0, 0.05))
                elif 'velocity_std' in name:
                    vec.append(np.random.normal(params['velocity_x'] * 0.5, 0.05))
                elif 'acceleration_mean' in name:
                    vec.append(np.random.normal(params['acc_norm'] * 0.01, 0.005))
                elif 'vertical_range' in name:
                    vec.append(np.random.normal(params['vertical_range'], 0.05))
                elif 'vertical_travel' in name:
                    vec.append(np.random.normal(params['vertical_range'] * 2, 0.1))
                elif 'vertical_speed' in name:
                    vec.append(np.random.normal(params['vertical_range'] * 30, 5))
                elif 'peak_count' in name:
                    vec.append(np.random.normal(params['peak_count'], 0.5))
                elif 'centroid_x_mean' in name or 'centroid_y_mean' in name:
                    vec.append(np.random.normal(0.5, 0.1))
                elif 'centroid_x_std' in name or 'centroid_y_std' in name:
                    vec.append(np.random.normal(0.05, 0.02))
                elif 'hand_presence_ratio' in name:
                    vec.append(np.random.normal(0.9, 0.1))
                else:
                    vec.append(np.random.normal(0, 0.1))

            # Accel features (18)
            for name in accel_names:
                if 'acc_norm_mean' in name:
                    vec.append(np.random.normal(params['acc_norm'] + 1000, 100))
                elif 'acc_norm_std' in name:
                    vec.append(np.random.normal(params['acc_norm'] * 0.3, 50))
                elif 'mean_jerk' in name:
                    vec.append(np.random.normal(params['acc_norm'] * 0.1, 10))
                elif 'peak_count' in name:
                    vec.append(np.random.normal(params['peak_count'], 0.5))
                elif 'tilt_angle' in name:
                    vec.append(np.random.normal(30, 15))
                else:
                    vec.append(np.random.normal(0, 0.5))

            X_list.append(vec)
            y_list.append(label)

    return np.array(X_list), np.array(y_list)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Train Random Forest Gesture Classifier")
    parser.add_argument("--data", type=str, default="data/raw/",
                        help="Path to recorded data directory (or 'synthetic')")
    parser.add_argument("--output", type=str, default="models/gesture_classifier.pkl",
                        help="Output model path")
    parser.add_argument("--window-ms", type=float, default=500,
                        help="Sliding window size (ms)")
    parser.add_argument("--stride-ms", type=float, default=250,
                        help="Sliding window stride (ms)")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load data
    if args.data == "synthetic":
        print("[DATA] Generating synthetic training data...")
        X, y = generate_synthetic_data(n_samples_per_class=200)
        feature_names = CameraFeatureVector.feature_names() + AccelFeatureVector.feature_names()
    else:
        sessions = load_recordings(args.data)
        if not sessions:
            print("[ERROR] No recordings found. Run collect_data.py first, or use --data synthetic")
            sys.exit(1)
        X, y, feature_names = extract_features(sessions, args.window_ms, args.stride_ms)

    if len(X) == 0:
        print("[ERROR] No features extracted. Check your data or use --data synthetic")
        sys.exit(1)

    # Train
    model = train_random_forest(X, y, feature_names)

    # Save model
    dump(model, output_path)
    print(f"\n[SAVE] Model saved to: {output_path}")

    # Also save feature names for inference
    meta_path = output_path.with_suffix('.meta.pkl')
    meta = {
        'feature_names': feature_names,
        'labels': sorted(set(y)),
        'n_features': X.shape[1],
    }
    with open(meta_path, 'wb') as f:
        pickle.dump(meta, f)
    print(f"[SAVE] Metadata saved to: {meta_path}")


if __name__ == "__main__":
    main()
