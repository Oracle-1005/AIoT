# BLE 固件刷写步骤

## 问题
MicroPython v2.1.1 **不支持 `bluetooth` 模块**。必须使用 MakeCode + Bluetooth 扩展。

## 操作步骤（每个 Micro:bit 约 2 分钟）

### 1. 打开 MakeCode 编辑器
浏览器打开: **https://makecode.microbit.org/**

### 2. 新建项目
点击 **"新建项目"** → 随便起个名（如 `ble-conductor-A`）

### 3. 切换到 JavaScript 模式
顶部中间下拉菜单 → 选择 **"JavaScript"**

### 4. 添加 Bluetooth 扩展
点击 **"高级"** → **"扩展"** → 搜索 **"bluetooth"** → 点击添加
> 会提示移除 radio 扩展 → 点确定

### 5. ⚠️ 关键设置：允许无需配对
点击右上角 ⚙️ **"项目设置"** → 勾选 **"无需配对"（No Pairing Required）**
> 不勾这步 BLE 扫不到设备！

### 6. 粘贴代码
清空编辑器内容，复制粘贴下面文件的内容：
```
d:\CC\AIoT\hardware\microbit\ble_uart.js
```
> ⚠️ 第二个 Micro:bit 把第 25 行 `let DEVICE_ID = "A"` 改为 `"B"`

### 7. 下载 + 刷入
点击左下角 **"下载"** → 得到 `.hex` 文件 → 拖到 `MICROBIT` 驱动器

### 8. 重复第二个
改 `DEVICE_ID = "B"`，再下载一次，刷入第二个 Micro:bit

## 预期结果
- Micro:bit LED 显示 ❤️→熄 → 等待连接（中心点灭）
- PC 用 BLE Scanner 可搜到 `BBC micro:bit [xxxxx]`
- 连接后 LED 中心点亮 → 开始接收 `A,acc_x,acc_y,acc_z,ts\n` 格式数据
