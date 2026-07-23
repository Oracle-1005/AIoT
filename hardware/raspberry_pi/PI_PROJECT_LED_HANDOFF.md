# Raspberry Pi 项目配置与 LED 接入交接文档

本文档记录 2026-07-23 树莓派 `AG1` 上当前可运行项目状态，用于后续接入 WS2812B LED 灯带/灯板控制。

## 1. 当前结论

当前树莓派项目已经统一为一条正式融合链路：

```text
micro:bit L/R -> BLE 广播 -> ESP32 -> UDP:17778 -> Raspberry Pi
Pi Camera -> Picamera2 + MediaPipe -> Raspberry Pi
Raspberry Pi fusion_pipeline -> TCP:9000 -> PC backend
```

后续 LED 控制建议不要直接消费 BLE、ESP32 UDP 或摄像头底层对象，而是消费已经整理好的 fusion 输出或 PC 下行命令：

- `fused_frame`：包含左右 micro:bit 加速度/姿态、摄像头手部关键点和时间对齐信息，适合作为模型输入和 LED 强度/分区控制输入。
- `control_event`：micro:bit 按键快速通道，适合触发暂停、继续、风格切换、紧急停止等动作。
- `status`：链路健康状态，只用于监控，不作为训练样本。
- 后续 PC -> Pi 下行的 `led_command`：建议作为正式 LED 控制入口。

## 2. 树莓派目录状态

项目根目录：

```bash
/home/ag1_client/aiot_conductor/project
```

当前主要目录：

```text
camera_to_Pi/
  main.py
  config.json
  camera_to_pi/
  models/hand_landmarker.task
  visual_verify.py
  .venv/

hardware/
  fusion_pipeline/
    main.py
    config.yaml
    gateway_adapter.py
    camera_adapter.py
    fusion_engine.py
    tcp_client.py
    pi-fusion.service
  microbit/microbit_to_pi/
    main.ts
    pxt.json
    tools/live_preview_server.py
    MICROBIT_VISUAL_VERIFICATION.md
  raspberry_pi/esp32_ble_gateway_to_Pi/
    config.example.json
    esp32_gateway_receiver/
    tools/send_demo_gateway_frame.py
  raspberry_pi_iot/led/
    controller.py
```

已清理项目源码目录中的 `__pycache__` 运行缓存。虚拟环境内部缓存没有清理，属于 Python 环境正常内容。

## 3. 虚拟环境

统一虚拟环境：

```bash
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv
```

Python：

```text
Python 3.13.5
```

`pyvenv.cfg` 关键状态：

```text
include-system-site-packages = true
executable = /usr/bin/python3.13
```

这说明 `.venv` 会看到系统 site-packages，因此 `pip list` 中会出现很多 Raspberry Pi OS 自带包。不要直接把完整 `pip freeze` 当作项目最小依赖。

当前关键依赖导入状态：

| 模块 | 状态 | 用途 |
| --- | --- | --- |
| `picamera2` | OK | Pi camera 采集 |
| `mediapipe` | OK | 手部关键点识别 |
| `cv2` | OK | 图像处理 |
| `bleak` | OK | 旧 BLE 直连实验依赖，当前正式链路不依赖 |
| `microbit_receiver` | OK | micro:bit 二进制协议解析与 JSON Lines 输出 |
| `esp32_gateway_receiver` | OK | ESP32 UDP 网关接收 |
| `yaml` | OK | 主项目 YAML 配置 |
| `rpi_ws281x` | 缺失 | WS2812B LED 控制，LED 接入前需要安装 |

已安装的项目 editable 包：

```text
microbit-to-pi-receiver==0.1.0
esp32-microbit-gateway-receiver==0.1.0
```

LED 接入前建议补装：

```bash
cd /home/ag1_client/aiot_conductor/project
camera_to_Pi/.venv/bin/python -m pip install rpi-ws281x
```

WS2812B 使用 `rpi_ws281x` 时通常需要 root 或合适的 GPIO/DMA 权限；首次硬件测试建议用：

```bash
sudo /home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python <led_test_script.py>
```

## 4. 当前运行中的服务

正式服务：

```text
pi-fusion.service
```

`pi-fusion.service` 会同时占用：

- UDP `17778`：接收 ESP32 网关数据；
- Pi Camera：采集图像并运行 MediaPipe。

因此 micro:bit 预览 `8787` 和摄像头预览 `8765` 都不能与 `pi-fusion.service` 同时运行。

检查进程：

```bash
systemctl is-active pi-fusion
ss -ltnup | grep -E '(:17778|:8765|:8787)' || true
ps -ef | grep -E 'pi-fusion|visual_verify|live_preview_server|esp32_gateway_receiver' | grep -v grep
```

停止正式服务：

```bash
sudo systemctl stop pi-fusion
```

停止预览服务：

```bash
kill "$(cat /tmp/camera_visual_verify.pid)" 2>/dev/null || true
kill "$(cat /tmp/microbit_esp32_preview_8787.pid)" 2>/dev/null || true
pkill -f visual_verify.py 2>/dev/null || true
pkill -f live_preview_server.py 2>/dev/null || true
pkill -f esp32_gateway_receiver.app 2>/dev/null || true
```

## 5. Camera 配置

配置文件：

```bash
/home/ag1_client/aiot_conductor/project/camera_to_Pi/config.json
```

当前关键值：

```json
{
  "camera": {
    "width": 640,
    "height": 480,
    "fps": 30.0,
    "pixel_format": "RGB888",
    "queue_size": 2,
    "buffer_count": 4,
    "warmup_seconds": 1.0
  },
  "detector": {
    "model_path": "models/hand_landmarker.task",
    "num_hands": 2,
    "min_hand_detection_confidence": 0.5,
    "min_hand_presence_confidence": 0.5,
    "min_tracking_confidence": 0.5,
    "input_array_order": "BGR"
  },
  "quality": {
    "ema_alpha": 0.45,
    "max_missing_frames": 2,
    "hold_last_on_missing": true,
    "reject_large_jumps": true
  }
}
```

验证命令：

```bash
cd /home/ag1_client/aiot_conductor/project/camera_to_Pi
.venv/bin/python main.py --config config.json --max-frames 5 --output /tmp/camera_verify.jsonl --log-level INFO
```

输出类型：

```text
camera_landmark_frame
```

用于 LED 时，建议只使用 `hands_detected`、`hands[]`、`pi_aligned_timestamp_ns` 和质量过滤后的关键点，不要让 LED 控制直接依赖原始 camera frame。

## 6. micro:bit 直接 BLE 配置（历史方案）

本节只保留为旧方案记录。Pi 直接 BLE 双连接仍不稳定，典型错误是 `le-connection-abort-by-local`。当前正式链路应使用 ESP32 广播网关，不应在 LED 演示中重新启用 Pi 直连两块 micro:bit。

配置文件：

```bash
/home/ag1_client/aiot_conductor/project/microbit_to_Pi/config.json
```

当前正式配置：

```json
{
  "tx_characteristic_uuid": "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
  "sensor_queue_size": 512,
  "event_dedup_ttl_seconds": 10.0,
  "devices": [
    {"hand": "left", "address": "E7:C8:C1:AF:21:46"},
    {"hand": "right", "address": "FD:15:9A:47:7F:8F"}
  ]
}
```

运行：

```bash
cd /home/ag1_client/aiot_conductor/project/microbit_to_Pi
../camera_to_Pi/.venv/bin/python -m microbit_receiver.app --config config.json --log-level INFO
```

## 7. ESP32 BLE-to-Wi-Fi 网关配置

Pi 端配置文件：

```bash
/home/ag1_client/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi/config.example.json
```

当前配置：

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 17778,
  "allowed_hands": ["left", "right"],
  "event_dedup_ttl_seconds": 10.0,
  "emit_gateway_metadata": true
}
```

启动 UDP receiver：

```bash
cd /home/ag1_client/aiot_conductor/project
camera_to_Pi/.venv/bin/python -m esp32_gateway_receiver.app \
  --config hardware/raspberry_pi/esp32_ble_gateway_to_Pi/config.example.json \
  --log-level INFO
```

无 ESP32 时模拟验证：

```bash
camera_to_Pi/.venv/bin/python \
  hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/send_demo_gateway_frame.py \
  --host 127.0.0.1 \
  --port 17778 \
  --hand right
```

已在 Pi 上验证：模拟 UDP 包可输出 `microbit_sensor_state`，且包含：

```text
transport = "esp32_udp_gateway"
gateway.source_ip
gateway.gateway_sequence
gateway.esp_rx_micros
gateway.ble_rssi
```

## 8. 浏览器预览

ESP32 UDP 网关预览：

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
cd /home/ag1_client/aiot_conductor/project
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

电脑端打开：

```text
http://192.168.43.221:8787/
http://AG1:8787/
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://192.168.43.221:8787/health
```

## 9. LED 控制现状

仓库中已有 LED 控制器：

```text
hardware/raspberry_pi_iot/led/controller.py
```

当前设计：

- 控制 WS2812B。
- 默认 GPIO：`18`，物理引脚 12。
- 默认 2 个 panel。
- 每个 panel 256 LEDs。
- 总计 512 LEDs。
- panel 0 映射左手，panel 1 映射右手。
- 默认亮度上限：`0.25`。

主项目配置里已有 LED 段：

```yaml
led:
  enabled: false
  gpio: 18
  panel_count: 2
  led_per_panel: 256
  brightness_limit: 0.25
  refresh_hz: 50
  dma_channel: 10
  pwm_freq_hz: 800000
```

注意事项：

- 当前 Pi 虚拟环境未安装 `rpi_ws281x`。
- `GPIO18` 使用 PWM/DMA，可能与音频或其它 PWM 功能冲突。
- 首次点亮必须限制亮度和供电电流，建议保持 `brightness_limit <= 0.25`。
- LED 电源地必须与树莓派 GND 共地。
- 数据线建议串联 330-470 欧姆电阻，长线建议加电平转换。

## 10. LED 接入推荐路径

推荐分三步接入，不要一开始就把 LED、camera、BLE、PC transport 全部串起来。

### 第一步：LED 独立硬件验证

目标：只验证 `rpi_ws281x`、GPIO18、供电和灯带方向。

建议新建一个最小脚本，调用 `LedController.clear()`、`show_beat()`、`update()`，不要接 camera/microbit。

### 第二步：接 fusion 输出或 PC 下行命令

目标：用 `fused_frame.microbits[]` 和 `control_event.payload.event.type` 驱动亮度/颜色。

建议映射：

```text
left microbit  -> panel 0
right microbit -> panel 1
motion intensity = abs(norm(ax_mg, ay_mg, az_mg) - 1000 mg)
tilt hue = pitch_deg / roll_deg
control_event stop/cutoff -> clear/off
```

### 第三步：接 PC 后端 LED 下行

目标：PC 后端通过 `/api/pi/send` 向 Pi 发送 `led_command`，Pi 侧 LED 服务只消费下行命令，不直接耦合模型、摄像头或 ESP32 接收器。

建议输出字段：

```json
{
  "type": "led_control_frame",
  "pi_aligned_timestamp_ns": 123,
  "left": {"intensity": 0.4, "confidence": 0.9},
  "right": {"intensity": 0.6, "confidence": 0.8},
  "global": {"bpm": 120, "mode": "breathing"}
}
```

这样 LED 不需要理解 camera 关键点细节，也不需要关心 BLE/ESP32 传输差异。

## 11. 当前冗余与整理建议

已经处理：

- 清理了源码目录下的 `__pycache__`。
- ESP32 UDP receiver 和 microbit receiver 已安装到同一个 `camera_to_Pi/.venv`，避免多虚拟环境割裂。

暂不建议删除：

- `microbit_to_Pi/*.egg-info` 和 `esp32_*egg-info`：editable 安装会生成，删除后不影响源码但会让安装状态不清晰。
- `.venv` 内部缓存：属于虚拟环境内容。

建议后续整理：

1. LED 接入前安装 `rpi_ws281x`，并增加一个独立 `led_smoke_test.py`。
2. 在 Pi 侧实现 `led_command` 下行消费与 LED 控制器调用。
3. 正式运行时只启动 `pi-fusion.service`，不要同时启动 `8765` 或 `8787` 预览。
4. 如果需要采集训练数据，优先从 PC 后端 `pi_messages` 中导出 `fused_frame`，不要从多个预览服务分别取样。

## 12. 最小恢复命令

重新安装当前 Python 项目包：

```bash
cd /home/ag1_client/aiot_conductor/project
camera_to_Pi/.venv/bin/python -m pip install -e microbit_to_Pi
camera_to_Pi/.venv/bin/python -m pip install -e hardware/raspberry_pi/esp32_ble_gateway_to_Pi
```

验证 camera：

```bash
cd /home/ag1_client/aiot_conductor/project/camera_to_Pi
.venv/bin/python main.py --config config.json --max-frames 5 --output /tmp/camera_verify.jsonl --log-level INFO
```

验证 ESP32 UDP receiver：

```bash
cd /home/ag1_client/aiot_conductor/project
(timeout 8s camera_to_Pi/.venv/bin/python -m esp32_gateway_receiver.app \
  --config hardware/raspberry_pi/esp32_ble_gateway_to_Pi/config.example.json \
  --log-level INFO > /tmp/esp32_udp_receiver.jsonl 2>/tmp/esp32_udp_receiver.log) &
sleep 2
camera_to_Pi/.venv/bin/python hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/send_demo_gateway_frame.py \
  --host 127.0.0.1 --port 17778 --hand right
cat /tmp/esp32_udp_receiver.jsonl
```
