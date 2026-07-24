# LED 下行链路（PC 后端 → Pi → WS2812B 灯板）接入说明

> 2026-07-24 新增。本文档说明 `led_command` 下行链路的实现、部署步骤与验证方法。
> 上行链路（Pi → PC）不受影响；本文只覆盖下行。

## 1. 链路总览

```text
PC 后端  POST /api/pi/send  (led_command, 冻结 schema: INTERFACE_CONTRACT §8.1)
   │  integration.send_pi_command() → pi_gateway.send()（同一 TCP 连接回写）
   ▼  TCP:9000 JSONL 下行
Pi pi-fusion  TcpJsonlClient._read_loop()（新增，与上行共用一条连接）
   │  set_downlink_handler 注册
   ▼
LedConsumer（新增 fusion_pipeline/led_consumer.py）
   │  schema 校验 → effect 映射 → brightness/duration_ms 语义
   ▼
LedController（复用已真机验证的 hardware/raspberry_pi_iot/led/controller.py）
   ▼  ws2812-pio 内核驱动，/dev/leds0，GPIO19
WS2812B 双灯板（左/右手各 8x32）
```

关键性质：

- **单连接双向**：下行复用上行同一条 TCP:9000 连接，后端无需新增端口；
- **断线自愈**：读循环跟随重连循环，重连后下行自动恢复（已有测试覆盖）；
- **永不拖垮管线**：无 LED 后端（无权限/非 Pi）时命令计数丢弃并告警，fusion 正常运行；
- **effect 直通 9 手势动画**：LED 侧无需知道模型细节，后端发什么效果名就播什么。

## 2. 本次改动文件

| 文件 | 改动 |
| --- | --- |
| `fusion_pipeline/tcp_client.py` | 保留下行 reader；新增 `_read_loop()`、`set_downlink_handler()`、`downlink_received` 统计；`_connect()` 重连前关闭旧 transport（防读循环卡死 + 防泄漏） |
| `fusion_pipeline/led_consumer.py` | **新增**。`LedConsumer`：校验冻结 schema、effect→pattern 映射、`duration_ms` 定时恢复默认动画、离线降级 |
| `fusion_pipeline/main.py` | 接线：`led:` 配置段、创建 LedConsumer、注册下行回调、主循环按 `refresh_hz` 驱动动画帧、停止时清灯 |
| `fusion_pipeline/config.yaml` | 新增 `led:` 段（默认 `enabled: true`） |
| `raspberry_pi_iot/__init__.py` | 新增空包标记（使 `raspberry_pi_iot.led.controller` 可导入） |
| `fusion_pipeline/test_led_downlink.py` | **新增**。54 项测试：映射/校验/定时恢复/降级/TCP 下行端到端（含重连） |

## 3. 配置（config.yaml）

```yaml
led:
  enabled: true
  default_pattern: "breathing"   # 启动动画 + 定时命令结束后的回落动画
  brightness_limit: 0.25         # 安全上限，首次点亮不要调高
  refresh_hz: 50                 # 动画帧率（主循环内节流）
```

## 4. led_command 语义

契约（后端冻结，`backend/docs/INTERFACE_CONTRACT.md` §8.1）：

```json
{"message_type": "led_command",
 "payload": {"effect": "downbeat", "brightness": 0.9, "duration_ms": 120, "source": "backend"}}
```

Pi 侧语义：

- `effect`：优先按 §8.2 规范事件名映射；同时接受 RF 中文标签（`强拍` 等）与英文别名
  （`strong_beat`、`start`、`wave` 等）。映射表见 `led_consumer.EFFECT_TO_PATTERN`。
- `brightness`：映射为动画 intensity，超出 `[0,1]` 会被截断（不拒绝）。
- `duration_ms`：`>0` 播放到时后自动回落 `default_pattern`；`=0` 一直保持到下一条命令。
  `start`/`stop` 是一次性动画，播完自然结束。
- 其他下行类型（`led_state`/`led_config`/`system_command`/`time_sync`）目前只记日志不处理。

后端手动发命令（组员电脑 .209 后端运行时）：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/pi/send `
  -ContentType 'application/json' `
  -Body '{"message_type":"led_command","payload":{"effect":"downbeat","brightness":0.9,"duration_ms":500}}'
```

## 5. Pi 部署步骤（重点：/dev/leds0 权限）

`pi-fusion.service` 以 `User=ag1_client` 运行，而 `/dev/leds0` 默认仅 root 可写。
**不加权限时 LED 不会亮**（日志会报 `ws2812-pio open failed: Permission denied`，
命令按离线丢弃计数，管线其它部分不受影响）。

推荐做法（udev 规则，重启持久；服务已在 `gpio` 附加组）：

```bash
# 1. 确认设备节点属性（不同驱动版本字段可能不同，先看一眼）
udevadm info -a /dev/leds0 | head -20

# 2. 写规则（KERNEL 名按上一步实际值，一般为 leds0）
echo 'KERNEL=="leds0", MODE="0660", GROUP="gpio"' | sudo tee /etc/udev/rules.d/99-ws2812.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 3. 验证权限（应显示 crw-rw---- root gpio）
ls -l /dev/leds0
```

备选（更省事但权限放大）：把 `pi-fusion.service` 改为 `User=root` 并 `sudo systemctl daemon-reload`。

然后同步代码并重启：

```bash
# 同步仓库到 /home/ag1_client/aiot_conductor/project（按惯例 tar 方式）
sudo systemctl restart pi-fusion
sudo journalctl -u pi-fusion -f
# 期望日志：
#   LED consumer ready: backend=ws2812-pio, 512 LEDs, default_pattern=breathing
# 若权限未配好：
#   LED consumer: no LED backend (...) — led_commands will be dropped.
```

## 6. 验证

本地（无硬件，Windows/Pi 均可）：

```bash
cd hardware/fusion_pipeline
python test_led_downlink.py   # 54 项全过
```

真机（Pi + 后端在线）：

1. 后端执行第 4 节的 `POST /api/pi/send`（effect 逐个试 9 手势规范名）；
2. 灯板应播放对应动画（动画定义见 `raspberry_pi_iot/led/controller.py` 头注释）；
3. Pi 日志出现 `led_command applied: effect=... → pattern=...`；
4. `status` 消息中 `tcp.downlink_received` 计数随命令递增。

## 7. 故障排查

| 现象 | 排查 |
| --- | --- |
| 日志 `no LED backend` | `/dev/leds0` 是否存在（overlay 是否启用）；`ls -l` 权限是否 gpio 组可写；udev 规则是否生效 |
| 后端 `/api/pi/send` 返回失败 | 后端未运行或 Pi 未连上（看后端 `/api/status` 的 pi_gateway.connected） |
| 命令到达但灯不亮 | 日志是否有 `led_command applied`；有则是供电/接线问题（查 330-470Ω 电阻、共地、亮度上限） |
| 重连后下行失效 | 不应发生（已有测试覆盖）；查日志 `TCP downlink EOF` 后是否有 `Connected to ...` |
