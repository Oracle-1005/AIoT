# 正式融合链路摄像头与 MediaPipe 调优说明

**更新时间**：2026-07-24  
**适用范围**：`pi-fusion.service` 正式链路与 `http://<Pi-IP>:8790/` 联合预览

## 1. 当前实现

正式链路只打开一次 Pi Camera：

```text
Picamera2 -> MediaPipe HandLandmarker -> CameraSensor
           -> 原始关键点 -> fusion_pipeline -> TCP:9000 -> PC backend
           -> 短时保持关键点 -> 8790 视频叠加（仅预览）
```

相关文件：

| 文件 | 作用 |
| --- | --- |
| `hardware/sensors/camera.py` | Picamera2、MediaPipe、关键点平滑、检出统计和预览短时保持 |
| `hardware/fusion_pipeline/camera_adapter.py` | 将摄像头帧转换为融合管线输入和状态 |
| `hardware/fusion_pipeline/config.yaml` | 摄像头分辨率、帧率、颜色格式和 MediaPipe 阈值 |
| `hardware/fusion_pipeline/preview_server.py` | `8790` 视频与检测指标页面 |

## 2. 推荐配置

```yaml
camera:
  width: 640
  height: 480
  fps: 30
  pixel_format: "BGR888"
  max_hands: 2
  min_hand_detection_confidence: 0.35
  min_hand_presence_confidence: 0.35
  min_tracking_confidence: 0.40
  max_missing_frames: 4
  detection_window_seconds: 5.0
```

### 颜色格式

Picamera2/libcamera 的格式名称与 NumPy 数组内的通道排列容易混淆。当前使用 `BGR888`，`capture_array()` 得到的数组按 `[R, G, B]` 交给 MediaPipe `SRGB`，避免红蓝通道颠倒。

不要只修改 `pixel_format` 而跳过 `CameraSensor._to_rgb_array()`；正式链路保证进入 MediaPipe、预览 JPEG 和可选视频流回调的数组始终为 RGB。

### 分辨率与帧率

当前正式配置为 `640x480 @ 30 FPS`。摄像头采集与 MediaPipe 当前在同一线程串行执行，因此配置帧率不是最终输出帧率：实机通常输出约 `16~17 Hz`。曾测试 `960x540 @ 20 FPS`，单帧处理延迟约为 `89 ms`、实际输出约 `11.3 Hz`，不利于快速指挥动作。

当手在 1~1.5 米距离过小时，可以短暂测试：

```yaml
width: 960
height: 540
fps: 30
```

但只有在处理延迟不持续超过 `80 ms`、实际帧率仍满足动作需求时才保留高分辨率。不要优先降低检测阈值来解决运动模糊；应先改善照明、站位和摄像头清晰度。

## 3. 原始数据与预览保持

`max_missing_frames: 4` 只用于视频骨架连续显示：

- 本帧真实检测到的骨架：`interpolated=false`、`missing_frames=0`；
- 短时沿用上一次骨架：`interpolated=true`、`missing_frames=1..4`；
- 超过 4 帧仍未重新检测：预览骨架消失。

正式发送给 PC 的 `fused_frame.camera.hands` 始终来自本帧原始 MediaPipe 结果。漏检帧仍发送 `hands=[]`，不会把预览保持数据伪装成训练样本。

PC 同时会收到质量辅助字段：

```json
"detection_quality": {
  "hand_detection_rate_5s": 0.92,
  "consecutive_missed_frames": 0,
  "preview_interpolated_hands": 0
}
```

训练样本可以用前两个字段做质量筛选；`preview_interpolated_hands` 只用于确认当时网页骨架是否处于显示保持状态。

手对象中的：

```text
confidence
handedness_confidence
```

表示 MediaPipe 对 `left/right` 分类的置信度，不是手部检测或存在置信度。`confidence_type` 固定为 `handedness`。

## 4. 8790 页面指标

| 指标 | 含义 | 建议观察方式 |
| --- | --- | --- |
| `raw hands` | 当前帧真实检测到的手数 | 双手入画时应多数为 2 |
| `5s detection` | 最近约 5 秒至少检测到一只手的帧比例 | 手持续入画时越接近 100% 越好 |
| `miss streak` | 当前连续完全漏检帧数 | 经常超过 4 表示真实检测不稳定 |
| `preview held` | 当前视频叠加中沿用上次结果的手数 | 偶尔为 1/2 正常，长期非零需排查 |
| `latency` | 单帧采集、MediaPipe 和特征处理耗时 | 应低于单帧周期附近，且不持续上升 |

检测改善验收建议：

1. 一只手保持入画 30 秒，`5s detection` 稳定在 85% 以上。
2. 双手完成九动作，骨架不应频繁连续消失超过 4 帧。
3. `dropped_capture_frames` 不持续快速增加。
4. PC 后端的 `fused_frame` 和 `status` 计数持续增加。

## 5. 现场条件

- 双手完整入画，手掌宽度尽量达到画面宽度的 10% 以上。
- 避免窗户或强灯位于人物背后。
- 增加正面漫射照明，快速下拍时尤其需要减少运动模糊。
- 两手交叉后如左右手标签交换，先分开双手，让追踪器重新建立稳定目标。
- 镜头污渍、失焦或手部靠近画面边缘都会降低检出率。

## 6. 修改配置后的验证

```bash
cd ~/aiot_conductor/project
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -n 40 --no-pager
```

日志应包含：

```text
Picamera2 initialized: 640x480 @ 30 FPS, format=BGR888
MediaPipe HandLandmarker initialized
Camera started.
```

在 PC 浏览器打开：

```text
http://192.168.43.221:8790/
```

然后查看后端链路：

```powershell
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 15 --require status --require fused_frame
```

## 7. 常见问题

| 现象 | 判断 | 处理 |
| --- | --- | --- |
| 视频正常但 `raw hands=0` | MediaPipe 没有检出 | 检查 RGB 通道、照明、距离和阈值 |
| 骨架短暂存在但 JSON 中 `hands=[]` | 预览正在短时保持 | 查看 `preview held`，属于预期行为 |
| `5s detection` 很低且 `miss streak` 很高 | 持续真实漏检 | 增加照明、靠近摄像头，再考虑降阈值 |
| 视频卡顿、延迟和丢帧同时增加 | Pi 处理压力过高 | 降到 `640x480 @ 20 FPS` 或提高 JPEG 跳帧数 |
| 左右手标签偶尔交换 | 双手交叉或 handedness 不稳定 | 分开双手重新进入画面，后续模型按空间连续性校验 |
