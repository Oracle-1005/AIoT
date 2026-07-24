# 硬件侧任务清单（采样率对齐 / ESP32 / 固件同步 / LED 更正）

**更新日期**: 2026-07-24
**面向**: 硬件组员（micro:bit / ESP32 / Pi 链路）
**一句话**: 优先级最高的只有任务 1——micro:bit 采样率实测，请今天（7/24）给出三组数据。

---

## 任务 1（最高优先）：micro:bit 有效采样率实测与提频实验

**为什么**：手势识别（RF，9 手势）按 50 Hz 采样设计（500 ms 特征窗 ≈ 25 个样本，stride 250 ms）。当前链路有效速率距此差一个数量级；fusion 的 120 ms 对齐阈值在低抵达率下也会大面积 `available=false`，两套路都受影响。

**当前参数**（`hardware/microbit/microbit_to_pi/main.ts:13-16`）：

| 参数 | 当前值 | 含义 |
| --- | --- | --- |
| `SAMPLE_PERIOD_MS` | 150 | 名义 6.7 Hz/手 |
| `SENSOR_REPEAT_TOTAL` | 1 | 每个样本只广播一次，不重复 |
| `AD_TX_POWER_DBM` | -12 | 发射功率偏低 |
| 实测抵达率 | ~25%（7/23 提交 6217581 自述） | **有效 ≈ 1.7 Hz/手** |

**请按顺序做三组实验**，每组改完**重烧两块 micro:bit** 并测量 60 秒：

| 组 | 改动 | 目的 |
| --- | --- | --- |
| A | `AD_TX_POWER_DBM`: -12 → `0`（条件允许再试 `4`） | 成本最低，最可能直接拉高抵达率 |
| B | 在 A 基础上 `SAMPLE_PERIOD_MS`: 150 → `100`（名义 10 Hz）；可再试 `50`（20 Hz） | 提高名义速率 |
| C | 若 B 后丢包暴涨：`SENSOR_REPEAT_TOTAL = 2`（`SENSOR_REPEAT_INTERVAL_MS = 50`） | 用重复包换抵达率。注意：当前不重复是为了避免拉长采样间隔，重复会占广播预算，需实测权衡 |

不动的部分：ESP32 扫描已是连续窗口（interval=window=45）；保持 ESP32 与 micro:bit 距离 30 cm–1 m、两块 micro:bit 分开、ESP32 靠近 Wi-Fi 热点。

**测量方法**（每组 60 秒）：

```bash
# Pi 上。注意先停正式服务，17778 端口互斥：
sudo systemctl stop pi-fusion

cd ~/aiot_conductor/project/hardware/raspberry_pi/esp32_ble_gateway_to_Pi
source ~/aiot_conductor/project/camera_to_Pi/.venv/bin/activate
python -m esp32_gateway_receiver.app --config config.json --log-level WARNING > /tmp/mb_test.jsonl
# 收满 60 秒后 Ctrl-C，然后统计：
python tools/measure_effective_rate.py /tmp/mb_test.jsonl

# 测完恢复：
sudo systemctl start pi-fusion
```

`tools/measure_effective_rate.py` 随本文档一起提交，输出每侧：收包数、跳号丢包数、抵达率、有效 Hz、RSSI 均值/极值。

**目标**：每侧有效 **≥ 10 Hz**、抵达率 ≥ 80%、RSSI 均值 > -75 dBm；理想 20 Hz+。

**请在 7/24 内把三组数据发群里**。结论只有两种：

1. 能达到 ≥10 Hz → 我方按该速率采集真实手势训练数据（7/25 前重训 RF）；
2. 物理层做不到 → 我方立即改方案（按实际速率采集 + 加大特征窗 + 精简手势集），越早确定损失越小。

---

## 任务 2：ESP32 网关固件确认（已烧录则只需 5 分钟核对）

7/23 的端到端验证表明链路可能已跑通。若 ESP32 已烧最新固件（`hardware/esp32/microbit_ble_wifi_gateway/`），请确认：

1. `.ino` 中 `WIFI_SSID` / `WIFI_PASSWORD` / `PI_HOST = 192.168.43.221` / `PI_UDP_PORT = 17778` 与现网一致；
2. 8787 预览页状态 `live`，左右两列 `sequence` 各自持续增长（不被单侧抢占），`gateway.flags = 1`，`ble_rssi` 长期 > 约 -85 dBm；
3. 任务 1 改 micro:bit 参数时 ESP32 固件**无需改动**（纯转发），但每次重烧 micro:bit 后要重跑预览确认双侧 `source` 都在。

未烧录则按 `hardware/esp32/microbit_ble_wifi_gateway/README.md` 操作（Arduino IDE + NimBLE-Arduino，板型 ESP32 Dev Module）。

---

## 任务 3：micro:bit 固件同步检查

两块板烧同一份 `hardware/microbit/microbit_to_pi/main.ts`，**唯一差异是 `HAND` 常量**（`main.ts:11`，`0 = 左 / 1 = 右`），别烧反。任务 1 每组实验改完参数，两块都要重烧。

---

## 任务 4（文档更正）：LED 章节已过时，勿按旧文档操作

`hardware/raspberry_pi/PI_PROJECT_LED_HANDOFF.md` 的 LED 章节仍写 "GPIO18（物理引脚 12）+ rpi_ws281x 待安装"——**7/23 已实测推翻**：

- rpi_ws281x 在 Pi 5 上**不可用**（RP1 南桥不兼容，`ws2811_init` 返回 -3），不是"没装"的问题；
- 现方案：**ws2812-pio 内核驱动**，`/boot/firmware/config.txt` 已加 `dtoverlay=ws2812-pio,gpio=19,num_leds=512,brightness=0`；
- 数据线：**GPIO19（物理引脚 35）**，经 330–470 Ω 电阻进灯板 0 DIN，两板级联，外接 5 V 电源、三地共连——接线已验证，**请勿改动**；
- `hardware/raspberry_pi_iot/led/controller.py` 已扩展 9 手势动画并**真机验证通过**（自动检测后端：Pi5 走 `/dev/leds0`，Pi3/4 回退 rpi_ws281x）；`/dev/leds0` 仅 root 可写，LED 服务需 root 运行；
- 建议团队商定后按本节内容更新 `PI_PROJECT_LED_HANDOFF.md` 的 LED 章节（谁改都行）。

---

## 待团队确认（非纯硬件，建议 7/24 例会上定）：LED 指令源与下游架构

下游当前并存两套栈，LED 指令源只能二选一：

| | 正式链（组员） | 我方链（7/23 前） |
| --- | --- | --- |
| 通路 | fusion → TCP:9000 → PC backend → 下行 `led_command` | receiver JSONL → MQTT → RF 推理 → `pi_led_driver` |
| LED 状态 | **Pi 侧 `led_command` 消费端尚未实现**（`PI_BACKEND_COMMUNICATION_PLAN.md` §11 待办） | 已实现并真机验证（9 手势动画） |
| 推理 | backend 内有模型钩子，未接线 | `pc_inference_bridge.py` RF 推理，待测 |

我方建议：在 Pi 侧实现 `led_command` TCP 下行消费端，直接复用 `LedController`（动画零改动、延迟最低）；RF 推理输出接入 PC backend（补 `model_service` 的接线）。这样 LED 归正式链路，双方代码都不浪费。等结论后我方立即开工。
