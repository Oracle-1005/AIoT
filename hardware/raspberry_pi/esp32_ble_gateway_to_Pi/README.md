# ESP32 BLE 网关到树莓派 UDP 接收器

本目录提供 Pi 端 UDP 接收器，用于接收 ESP32 网关发来的 micro:bit 原始数据包，并输出与原 `microbit_receiver.app` 基本一致的 JSON Lines。

## 输入与输出

输入：

```text
ESP32 UDP gateway frame on 0.0.0.0:17778
```

输出：

```json
{"type":"microbit_sensor_state","source":"right","message_type":1,"hand":1,"sample_sequence":9693,"device_timestamp_ms":970210,"pi_rx_monotonic_ns":2223507067128,"raw":{"ax_mg":-24,"ay_mg":744,"az_mg":-680,"pitch_deg":47,"roll_deg":-2},"time_alignment":null,"sequence_status":"first_sample","missing_sample_count":0,"device_restarted":false,"transport":"esp32_udp_gateway","gateway":{"source_ip":"192.168.43.50","source_port":49152,"gateway_sequence":123,"esp_rx_micros":456789,"conn_index":1,"ble_rssi":-42,"flags":0}}
```

`pi_rx_monotonic_ns` 表示树莓派收到 UDP 包的单调时钟时间。ESP32 侧 BLE Notify 到达时间保存在 `gateway.esp_rx_micros`，用于调试网关延迟和丢包，不直接替代 Pi 的融合时间轴。

## 安装

建议继续使用 `camera_to_Pi/.venv` 这个虚拟环境，保持 camera、micro:bit、ESP32 gateway 在同一个 Python 环境下：

```bash
cd ~/aiot_conductor/project
source camera_to_Pi/.venv/bin/activate
python -m pip install -e microbit_to_Pi
python -m pip install -e hardware/raspberry_pi/esp32_ble_gateway_to_Pi
```

如果仓库没有同步到 `~/aiot_conductor/project/hardware/...`，把本目录同步到 Pi 后按实际路径安装即可。

## 配置

```bash
cd ~/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
cp config.example.json config.json
```

默认配置：

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 17778,
  "allowed_hands": ["left", "right"],
  "event_dedup_ttl_seconds": 10.0,
  "emit_gateway_metadata": true
}
```

## 命令行验证

先启动 Pi 端接收：

```bash
cd ~/aiot_conductor/project
camera_to_Pi/.venv/bin/python -m esp32_gateway_receiver.app \
  --config hardware/raspberry_pi/esp32_ble_gateway_to_Pi/config.json \
  --log-level INFO
```

然后给 ESP32 上电。正常时终端会持续输出 `microbit_sensor_state` 和 `microbit_control_event` JSON Lines。

没有 ESP32 时，也可以先从另一终端发一帧模拟 UDP 包验证 receiver：

```bash
python hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/send_demo_gateway_frame.py \
  --host 127.0.0.1 \
  --port 17778 \
  --hand left
```

## 接入浏览器预览

现有 `live_preview_server.py` 已支持替换 receiver 模块。启动 ESP32 UDP 网关预览：

```bash
cd ~/aiot_conductor/project
camera_to_Pi/.venv/bin/python \
  hardware/microbit/microbit_to_pi/tools/live_preview_server.py \
  --receiver-dir ~/aiot_conductor/project \
  --config hardware/raspberry_pi/esp32_ble_gateway_to_Pi/config.json \
  --python ~/aiot_conductor/project/camera_to_Pi/.venv/bin/python \
  --receiver-module esp32_gateway_receiver.app \
  --host 0.0.0.0 \
  --port 8787
```

电脑浏览器打开：

```text
http://192.168.43.221:8787/
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://192.168.43.221:8787/health
```

## 为什么比 Pi 直接连 BLE 稳定

原链路中，树莓派板载 Wi-Fi 和 BLE 共用 2.4 GHz 无线资源，同时 BlueZ 要维护两个 micro:bit GATT 连接，容易出现 `le-connection-abort-by-local`。ESP32 网关把 BLE central 角色移出 Pi，Pi 只收 UDP，camera、MediaPipe 和融合逻辑不再和 BlueZ 抢状态。

这个方案仍保留 micro:bit BLE，所以它不是无限可靠。若未来仍不满足实时性，应进一步改为 `ESP32 + IMU` 直接采集，或者用 ESP-NOW/UDP 发送姿态数据。
