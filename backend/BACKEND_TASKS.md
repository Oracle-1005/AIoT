# 后端侧任务清单（推理接线 / LED 下行 / 一致性修复）

**更新日期**: 2026-07-24
**面向**: 后端组员（Flask `backend/`）
**前提**: 硬件侧正在做 micro:bit 提频实验（见 `hardware/HARDWARE_TASKS.md` 任务 1）。本清单全部修复完成后，再统一做端到端验证——请逐项标记完成状态。

---

## 任务 1（最高优先）：接通模型推理链

现状（7/24 已核实）：

- `model_service.py` 启动时 `load()` 模型，但 `predict()` 在全后端的唯一调用方是 `integration.run_prediction()`，而 `integration.py` 的三个函数（`run_prediction` / `accept_prediction` / `send_pi_command`）**无任何调用方**——推理链是死代码；
- `sonic_pi.py` 的 `publish_prediction()`（预测→音乐）同样只有死路可达；
- `from model.inference import GestureClassifier` 目前会 **ImportError**：`model/inference/` 下只有 `realtime_pipeline.py`，没有 `GestureClassifier` 类，也没有 `__init__.py`。模型侧封装由我方补（见文末"协调项"），但后端接线不依赖它——可以先写好调用方。

请求：

1. 选定触发源并接线。建议路径：`fused_frame` 上行 → 按 hand 分路、**按 `sample_sequence` 去重** → 滑窗特征 → `model_service.predict()` → `integration.accept_prediction()` → 落库 + `/api/gesture/current` + `sonic_pi.publish_prediction()`；
2. 模型输入契约按 `docs/TASK_ASSIGNMENT.md` 1.3 节：**camera_features 为主**（轨迹/速度/张合度，30 fps——摄像头是手势识别主传感器，7/24 团队已确认），**microbit_features 为辅**（窗口聚合值，耐稀疏；缺数据时填 0 + `available` 标志），外加 `cross_modal_features`。窗口特征的计算归模型侧（我方），后端负责把窗口数据喂进 `predict()`；
3. **必须去重**：micro:bit 原始采样名义仅 6.7 Hz（辅助通道，不追高采样率），而 `fused_frame` 以 30 Hz 相机帧率对同一 micro:bit 样本做最近邻重复引用——不去重的话特征窗里全是同一样本的拷贝；
4. `window_features` 上行类型：要么在 `message_router.py` 注册（`app.py:6` 和 `README.md:7` 声称接受 4 类），要么从文档删掉——当前文档与实现不一致。

## 任务 2：冻结 `led_command` 下行 schema

`README.md:91-105` 的示例 `{effect, strength, duration_ms}` 与 `PI_BACKEND_COMMUNICATION_PLAN.md:317-329` 的 `{mode, color, brightness, duration_ms, source}` **不一致**。

请求：冻结一版并写进 `docs/INTERFACE_CONTRACT.md`。我方按冻结版实现 Pi 侧 `led_command` 消费端（复用已真机验证的 `LedController`，9 手势动画现成）。建议至少含：效果名 / brightness / duration_ms；效果名直接复用任务 3 的手势集合可省一层映射。

## 任务 3：手势标签映射表（联合，我方出 RF 侧）

后端 `state.py:10-27` 的 `GESTURES`（idle / downbeat / crescendo / decrescendo / cutoff / style_switch / tempo_up / tempo_down / 各 wrist_strike 等）和 `sonic_pi.py:33-51` 的联动集合，与 RF 模型的 9 手势（静止 / 开始 / 停止 / 强拍 / 弱拍 / 渐强 / 渐弱 / 左手提示 / 右手提示）**不是一套**。

请求：共同出一张 RF label → `event.type` 对照表；`predict()` 输出先映射再进 `accept_prediction()`，否则 Sonic Pi 联动和前端显示会对不上。

## 任务 4：一致性小修（低风险，随手做）

- `AIOT_AUTO_INFER_WINDOW_FEATURES`：出现在 `.env.example:18` 和 `README.md:133`，但代码无人消费——接线或删除；
- `README.md:16` 的运行路径 `G:\code\AIoT\AIoT` 是旧机器的，改成相对路径；
- （可选）`verify_pi_stream.py` 只验计数器增量、不验 payload 字段，可加 `--strict` 模式校验必需字段；
- （可选）`state.py` 的 `connected` 改为按 `age_ms < 1000` 计算（`PI_BACKEND_COMMUNICATION_PLAN.md:270` 的悬置建议）。

## 不要破坏（前端硬性依赖）

前端以 250 ms 轮询 `/api/status`、`/api/gesture/current`、`/api/sensors/live`、`/api/music/state`（+ 可选 `/api/pi/status`）：字段**只增不删**，`confidence ∈ [0,1]`（`docs/FRONTEND_PROGRESS_AND_STRUCTURE.md` §9 的对接请求）。

---

## 全部修复后的联合验证（我方主导；等硬件提频结论 + 本清单完成后开始）

1. `python backend/test_backend.py` 全过；
2. `backend/tools/verify_pi_stream.py --duration 60 --require status --require fused_frame --require control_event` PASS；
3. 推理链：做手势 → `fused_frame` → predict → `/api/gesture/current` 变化 + Sonic Pi 联动 + `predictions` 表落库；
4. LED：`POST /api/pi/send`（led_command）→ Pi 侧灯板响应（消费端由我方实现）。

## 协调项（我方任务，不阻塞后端开工）

- `model.inference.GestureClassifier` 缺失：我方（模型侧）补薄封装类，按 `model_service.py:64-74` + `INTERFACE_CONTRACT.md` 4.3 的六字段契约（gesture / confidence / gesture_id / timestamp / features_used / all_probs）。**等采样率实验结论后随重训模型一并交付**；
- RF 9 手势定义与训练数据格式：我方提供；
- `led_command` 的 Pi 侧消费端：我方实现（任务 2 冻结 schema 后开工）。
