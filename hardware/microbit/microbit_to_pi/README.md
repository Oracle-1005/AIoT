# 双手 micro:bit Radio 发送端

**当前正式链路**：

```text
左手 micro:bit ─┐
                ├─ MakeCode Radio 组 79
右手 micro:bit ─┘
                         ↓
第三块 micro:bit 网关 → USB 串口 → Raspberry Pi
                         ↓
降噪、时间对齐、摄像头融合 → PC 后端
```

旧 ESP32 BLE/Wi-Fi 方案仍保存在 Git 和树莓派回退目录中，但不再是当前
`pi-fusion` 的默认输入方式。

## 固件文件

| 文件 | 用途 |
| --- | --- |
| `main.ts` | 左右手共用的 MakeCode TypeScript 源码 |
| `pxt.json` | MakeCode Radio 工程依赖 |
| `MICROBIT_VISUAL_VERIFICATION.md` | 旧 ESP32 预览说明，仅供回退参考 |

## 左右手配置

烧录左手前：

```typescript
const HAND: number = 0
```

烧录右手前：

```typescript
const HAND: number = 1
```

当前设备映射：

| 手别 | 本次烧录盘符 | DAPLink 唯一 ID 尾段 | Radio 发送板序列号 |
| --- | --- | --- | --- |
| 左手 | `F:` | `e15b1fe8a20608ea` | `-1944233693` |
| 右手 | `H:` | `6a0e2f5b8fe408e9` | `-349312960` |

盘符可能因重新插拔变化，重新烧录时应核对 `DETAILS.TXT` 的唯一 ID。

## 发送参数

```typescript
const RADIO_GROUP = 79
const SAMPLE_PERIOD_MS = HAND == 0 ? 47 : 53
const SENSOR_REPEAT_TOTAL = 2
const SENSOR_REPEAT_INTERVAL_MS = 15
const EVENT_REPEAT_TOTAL = 7
const EVENT_REPEAT_INTERVAL_MS = 40
```

左右手采用不同的互质发送周期，逻辑采样率约为 `21.3 Hz` 和 `18.9 Hz`，
避免两块板启动相位接近后持续发生无线碰撞。
每个传感样本发送两次，Pi 根据相同的 `sample_sequence` 丢弃重复副本，只让
首个成功副本进入滤波和融合。按键事件与传感样本在同一循环中交错发送，
按键事件优先，但不会像旧 BLE 方案一样暂停数百毫秒的传感采样。

## 数据协议

传感状态包固定为 `17 B`：

```text
header, sample_sequence, device_timestamp_ms,
ax_mg, ay_mg, az_mg, pitch_deg, roll_deg
```

控制事件包固定为 `11 B`：

```text
header, event_sequence, device_timestamp_ms,
event_code, priority, repeat_index, repeat_total
```

协议与旧 ESP32 网关向 Pi 输出的完整载荷保持一致，因此 Pi 的协议解析、
序号跟踪、滤波和融合数据结构不需要变化。

## 按键定义

| 手别 | 操作 | 后端事件 |
| --- | --- | --- |
| 左手 | A 短按 | `resume` |
| 左手 | B 短按 | `cutoff` |
| 左手 | A+B 长按 | `gesture_start` |
| 右手 | A 短按 | `style_switch` |
| 右手 | B 长按 | `stop` |
| 右手 | A+B 长按 | `gesture_start` |

同一个按键事件重复发送 7 次，Pi 根据 `(hand, event_sequence)` 去重，只向
后端输出一次。

## 运行验证

树莓派正式服务：

```bash
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f
```

浏览器打开：

```text
http://192.168.43.221:8790/
```

如需使用原来的双 micro:bit 独立页面，可在 `pi-fusion` 保持运行时启动只读
兼容预览：

```bash
bash hardware/microbit/microbit_to_pi/tools/start_radio_preview.sh
```

然后打开：

```text
http://192.168.43.221:8787/
```

该模式读取 `8790/state`，不占用 USB 串口，不会中断正式融合和后端发送。

通过标准：

- 左右手原始数据和滤波数据都持续刷新；
- `source` 分别为 `left`、`right`；
- `transport` 为 `microbit_radio_usb`；
- `age` 通常低于 `120 ms`；
- 融合输出的两个 `microbits[]` 尽量为 `available=true`；
- PC 状态显示已连接且发送队列没有持续增长。

完整部署、回退和故障排查见：

```text
hardware/MICROBIT_RADIO_USB_GATEWAY.md
```
