"""
MediaPipe Hands 基础验证 (API 0.10.x)
- 摄像头 30 FPS 双手 21 关键点检测
- 按 Q 退出
"""
import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.vision import RunningMode
import time
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "hand_landmarker.task")

# 创建 HandLandmarker
options = vision.HandLandmarkerOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=RunningMode.VIDEO,
    num_hands=2,
    min_hand_detection_confidence=0.7,
    min_tracking_confidence=0.5
)
landmarker = vision.HandLandmarker.create_from_options(options)

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[ERR] 无法打开摄像头！")
    exit(1)

print("[OK] MediaPipe HandLandmarker 已加载")
print(f"[CAM] 摄像头: {cap.get(cv2.CAP_PROP_FRAME_WIDTH):.0f}×{cap.get(cv2.CAP_PROP_FRAME_HEIGHT):.0f}")
print("Press Q to quit\n")

frame_idx = 0
frame_count = 0
fps_start = time.time()
fps = 0

# 关键点连线定义 (21个点之间的连线)
HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),       # 拇指
    (0,5),(5,6),(6,7),(7,8),       # 食指
    (0,9),(9,10),(10,11),(11,12),  # 中指
    (0,13),(13,14),(14,15),(15,16),# 无名指
    (0,17),(17,18),(18,19),(19,20),# 小指
    (5,9),(9,13),(13,17)           # 手指间连接
]

COLORS = [(0,255,0),(0,0,255)]  # 左手绿, 右手红

while True:
    ret, frame = cap.read()
    if not ret:
        break

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect_for_video(mp_image, frame_idx)
    frame_idx += 1

    h, w, _ = frame.shape

    # 画手部关键点
    if result.hand_landmarks:
        for hi, landmarks in enumerate(result.hand_landmarks):
            color = COLORS[hi % 2]

            # 画连线
            for conn in HAND_CONNECTIONS:
                p1 = landmarks[conn[0]]
                p2 = landmarks[conn[1]]
                x1, y1 = int(p1.x * w), int(p1.y * h)
                x2, y2 = int(p2.x * w), int(p2.y * h)
                cv2.line(frame, (x1, y1), (x2, y2), color, 2)

            # 画关键点
            for lm in landmarks:
                cx, cy = int(lm.x * w), int(lm.y * h)
                cv2.circle(frame, (cx, cy), 4, color, -1)

            # 手腕处显示左右手标签
            wrist = landmarks[0]
            wx, wy = int(wrist.x * w), int(wrist.y * h)
            if result.handedness and hi < len(result.handedness):
                label = f"{result.handedness[hi][0].category_name} ({result.handedness[hi][0].score:.2f})"
                cv2.putText(frame, label, (wx - 30, wy - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)

    # FPS
    frame_count += 1
    if frame_count >= 30:
        elapsed = time.time() - fps_start
        fps = 30 / elapsed
        fps_start = time.time()
        frame_count = 0

    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(frame, f"Hands: {len(result.hand_landmarks or [])}", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    cv2.imshow("MediaPipe Hands — Press Q to quit", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
landmarker.close()
print("Bye")
