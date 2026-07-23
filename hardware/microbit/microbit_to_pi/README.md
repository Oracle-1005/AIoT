# 双 micro:bit 到树莓派数据链路说明

**更新日期**: 2026-07-23

当前正式链路：

```text
left micro:bit v2  -> BLE advertising
right micro:bit v2 -> BLE advertising
ESP32              -> 扫描广播并通过 UDP:17778 转发到 Raspberry Pi
Raspberry Pi       -> fusion_pipeline 与摄像头数据融合
PC backend         -> 接收 fused_frame / status / control_event
```

旧的“树莓派直接 BLE GATT/UART 同时连接两块 micro:bit”方案已归档到：

```text
hardware/microbit/legacy_ble_connection_tests/
```

该旧方案可用于参考协议设计，但不再作为当前稳定性优先的默认方案。

## 1. 本目录内容

```text
hardware/microbit/microbit_to_pi/
├── main.ts                         # MakeCode TypeScript 广播固件
├── pxt.json                        # MakeCode 项目依赖
├── tools/live_preview_server.py    # 通用浏览器预览服务
├── MICROBIT_VISUAL_VERIFICATION.md # micro:bit 预览验证说明
└── README.md                       # 本说明
```

## 2. micro:bit 固件状态

两块 micro:bit 使用同一份 `main.ts`，烧录前只修改 `HAND`：

```typescript
const HAND = 0  // left
const HAND = 1  // right
```

当前关键参数：

```typescript
const SAMPLE_PERIOD_MS = 150
const SENSOR_REPEAT_TOTAL = 1
const SENSOR_REPEAT_INTERVAL_MS = 50
const EVENT_REPEAT_TOTAL = 7
const EVENT_REPEAT_INTERVAL_MS = 90
const CONTROL_HOLD_MS = 70
const BLE_CONNECTABLE = false
```

含义：

- 状态样本约每 `150 ms` 更新一次。
- 状态样本不再由程序主动重复多次，避免拉长实际采样间隔。
- BLE 广播层会自然重复当前广告包。
- 按键事件重复广播 `7` 次，优先保证控制事件到达。
- micro:bit 不需要配对、不需要连接、不依赖蓝牙地址。

## 3. 广播数据内容

状态包包含可用于训练的 IMU 数据：

```text
sample_sequence
device_timestamp_ms
ax_mg
ay_mg
az_mg
pitch_deg
roll_deg
```

`ax_mg / ay_mg / az_mg` 单位为 `mg`，约 `1000 mg = 1g`。静止时某个轴接近 `±1000 mg` 是重力投影，不是异常。

按键事件包含：

```text
event_sequence
device_timestamp_ms
event_code
priority
repeat_index
repeat_total
```

## 4. 按键事件定义

左手：

| 操作 | event_code | candidate | 进入后端后的事件 |
| --- | --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `start_or_resume` | `resume` |
| B 短按 | `B_SHORT_PRESS` | `pause` | `cutoff` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` | `gesture_start` |

右手：

| 操作 | event_code | candidate | 进入后端后的事件 |
| --- | --- | --- | --- |
| A 短按 | `A_SHORT_PRESS` | `style_switch` | `style_switch` |
| B 长按 | `B_LONG_PRESS` | `emergency_stop` | `stop` |
| A+B 长按 | `AB_LONG_PRESS` | `recalibrate` | `gesture_start` |

## 5. 烧录方式

1. 打开 MakeCode for micro:bit。
2. 新建项目。
3. 添加 Bluetooth 扩展。
4. 切换到 JavaScript / TypeScript。
5. 粘贴 `main.ts` 内容。
6. 烧录左手前设置 `const HAND = 0`。
7. 烧录右手前设置 `const HAND = 1`。
8. 上电后左手应显示 `L`，右手应显示 `R`。

## 6. 树莓派预览验证

micro:bit 预览依赖 ESP32 网关，入口见：

```text
hardware/microbit/microbit_to_pi/MICROBIT_VISUAL_VERIFICATION.md
```

树莓派上运行：

```bash
sudo systemctl stop pi-fusion 2>/dev/null || true
cd /home/ag1_client/aiot_conductor/project
bash hardware/raspberry_pi/esp32_ble_gateway_to_Pi/tools/start_gateway_preview.sh
```

PC 浏览器打开：

```text
http://192.168.43.221:8787/
```

通过标准：

- 页面顶部显示 `live`。
- left 和 right 两列都持续刷新。
- 两侧 `sequence` 持续增长。
- 两侧 `age` 周期性回落，不持续增大。
- 按键后“最近控制事件”刷新。

该预览会占用 UDP `17778`，正式启动 `pi-fusion.service` 前必须关闭。

## 7. 正式融合验证

完整流程见：

```text
hardware/END_TO_END_TRANSMISSION_VERIFICATION.md
```

PC 后端启动后，运行：

```powershell
cd G:\code\AIoT\AIoT
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 30
```

如果需要验证按键事件：

```powershell
backend\.venv\Scripts\python.exe backend\tools\verify_pi_stream.py --duration 60 --require status --require fused_frame --require control_event
```

运行期间至少按一次 micro:bit 按键。

## 8. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 只有一侧有数据 | 另一块 micro:bit 未上电、`HAND` 设置错误或信号差 | 检查屏幕显示 `L/R`，靠近 ESP32 |
| `sequence_gap` 偶发 | BLE 广播无确认机制 | 可接受，重点看两侧是否持续刷新 |
| `sequence_gap` 很多 | 距离、遮挡或 2.4 GHz 干扰 | ESP32 与 micro:bit 保持 30 cm 到 1 m，两块板不要贴在一起 |
| 按键事件不出现 | 事件广播被状态包覆盖或距离太远 | 靠近 ESP32，重新按键，观察 `8787` 页面 |
| fusion 报端口占用 | `8787` 预览仍占用 UDP `17778` | 停止预览后重启 `pi-fusion` |
