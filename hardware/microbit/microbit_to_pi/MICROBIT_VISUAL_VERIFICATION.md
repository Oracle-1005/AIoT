# 双 micro:bit 独立预览验证

当前 `8787` 页面已适配第三块 micro:bit Radio/USB 网关方案。页面不直接读取
USB 串口，而是只读访问正式 `pi-fusion` 的 `8790/state`，因此可以与摄像头、
融合和 PC 后端传输同时运行。

## 启动

在树莓派执行：

```bash
cd /home/ag1_client/aiot_conductor/project
bash hardware/microbit/microbit_to_pi/tools/start_radio_preview.sh
```

PC 浏览器打开：

```text
http://192.168.43.221:8787/
```

当前页面已经在树莓派后台启动，可直接访问。

## 页面内容

- 左手和右手分别占用独立区域，不会互相抢占显示；
- `pitch`、`roll` 姿态；
- `ax_mg`、`ay_mg`、`az_mg` 加速度；
- 样本序号、RSSI 和刷新年龄；
- 加速度历史曲线；
- 最近控制事件和接收日志。

## 通过标准

- 页面顶部状态为 `live`；
- 左右手指示点均保持绿色；
- 两侧 `sequence` 持续增长；
- 两侧 `age` 周期性回落，不持续增大；
- 移动对应板时，该侧姿态和加速度明显变化；
- 按键后“最近控制事件”只增加一个逻辑事件。

## 健康检查

从 PC 访问：

```text
http://192.168.43.221:8787/health
```

响应中的 `latest_by_source.left` 和 `latest_by_source.right` 应同时存在，并且
`transport` 应为 `microbit_radio_usb`。

## 关闭

```bash
kill "$(cat /tmp/microbit_radio_preview_8787.pid)"
```

关闭 `8787` 不会停止 `pi-fusion`。正式联合预览仍可通过以下地址访问：

```text
http://192.168.43.221:8790/
```

## 与旧 ESP32 方式的区别

旧方式通过 `start_gateway_preview.sh` 直接占用 UDP `17778`，必须停止正式服务。
当前 `start_radio_preview.sh` 只读取 `8790/state`，不要停止 `pi-fusion`，也不会
打开第二个 USB 串口读取进程。
