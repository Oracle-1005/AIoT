"""
Pi 5 MediaPipe Hands 基准测试脚本
用途: 测试 Pi 5 跑 MediaPipe Hands 的实际帧率
用法: python benchmark_pi.py
      (先确认 hand_landmarker.task 在同目录下的 models/ 里)
输出: 终端打印每项指标，最后给出判定结论
"""

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import RunningMode
import time
import os
import sys

# ── 配置 ──────────────────────────────────────────────
DURATION = 15          # 每轮测试时长（秒）
RESOLUTIONS = [         # 要测试的分辨率
    (320, 240),
    (640, 480),
]
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "hand_landmarker.task")

# ── 检查模型文件 ──────────────────────────────────────
if not os.path.exists(MODEL_PATH):
    print(f"[ERR] 模型文件未找到: {MODEL_PATH}")
    print("      请确认 hand_landmarker.task 放在 model/models/ 目录下")
    sys.exit(1)

# ── 摄像头索引（Pi Camera 通常是 0，如有 USB 摄像头可能不同）───
CAM_INDEX = 0

# ── 辅助函数 ──────────────────────────────────────────
def bench_one_resolution(width, height):
    """对单一分辨率做 DURATION 秒的基准测试，返回统计 dict"""

    options = vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=MODEL_PATH),
        running_mode=RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_tracking_confidence=0.3,
    )
    landmarker = vision.HandLandmarker.create_from_options(options)

    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)

    actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    print(f"\n{'='*55}")
    print(f"[TEST] 分辨率: {actual_w:.0f}×{actual_h:.0f}  |  测试时长: {DURATION}s")
    print(f"{'='*55}")

    frame_idx = 0
    total_frames = 0
    total_capture_ms = 0.0
    total_inference_ms = 0.0
    hands_detected_frames = 0
    test_start = time.time()

    try:
        while time.time() - test_start < DURATION:
            # --- 采集耗时 ---
            t0 = time.perf_counter()
            ret, frame = cap.read()
            if not ret:
                print("[WARN] cap.read() 失败，跳过这一帧")
                continue
            t1 = time.perf_counter()

            # --- MediaPipe 推理耗时 ---
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, frame_idx)
            t2 = time.perf_counter()

            frame_idx += 1
            total_frames += 1
            total_capture_ms += (t1 - t0) * 1000
            total_inference_ms += (t2 - t1) * 1000

            if result.hand_landmarks:
                hands_detected_frames += 1

    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")

    elapsed = time.time() - test_start

    cap.release()
    landmarker.close()

    # 打印指标
    avg_capture = total_capture_ms / total_frames if total_frames else 0
    avg_inference = total_inference_ms / total_frames if total_frames else 0
    fps_actual = total_frames / elapsed if elapsed > 0 else 0

    print(f"  总帧数:        {total_frames}")
    print(f"  耗时:           {elapsed:.1f}s")
    print(f"  实际 FPS:       {fps_actual:.1f}")
    print(f"  平均采集耗时:   {avg_capture:.1f} ms")
    print(f"  平均推理耗时:   {avg_inference:.1f} ms  ← MediaPipe 关键指标")
    print(f"  总延迟/帧:      {avg_capture + avg_inference:.1f} ms")
    print(f"  检测到手帧数:   {hands_detected_frames} / {total_frames} "
          f"({100*hands_detected_frames/max(total_frames,1):.1f}%)")

    return {
        "width": int(actual_w),
        "height": int(actual_h),
        "total_frames": total_frames,
        "fps": round(fps_actual, 1),
        "inference_ms": round(avg_inference, 1),
        "total_ms": round(avg_capture + avg_inference, 1),
        "hands_ratio": round(100 * hands_detected_frames / max(total_frames, 1), 1),
    }

# ── 主流程 ────────────────────────────────────────────
def main():
    print("╔══════════════════════════════════════════════════╗")
    print("║   Pi 5 MediaPipe Hands 基准测试                  ║")
    print("║   模型: HandLandmarker  (hand_landmarker.task)   ║")
    print("╚══════════════════════════════════════════════════╝")

    # 快速测一下摄像头能不能打开
    cap = cv2.VideoCapture(CAM_INDEX)
    if not cap.isOpened():
        print(f"\n[ERR] 无法打开摄像头 index={CAM_INDEX}")
        print("      尝试: 1) 确认排线插好  2) 改脚本顶部 CAM_INDEX")
        sys.exit(1)
    cap.release()

    results = []
    for w, h in RESOLUTIONS:
        r = bench_one_resolution(w, h)
        results.append(r)

    # ── 判定 ──────────────────────────────────────────
    print(f"\n{'='*55}")
    print("判定结论")
    print(f"{'='*55}")

    for r in results:
        fps = r["fps"]
        inf_ms = r["inference_ms"]
        print(f"\n  {r['width']}×{r['height']}:")
        if fps >= 25:
            print(f"    ✅ 绿灯 — {fps:.0f} FPS，足以支撑实时手势识别")
        elif fps >= 15:
            print(f"    🟡 黄灯 — {fps:.0f} FPS，可用但时间分辨率偏低")
        else:
            print(f"    🔴 红灯 — {fps:.0f} FPS，建议回退到 PC 处理")

    print(f"\n  推理耗时: {inf_ms:.1f} ms/帧")
    if inf_ms < 33:
        print("  → 低于 33ms (30FPS 窗口)，Pi 处理 MediaPipe 完全够用")
    elif inf_ms < 50:
        print("  → 33-50ms，可维持 20+ FPS，考虑降分辨率或用 PC")
    else:
        print("  → >50ms，建议将 MediaPipe 移到 PC 处理")

    print(f"\n[EOF] — 把以上结果发回给模型负责人即可\n")

if __name__ == "__main__":
    main()
