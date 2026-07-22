/**
 * 双 micro:bit -> 树莓派 BLE 二进制发送端（MakeCode TypeScript）
 *
 * 使用方法：
 * 1. 在 https://makecode.microbit.org 新建项目。
 * 2. 在“扩展”中添加 Bluetooth，然后切换到 JavaScript。
 * 3. 将本文件完整复制到 main.ts。
 * 4. 左腕保持 HAND = 0；给右腕烧录时改成 HAND = 1。
 *
 * 协议：
 * - sensor_state: 17 B，25 Hz，header + <H I h h h h h>
 * - control_event: 11 B，事件确认后发送 3 次
 * - 所有多字节整数均为 Little Endian（小端序）
 */

// ======================== 可调整参数 ========================

// 0 = 左手，1 = 右手。两块 micro:bit 必须分别烧录不同的值。
// 显式标注 number，避免 MakeCode 把它推断成只能取 0 的字面量类型；
// 这样复制项目并改为 1 时，左右手分支都能通过类型检查。
const HAND: number = 0

// 默认采用 10 Hz：1000 / 10 = 100 ms。micro:bit BLE UART 连续高频发送时
// 容易在树莓派 BlueZ 服务发现/重连阶段诱发断连；稳定后再按需要调高。
const SAMPLE_PERIOD_MS = 100

// 普通按钮防抖时间与长按判定阈值。
const DEBOUNCE_MS = 60
const LONG_PRESS_MS = 1000

// 每个控制事件共发送 3 次，相邻发送间隔 20 ms。
const EVENT_REPEAT_TOTAL = 3
const EVENT_REPEAT_INTERVAL_MS = 20
const EVENT_QUEUE_MAX = 8

// ======================== 协议常量 ========================

const MESSAGE_SENSOR_STATE = 1
const MESSAGE_CONTROL_EVENT = 2

const EVENT_A_SHORT_PRESS = 0x01
const EVENT_B_SHORT_PRESS = 0x02
const EVENT_B_LONG_PRESS = 0x03
const EVENT_AB_LONG_PRESS = 0x04

const SENSOR_PACKET_LENGTH = 17
const CONTROL_PACKET_LENGTH = 11

/**
 * 待重复发送的不可变控制事件。
 * repeatIndex 是下一次发送时要写入数据包的编号。
 */
class PendingEvent {
    sequence: number
    timestampMs: number
    eventCode: number
    priority: number
    repeatIndex: number
    nextDueMs: number

    constructor(sequence: number, timestampMs: number,
        eventCode: number, priority: number, nextDueMs: number) {
        this.sequence = sequence
        this.timestampMs = timestampMs
        this.eventCode = eventCode
        this.priority = priority
        // 第 0 份会在事件产生时立即发送；队列从第 1 份开始。
        this.repeatIndex = 1
        this.nextDueMs = nextDueMs
    }
}

// ======================== 运行状态 ========================

let bluetoothConnected = false
let sampleSequence = 0
let eventSequence = 0
let nextSampleDueMs = input.runningTime()

// 状态采样和 BLE 发送分开：采样按固定时钟进行，发送被事件短暂占用时，
// 只保留最新状态包，避免陈旧状态在恢复连接后堆积。
let latestSensorPacket: Buffer = null
let sensorPacketPending = false

let pendingEvents: PendingEvent[] = []

// 按钮防抖状态。
let rawA = false
let rawB = false
let lastRawA = false
let lastRawB = false
let stableA = false
let stableB = false
let rawAChangedMs = 0
let rawBChangedMs = 0

// 按键语义状态。
let aPressStartMs = 0
let bPressStartMs = 0
let bLongReported = false
let abActive = false
let abPressStartMs = 0
let abLongReported = false

// ======================== 数据包编码 ========================

/**
 * Header: bit 0~1 = message_type，bit 2 = hand，bit 3~7 保持为 0。
 */
function makeHeader(messageType: number): number {
    return (messageType & 0x03) | ((HAND & 0x01) << 2)
}

/** 构造 17 B sensor_state。加速度的单位由 MakeCode 直接提供为 mg。 */
function buildSensorPacket(sequence: number, timestampMs: number): Buffer {
    const packet = pins.createBuffer(SENSOR_PACKET_LENGTH)
    packet.setUint8(0, makeHeader(MESSAGE_SENSOR_STATE))
    packet.setNumber(NumberFormat.UInt16LE, 1, sequence)
    packet.setNumber(NumberFormat.UInt32LE, 3, timestampMs)
    packet.setNumber(NumberFormat.Int16LE, 7, input.acceleration(Dimension.X))
    packet.setNumber(NumberFormat.Int16LE, 9, input.acceleration(Dimension.Y))
    packet.setNumber(NumberFormat.Int16LE, 11, input.acceleration(Dimension.Z))
    packet.setNumber(NumberFormat.Int16LE, 13, input.rotation(Rotation.Pitch))
    packet.setNumber(NumberFormat.Int16LE, 15, input.rotation(Rotation.Roll))
    return packet
}

/** 构造 11 B control_event；只有 repeatIndex 会在三份副本间变化。 */
function buildControlPacket(event: PendingEvent, repeatIndex: number): Buffer {
    const packet = pins.createBuffer(CONTROL_PACKET_LENGTH)
    packet.setUint8(0, makeHeader(MESSAGE_CONTROL_EVENT))
    packet.setNumber(NumberFormat.UInt16LE, 1, event.sequence)
    packet.setNumber(NumberFormat.UInt32LE, 3, event.timestampMs)
    packet.setUint8(7, event.eventCode)
    packet.setUint8(8, event.priority)
    packet.setUint8(9, repeatIndex)
    packet.setUint8(10, EVENT_REPEAT_TOTAL)
    return packet
}

/**
 * 通过 micro:bit UART Service 发送原始 Buffer。
 * uartWriteBuffer 是 MakeCode JavaScript 可用的底层二进制接口。
 */
function sendBuffer(packet: Buffer): void {
    if (bluetoothConnected) {
        bluetooth.uartWriteBuffer(packet)
    }
}

// ======================== 控制事件产生与调度 ========================

/**
 * 文档中已确定的 hand + event_code -> priority 映射。
 * 返回 -1 表示该手别不应产生这个事件。
 */
function priorityFor(eventCode: number): number {
    if (eventCode == EVENT_AB_LONG_PRESS) return 60

    if (HAND == 0) {
        if (eventCode == EVENT_A_SHORT_PRESS) return 40  // 开始/继续
        if (eventCode == EVENT_B_SHORT_PRESS) return 60  // 暂停
    } else {
        if (eventCode == EVENT_A_SHORT_PRESS) return 20  // 风格切换
        if (eventCode == EVENT_B_LONG_PRESS) return 100  // 紧急停止
    }
    return -1
}

/**
 * 创建一次新事件：分配序号、固定确认时刻、立即发送第 0 份，
 * 再将第 1/2 份加入重复队列。断线期间的按键不会延迟到重连后执行。
 */
function emitControlEvent(eventCode: number, nowMs: number): void {
    const priority = priorityFor(eventCode)
    if (priority < 0 || !bluetoothConnected) return

    const event = new PendingEvent(
        eventSequence,
        nowMs,
        eventCode,
        priority,
        nowMs + EVENT_REPEAT_INTERVAL_MS
    )
    eventSequence = (eventSequence + 1) & 0xffff

    // 新事件第一次发送具有最高优先级。
    sendBuffer(buildControlPacket(event, 0))

    // 事件本身很少发生；若队列异常堆满，保留较新的事件。
    if (pendingEvents.length >= EVENT_QUEUE_MAX) {
        pendingEvents.shift()
    }
    pendingEvents.push(event)
}

/** 每次主循环最多发送一份到期重复包，让状态包能插入重复包之间。 */
function sendOneDueEventRepeat(nowMs: number): void {
    for (let i = 0; i < pendingEvents.length; i++) {
        const event = pendingEvents[i]
        if (nowMs >= event.nextDueMs) {
            sendBuffer(buildControlPacket(event, event.repeatIndex))
            event.repeatIndex += 1

            if (event.repeatIndex >= EVENT_REPEAT_TOTAL) {
                pendingEvents.removeAt(i)
            } else {
                event.nextDueMs = nowMs + EVENT_REPEAT_INTERVAL_MS
            }
            return
        }
    }
}

// ======================== 按钮防抖与长按状态机 ========================

/** 将物理按钮的抖动过滤成稳定的按下/释放状态。 */
function updateDebouncedButtons(nowMs: number): void {
    rawA = input.buttonIsPressed(Button.A)
    rawB = input.buttonIsPressed(Button.B)

    if (rawA != lastRawA) {
        lastRawA = rawA
        rawAChangedMs = nowMs
    }
    if (rawB != lastRawB) {
        lastRawB = rawB
        rawBChangedMs = nowMs
    }

    if (stableA != rawA && nowMs - rawAChangedMs >= DEBOUNCE_MS) {
        stableA = rawA
        if (stableA) aPressStartMs = nowMs
    }
    if (stableB != rawB && nowMs - rawBChangedMs >= DEBOUNCE_MS) {
        stableB = rawB
        if (stableB) {
            bPressStartMs = nowMs
            bLongReported = false
        }
    }
}

/**
 * 实现文档中的组合键规则：一旦 A、B 同时稳定按下，只处理 AB_LONG，
 * 并一直等到两个按钮都释放后才退出组合状态。
 */
function processButtonState(nowMs: number): void {
    if (!abActive && stableA && stableB) {
        abActive = true
        abPressStartMs = nowMs
        abLongReported = false
        // 进入组合键后取消独立 B 长按。
        bLongReported = true
    }

    if (abActive) {
        if (stableA && stableB && !abLongReported &&
            nowMs - abPressStartMs >= LONG_PRESS_MS) {
            emitControlEvent(EVENT_AB_LONG_PRESS, nowMs)
            abLongReported = true
        }

        if (!stableA && !stableB) {
            // 无论 AB 是否达到长按，都不再补发 A/B 单键事件。
            abActive = false
            abLongReported = false
            bLongReported = false
        }
        return
    }

    // 右手 B 长按是紧急停止。左手没有 B_LONG 映射，因此长按不产生事件，
    // 也不会在释放时误触发 B_SHORT。
    if (stableB && !bLongReported && nowMs - bPressStartMs >= LONG_PRESS_MS) {
        if (HAND == 1) {
            emitControlEvent(EVENT_B_LONG_PRESS, nowMs)
        }
        bLongReported = true
    }

    // 通过稳定状态的下降沿识别释放。previousStable* 只在本函数末尾更新。
    if (previousStableA && !stableA) {
        emitControlEvent(EVENT_A_SHORT_PRESS, nowMs)
    }
    if (previousStableB && !stableB && !bLongReported) {
        emitControlEvent(EVENT_B_SHORT_PRESS, nowMs)
    }
}

let previousStableA = false
let previousStableB = false

// ======================== BLE 与主循环 ========================

bluetooth.startUartService()
// 不使用最高发射功率；距离树莓派很近时过强 RSSI 反而容易造成连接阶段不稳定。
bluetooth.setTransmitPower(3)
input.setAccelerometerRange(AcceleratorRange.FourG)

bluetooth.onBluetoothConnected(function () {
    bluetoothConnected = true
    pendingEvents = []
    basic.showIcon(IconNames.Yes)
})

bluetooth.onBluetoothDisconnected(function () {
    bluetoothConnected = false
    pendingEvents = []
    sensorPacketPending = false
    basic.showIcon(IconNames.No)
})

basic.showString(HAND == 0 ? "L" : "R")

basic.forever(function () {
    const nowMs = input.runningTime()

    // 先读取按钮，新确认的事件会在 emitControlEvent() 中立即发送。
    updateDebouncedButtons(nowMs)
    processButtonState(nowMs)

    // 固定周期采样。序号在“产生样本”时递增，而不是在发送成功时递增。
    if (nowMs >= nextSampleDueMs) {
        latestSensorPacket = buildSensorPacket(sampleSequence, nowMs)
        sampleSequence = (sampleSequence + 1) & 0xffff
        sensorPacketPending = true

        nextSampleDueMs += SAMPLE_PERIOD_MS
        // 若系统曾长时间阻塞，不补采大量旧样本，从当前时刻恢复周期。
        if (nowMs - nextSampleDueMs > SAMPLE_PERIOD_MS * 4) {
            nextSampleDueMs = nowMs + SAMPLE_PERIOD_MS
        }
    }

    // 优先级：新事件首包（已发送） > 最新状态 > 到期重复包。
    if (sensorPacketPending && bluetoothConnected) {
        sendBuffer(latestSensorPacket)
        sensorPacketPending = false
    }
    sendOneDueEventRepeat(nowMs)

    previousStableA = stableA
    previousStableB = stableB

    // 5 ms 轮询足以完成 60 ms 防抖，也避免 forever 忙等占满 CPU。
    basic.pause(5)
})
