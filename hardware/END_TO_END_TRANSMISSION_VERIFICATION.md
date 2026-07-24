# 端到端传输验证流程

**日期**: 2026-07-23

本文档用于验证完整链路：

```text
micro:bit L/R -> ESP32 -> Raspberry Pi -> PC backend
Pi Camera -> Raspberry Pi -> PC backend
```

验证目标不是只确认程序能启动，而是确认 PC 后端能持续收到：

- `status`
- `fused_frame`
- `control_event`

## 1. 验证前提

确认硬件状态：

- PC、树莓派、ESP32 在同一局域网。
- PC 当前后端 IP 为 `192.168.43.209`。
- 树莓派 IP 为 `192.168.43.221`，或可用主机名 `AG1`。
- ESP32 已烧录 BLE-to-Wi-Fi gateway 固件，并配置向树莓派 `17778` 发送 UDP。
- 两块 micro:bit v2 已烧录广播固件，分别显示 `L` 和 `R`。
- Pi Camera 已连接并能被 `rpicam-hello --list-cameras` 识别。

树莓派统一项目根目录：

```text
/home/ag1_client/aiot_conductor/project
```

树莓派统一 Python 环境：

```text
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python
```

## 2. 不要同时运行的程序

正式融合传输验证时，不能同时运行两个预览服务：

| 程序 | 端口 / 资源 | 原因 |
| --- | --- | --- |
| 摄像头预览 `visual_verify.py` | HTTP `8765` + Pi Camera | 会占用摄像头 |
| micro:bit ESP32 预览 | UDP `17778` + HTTP `8787` | 会占用 ESP32 UDP 接收端口 |
| `pi-fusion.service` | UDP `17778` + Pi Camera | 正式融合程序 |

如果之前开过预览，先在树莓派执行：

```bash
kill "$(cat /tmp/camera_visual_verify.pid)" 2>/dev/null || true
kill "$(cat /tmp/microbit_esp32_preview_8787.pid)" 2>/dev/null || true
pkill -f visual_verify.py 2>/dev/null || true
pkill -f live_preview_server.py 2>/dev/null || true
pkill -f esp32_gateway_receiver.app 2>/dev/null || true
```

确认关键端口未被预览占用：

```bash
ss -ltnup | grep -E '(:8765|:8787|:17778)' || true
```

正式启动 fusion 前，`17778` 不应被其他 Python 进程占用。

## 3. 启动 PC 后端

在 PC PowerShell 中运行：

```powershell
cd G:\code\AIoT\AIoT
powershell -ExecutionPolicy Bypass -File backend\tools\start_backend.ps1 -Restart
```

后端应启动：

- Flask HTTP: `0.0.0.0:5000`
- Pi TCP gateway: `0.0.0.0:9000`
- 日志文件：`backend\logs\backend_stdout.log`、`backend\logs\backend_stderr.log`

如果需要前台观察日志，也可以运行：

```powershell
backend\.venv\Scripts\python.exe backend\app.py
```

另开一个 PowerShell 检查端口：

```powershell
netstat -ano | Select-String ':5000|:9000'
```

浏览器或 PowerShell 检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5000/api/status
```

此时 `pi_gateway.running` 应为 `true`。在树莓派 fusion 启动前，`pi_gateway.connected` 可以是 `false`。

## 4. 检查树莓派配置

SSH 到树莓派：

```powershell
ssh ag1_client@192.168.43.221
```

检查目录和 Python：

```bash
cd /home/ag1_client/aiot_conductor/project
camera_to_Pi/.venv/bin/python --version
```

检查融合配置：

```bash
grep -A8 '^tcp:' hardware/fusion_pipeline/config.yaml
grep -A6 '^gateway:' hardware/fusion_pipeline/config.yaml
```

预期包含：

```yaml
tcp:
  host: "192.168.43.209"
  port: 9000

gateway:
  listen_host: "0.0.0.0"
  listen_port: 17778
```

如果 PC IP 变化，修改：

```bash
nano hardware/fusion_pipeline/config.yaml
```

## 5. 启动正式融合传输

推荐先用前台方式启动，便于观察日志：

```bash
cd /home/ag1_client/aiot_conductor/project/hardware/fusion_pipeline
/home/ag1_client/aiot_conductor/project/camera_to_Pi/.venv/bin/python main.py --config config.yaml
```

正常日志应包含：

```text
GatewayAdapter listening on 0.0.0.0:17778
Camera started.
Fusion Pipeline started
Connected to 192.168.43.209:9000
```

如果前台运行稳定，再改用 systemd：

```bash
sudo systemctl start pi-fusion
sudo systemctl status pi-fusion --no-pager
sudo journalctl -u pi-fusion -f
```

停止 systemd：

```bash
sudo systemctl stop pi-fusion
```

## 6. 在 PC 后端验证数据

后端和 Pi fusion 都启动后，在 PC 另一个 PowerShell 中运行：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

观察输出：

```text
gateway_running=yes
pi_connected=yes
counts={'fused_frame': ..., 'control_event': ..., 'status': ...}
delta={'fused_frame': ..., 'control_event': ..., 'status': ...}
```

最低通过标准：

- `gateway_running=yes`
- `pi_connected=yes`
- `status` 计数持续增加

摄像头融合通过标准：

- `fused_frame` 计数持续增加
- `camera_fps` 有稳定数值
- `camera_hands` 在手进入画面时变为 `1` 或 `2`

micro:bit 通过标准：

- `left_age_ms` 和 `right_age_ms` 周期性刷新
- `left_rssi` 和 `right_rssi` 有数值
- `left_seq` 和 `right_seq` 逐步变化

按键事件通过标准：

- 按左手或右手 micro:bit 按键后，`control_event` 计数增加
- `last_control_event` 显示 `resume`、`cutoff`、`style_switch` 或 `stop`

严格验证命令：

```powershell
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 60 --require status --require fused_frame --require control_event
```

这个命令要求 60 秒内三类消息都增加。运行期间需要至少按一次 micro:bit 按键，否则 `control_event` 不会增加。

### 6.1 最近一次真实验证记录

2026-07-24 实测：

- PC 后端 IP：`192.168.43.209`
- 树莓派 IP：`192.168.43.221`
- 验证命令：`backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30 --interval 1 --require status --require fused_frame`
- 结果：`PASS`
- 30 秒内新增：`fused_frame=472`，`status=29`
- 后端接收快照：`hardware/live_test_records/pi_backend_live_final_20260724_133045.json`

## 7. 后端 REST 手动检查

PC 浏览器打开：

```text
http://127.0.0.1:5000/api/status
http://127.0.0.1:5000/api/pi/status
http://127.0.0.1:5000/api/sensors/live
http://127.0.0.1:5000/api/pi/messages?limit=20
```

重点字段：

```text
/api/status
  pi_gateway.running
  pi_gateway.connected
  pi_gateway.received_messages

/api/pi/status
  runtime.message_counts.status
  runtime.message_counts.fused_frame
  runtime.message_counts.control_event
  runtime.last_control_event

/api/sensors/live
  camera
  microbit_left
  microbit_right
```

## 8. 独立预览方式

正式融合验证失败时，可以拆开验证 micro:bit 和摄像头。

### 8.1 micro:bit ESP32 预览

该预览会占用 UDP `17778`，不能和 `pi-fusion.service` 同时运行。

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
cd /home/ag1_client/aiot_conductor/project
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

PC 浏览器打开：

```text
http://192.168.43.221:8787/
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

后台启动：

```bash
cd /home/ag1_client/aiot_conductor/project
nohup bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh > /tmp/microbit_esp32_preview.log 2>&1 &
echo $! > /tmp/microbit_esp32_preview_8787.pid
```

停止：

```bash
kill "$(cat /tmp/microbit_esp32_preview_8787.pid)"
```

### 8.2 摄像头预览

摄像头预览方式没有变化，但会占用 Pi Camera，不能和 `pi-fusion.service` 同时运行。

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
cd /home/ag1_client/aiot_conductor/project/camera_to_Pi
source .venv/bin/activate
python visual_verify.py --config config.json --host 0.0.0.0 --port 8765
```

PC 浏览器打开：

```text
http://192.168.43.221:8765/
```

健康检查：

```bash
curl http://127.0.0.1:8765/status
```

如果以前台方式启动，按 `Ctrl+C` 关闭预览。若以前后台方式启动，或不确定是否仍有残留进程，执行：

```bash
kill "$(cat /tmp/camera_visual_verify.pid)" 2>/dev/null || true
pkill -f visual_verify.py 2>/dev/null || true
ss -ltnp | grep ':8765' || echo "camera preview stopped"
```

确认看到 `camera preview stopped` 后，再启动 `pi-fusion.service`。

后台启动：

```bash
cd /home/ag1_client/aiot_conductor/project/camera_to_Pi
nohup .venv/bin/python visual_verify.py --config config.json --host 0.0.0.0 --port 8765 > /tmp/camera_visual_verify.log 2>&1 &
echo $! > /tmp/camera_visual_verify.pid
```

停止：

```bash
kill "$(cat /tmp/camera_visual_verify.pid)"
```

## 9. 预览方式是否发生变化

摄像头预览：

- 命令基本不变。
- 当前仍从 `/home/ag1_client/aiot_conductor/project/camera_to_Pi` 启动。
- 仍使用 `visual_verify.py` 和端口 `8765`。
- 变化点是正式融合服务也会使用同一个摄像头和同一个 `.venv`，因此预览和 fusion 不能同时运行。

micro:bit 预览：

- 已发生变化。
- 旧方案是树莓派通过 BLE GATT 直接连接两块 micro:bit。
- 当前推荐方案是 micro:bit BLE 广播，ESP32 扫描并通过 UDP 转发给树莓派。
- 当前预览入口是：

```bash
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

- 当前页面仍是 `8787`，但它显示的是 ESP32 UDP 网关接收流，不再是树莓派直连 BLE 流。

## 10. 常见失败判断

| 现象 | 判断 | 处理 |
| --- | --- | --- |
| `pi_connected=no` | Pi 没有连上 PC TCP `9000` | 检查 PC 后端是否启动、`tcp.host` 是否为 PC 当前 IP |
| `status` 不增加 | Pi fusion 没有成功运行或 TCP 未发送 | 看 `journalctl -u pi-fusion -f` |
| `fused_frame` 不增加 | 摄像头未启动或被预览占用 | 停止 `8765` 预览，检查 `rpicam-hello --list-cameras` |
| `left/right_age_ms` 持续很大 | ESP32 没收到对应 micro:bit 或 UDP 未到 Pi | 先运行 micro:bit ESP32 预览 |
| `control_event` 不增加 | 没有按键事件或被去重 | 按一次 micro:bit 按键，观察 ESP32 预览页面 |
| fusion 报 `Address already in use` | `17778` 被预览占用 | 停止 micro:bit 预览 |
| fusion 报 camera busy | 摄像头被预览占用 | 停止摄像头预览 |
