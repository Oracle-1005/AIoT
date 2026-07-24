# 硬件侧任务清单（采样率确认 / ESP32 / 固件同步 / LED 更正）

**更新日期**: 2026-07-24（v2：采样率要求已降级，只需做实验 A）
**面向**: 硬件组员（micro:bit / ESP32 / Pi 链路）
**一句话**: 只有任务 1 的一个小实验（改发射功率）+ 任务 2 的确认清单，其余是信息同步。

---

## 任务 1：micro:bit 发射功率实验（唯一需要动手的实验）

**背景（7/24 团队已确认）**：**摄像头是手势识别的主传感器**（项目提案原文："The camera will be the main spatial sensing input"），micro:bit 只是辅助——模型契约里它只提供窗口聚合特征（`acc_magnitude_mean`、`max_jerk` 之类，见 `docs/TASK_ASSIGNMENT.md` 1.3 节），这类统计量在稀疏采样下照样能算；按键事件已有 7 次重复广播保底。**因此不再追求高采样率。**

**目标**（比 v1 大幅放宽）：双手**稳定在线**、有效 **≥ 3 Hz**、`age_ms` 大部分时间 < 1 s、RSSI 均值 > -75 dBm。

**只做实验 A**：

1. `hardware/microbit/microbit_to_pi/main.ts:16`：`AD_TX_POWER_DBM`: `-12` → `0`（条件允许可试 `4`）；
2. 重烧两块板（`HAND` 常量别烧反，`main.ts:11`）；
3. 测 60 秒：

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

**结果判定**：

- 有效 ≥ 3 Hz 且预览稳定 → **收工**，不做其他实验；
- 仍 < 2 Hz 或 `age_ms` 长期 > 1 s → 再试 `SAMPLE_PERIOD_MS = 100`（实验 B）；重复包方案（C）原则上不做；
- 当前固件基线（150 ms / 不重复 / -12 dBm）7/23 实测抵达率 ~25%（有效 ~1.7 Hz），如果实验 A 后变化不大的也可以接受——micro:bit 特征在模型里是次要通道，实在不行模型可全相机特征，micro:bit 只出状态展示 + 按键。

**请在 7/24 内把实验 A 的数据发群里**（`measure_effective_rate.py` 输出截图即可）。摆放不动：ESP32 与 micro:bit 30 cm–1 m、两板分开、ESP32 靠近热点。

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
