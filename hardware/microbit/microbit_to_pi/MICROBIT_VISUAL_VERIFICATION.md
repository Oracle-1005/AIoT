# micro:bit 到树莓派数据可视化验证说明

**日期**: 2026-07-23

当前推荐链路已经从“树莓派直接 BLE 连接两块 micro:bit”调整为：

```text
micro:bit L/R -> BLE advertising -> ESP32 -> UDP:17778 -> Raspberry Pi
```

旧的树莓派直连 BLE/GATT 方案连接不稳定，仅作为历史调试方案保留，不再作为正式预览方式。

## 1. 当前预览方式是否变化

已变化。

旧方式：

```text
Raspberry Pi -> BLE GATT connect -> micro:bit L/R
```

当前方式：

```text
micro:bit L/R -> BLE broadcast -> ESP32 scan -> UDP -> Raspberry Pi preview
```

变化原因：

- 两块 micro:bit 同时被树莓派通过 BLE GATT 连接时，BlueZ/Bleak 容易出现连接中断、服务发现失败和 `InProgress`。
- 广播方案不需要连接和配对，ESP32 只扫描广播包，稳定性更适合双 micro:bit 同时使用。
- 代价是 BLE 广播没有确认机制，偶发 `sequence_gap` 属于正常现象。

## 2. 文件位置

micro:bit 固件：

```text
hardware/microbit/microbit_to_pi/
  main.ts
  pxt.json
  README.md
```

ESP32 网关固件：

```text
hardware/esp32/microbit_ble_wifi_gateway/
```

树莓派 ESP32 UDP 接收器：

```text
hardware/raspberry_pi/esp32_ble_gateway_to_Pi/
```

浏览器预览页面：

```text
hardware/microbit/microbit_to_pi/tools/live_preview_server.py
```

## 3. 预览前提

- ESP32 已烧录 `microbit_ble_wifi_gateway` 固件。
- ESP32 已连接到与树莓派相同的 Wi-Fi。
- ESP32 固件中的 Pi 目标 IP 是当前树莓派 IP。
- 两块 micro:bit v2 已烧录广播固件。
- 左手 micro:bit 显示 `L`，右手 micro:bit 显示 `R`。
- 树莓派项目根目录为：

```text
/home/ag1_client/aiot_conductor/project
```

## 4. 启动 micro:bit ESP32 预览

该预览会占用 UDP `17778` 和网页端口 `8787`。启动前应停止正式融合服务：

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
```

在树莓派运行：

```bash
cd /home/ag1_client/aiot_conductor/project
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

PC 浏览器打开：

```text
http://192.168.43.221:8787/
```

如果树莓派 IP 改变：

```bash
hostname -I
```

然后用新的 IP 打开：

```text
http://<树莓派IP>:8787/
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

## 5. 后台启动和停止

后台启动：

```bash
cd /home/ag1_client/aiot_conductor/project
nohup bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh > /tmp/microbit_esp32_preview.log 2>&1 &
echo $! > /tmp/microbit_esp32_preview_8787.pid
```

查看日志：

```bash
tail -f /tmp/microbit_esp32_preview.log
```

停止：

```bash
kill "$(cat /tmp/microbit_esp32_preview_8787.pid)"
```

如果 PID 文件不存在：

```bash
ps -ef | grep -E 'live_preview_server|esp32_gateway_receiver.app' | grep -v grep
pkill -f live_preview_server.py
pkill -f esp32_gateway_receiver.app
```

## 6. 页面应观察到的结果

正常状态：

- 页面顶部显示 `live`。
- 左右两列分别显示 left 和 right，不再被最新到达的一侧抢占。
- 两侧 `sequence` 分别持续增长。
- `age` 周期性回落，不应持续增大。
- `rssi` 有数值，通常越接近 0 表示信号越强。
- 倾斜 micro:bit 时，pitch、roll、ax、ay、az 会变化。
- 按键后，“最近控制事件”区域会刷新。

状态样本可能出现：

```text
sequence_status = in_order
sequence_status = sequence_gap
```

短时间 `sequence_gap` 可以接受；如果持续大量出现，说明广播丢包较多。

## 7. 按键事件

左手：

| 操作 | event_code | candidate |
| --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `start_or_resume` |
| B 短按 | `B_SHORT_PRESS` | `pause` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` |

右手：

| 操作 | event_code | candidate |
| --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `style_switch` |
| B 长按 | `B_LONG_PRESS` | `emergency_stop` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` |

进入 PC 后端时，fusion 管线会把它们转换为后端接受的 `control_event`。

## 8. 端口冲突

micro:bit 预览和正式 fusion 不能同时运行：

| 程序 | 占用 |
| --- | --- |
| micro:bit ESP32 预览 | UDP `17778` + HTTP `8787` |
| `pi-fusion.service` | UDP `17778` + Pi Camera |

如果正式 fusion 启动时报 `Address already in use`，先停止 micro:bit 预览。

## 9. az_mg 如何理解

`az_mg` 是 micro:bit 板子 Z 轴方向的加速度，单位是 milli-g，并且包含重力。

它不是高度、速度或垂直位移。静止时三轴合成模长通常接近 `1000 mg`。如果板子平放，重力主要体现在某一个轴上，正负号取决于板子朝向和佩戴方向。

判断动作强度时应看：

```text
sqrt(ax_mg^2 + ay_mg^2 + az_mg^2)
```

相对 `1000 mg` 的偏离。若需要纯运动加速度，需要后续滤波或姿态估计先扣除重力分量。

## 10. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 页面打不开 | 预览服务未启动或 IP 错误 | 检查树莓派 `hostname -I` 和 8787 端口 |
| 页面打开但无数据 | ESP32 没有向 Pi 发 UDP | 检查 ESP32 Wi-Fi 和目标 Pi IP |
| 只有一侧有数据 | 另一块 micro:bit 未上电、固件 hand 配置错误或信号差 | 检查 micro:bit 显示 L/R，靠近 ESP32 |
| `age` 持续变大 | 数据流中断 | 重启 ESP32 和对应 micro:bit |
| `sequence_gap` 很多 | 广播丢包或 2.4 GHz 干扰 | 缩短距离，减少 Wi-Fi/蓝牙干扰 |
| fusion 无法启动 | 预览占用 `17778` | 停止预览后再启动 fusion |

