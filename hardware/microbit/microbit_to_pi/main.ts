/*
 * micro:bit -> ESP32 BLE advertising sender.
 *
 * This version does not open a GATT/UART connection. It periodically updates
 * an Eddystone UID advertisement with a compact 16-byte frame. The ESP32 scans
 * advertisements, expands the compact frame back to the existing 17B/11B
 * project protocol, and forwards it to Raspberry Pi over UDP.
 */

// 0 = left hand, 1 = right hand. Change to 1 before flashing the right board.
const HAND: number = 0

const SAMPLE_PERIOD_MS = 150
const SENSOR_REPEAT_TOTAL = 1
const SENSOR_REPEAT_INTERVAL_MS = 50
const AD_TX_POWER_DBM = 0
const BLE_CONNECTABLE = false

const DEBOUNCE_MS = 60
const LONG_PRESS_MS = 1000
const EVENT_REPEAT_TOTAL = 7
const EVENT_REPEAT_INTERVAL_MS = 90
const CONTROL_HOLD_MS = 70
const EVENT_QUEUE_MAX = 8

const ADV_SENSOR = 0xa1
const ADV_CONTROL = 0xa2

const MESSAGE_SENSOR_STATE = 1
const MESSAGE_CONTROL_EVENT = 2

const EVENT_A_SHORT_PRESS = 0x01
const EVENT_B_SHORT_PRESS = 0x02
const EVENT_B_LONG_PRESS = 0x03
const EVENT_AB_LONG_PRESS = 0x04

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
        this.repeatIndex = 0
        this.nextDueMs = nextDueMs
    }
}

class PendingSensor {
    sequence: number
    timestampMs: number
    axMg: number
    ayMg: number
    azMg: number
    pitchDeg: number
    rollDeg: number
    repeatIndex: number
    nextRepeatMs: number

    constructor(sequence: number, timestampMs: number, nextRepeatMs: number) {
        this.sequence = sequence
        this.timestampMs = timestampMs
        this.axMg = input.acceleration(Dimension.X)
        this.ayMg = input.acceleration(Dimension.Y)
        this.azMg = input.acceleration(Dimension.Z)
        this.pitchDeg = clampInt8(input.rotation(Rotation.Pitch))
        this.rollDeg = clampInt8(input.rotation(Rotation.Roll))
        this.repeatIndex = 0
        this.nextRepeatMs = nextRepeatMs
    }
}

let sampleSequence = 0
let eventSequence = 0
let nextSampleDueMs = input.runningTime()
let pendingEvents: PendingEvent[] = []
let pendingSensor: PendingSensor = null
let controlHoldUntilMs = 0

let rawA = false
let rawB = false
let lastRawA = false
let lastRawB = false
let stableA = false
let stableB = false
let previousStableA = false
let previousStableB = false
let rawAChangedMs = 0
let rawBChangedMs = 0

let aPressStartMs = 0
let bPressStartMs = 0
let bLongReported = false
let abActive = false
let abPressStartMs = 0
let abLongReported = false

function makeHeader(messageType: number): number {
    return (messageType & 0x03) | ((HAND & 0x01) << 2)
}

function clampInt8(value: number): number {
    if (value > 127) return 127
    if (value < -128) return -128
    return value
}

function advertiseFrame(packet: Buffer): void {
    bluetooth.advertiseUidBuffer(packet, AD_TX_POWER_DBM, BLE_CONNECTABLE)
}

function advertiseSensor(sample: PendingSensor): void {
    const packet = pins.createBuffer(16)
    packet.setUint8(0, ADV_SENSOR)
    packet.setUint8(1, makeHeader(MESSAGE_SENSOR_STATE))
    packet.setNumber(NumberFormat.UInt16LE, 2, sample.sequence)
    packet.setNumber(NumberFormat.UInt32LE, 4, sample.timestampMs)
    packet.setNumber(NumberFormat.Int16LE, 8, sample.axMg)
    packet.setNumber(NumberFormat.Int16LE, 10, sample.ayMg)
    packet.setNumber(NumberFormat.Int16LE, 12, sample.azMg)
    packet.setNumber(NumberFormat.Int8LE, 14, sample.pitchDeg)
    packet.setNumber(NumberFormat.Int8LE, 15, sample.rollDeg)
    advertiseFrame(packet)
}

function advertiseControl(event: PendingEvent): void {
    const packet = pins.createBuffer(16)
    packet.setUint8(0, ADV_CONTROL)
    packet.setUint8(1, makeHeader(MESSAGE_CONTROL_EVENT))
    packet.setNumber(NumberFormat.UInt16LE, 2, event.sequence)
    packet.setNumber(NumberFormat.UInt32LE, 4, event.timestampMs)
    packet.setUint8(8, event.eventCode)
    packet.setUint8(9, event.priority)
    packet.setUint8(10, event.repeatIndex)
    packet.setUint8(11, EVENT_REPEAT_TOTAL)
    packet.setUint8(12, HAND)
    packet.setNumber(NumberFormat.UInt16LE, 13, event.sequence ^ 0x5a5a)
    packet.setUint8(15, 0x7e)
    advertiseFrame(packet)
}

function priorityFor(eventCode: number): number {
    if (eventCode == EVENT_AB_LONG_PRESS) return 60
    if (HAND == 0) {
        if (eventCode == EVENT_A_SHORT_PRESS) return 40
        if (eventCode == EVENT_B_SHORT_PRESS) return 60
    } else {
        if (eventCode == EVENT_A_SHORT_PRESS) return 20
        if (eventCode == EVENT_B_LONG_PRESS) return 100
    }
    return -1
}

function emitControlEvent(eventCode: number, nowMs: number): void {
    const priority = priorityFor(eventCode)
    if (priority < 0) return

    if (pendingEvents.length >= EVENT_QUEUE_MAX) {
        pendingEvents.shift()
    }
    pendingEvents.push(new PendingEvent(
        eventSequence,
        nowMs,
        eventCode,
        priority,
        nowMs
    ))
    eventSequence = (eventSequence + 1) & 0xffff
}

function sendOneDueEventRepeat(nowMs: number): boolean {
    for (let i = 0; i < pendingEvents.length; i++) {
        const event = pendingEvents[i]
        if (nowMs >= event.nextDueMs) {
            advertiseControl(event)
            controlHoldUntilMs = nowMs + CONTROL_HOLD_MS
            event.repeatIndex += 1
            if (event.repeatIndex >= EVENT_REPEAT_TOTAL) {
                pendingEvents.removeAt(i)
            } else {
                event.nextDueMs = nowMs + EVENT_REPEAT_INTERVAL_MS
            }
            return true
        }
    }
    return false
}

function sendDueSensorRepeat(nowMs: number): boolean {
    if (!pendingSensor || nowMs < pendingSensor.nextRepeatMs) {
        return false
    }
    advertiseSensor(pendingSensor)
    pendingSensor.repeatIndex += 1
    if (pendingSensor.repeatIndex >= SENSOR_REPEAT_TOTAL) {
        pendingSensor = null
    } else {
        pendingSensor.nextRepeatMs = nowMs + SENSOR_REPEAT_INTERVAL_MS
    }
    return true
}

function startNewSensorSample(nowMs: number): void {
    pendingSensor = new PendingSensor(sampleSequence, nowMs, nowMs)
    sampleSequence = (sampleSequence + 1) & 0xffff
    sendDueSensorRepeat(nowMs)
}

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

function processButtonState(nowMs: number): void {
    if (!abActive && stableA && stableB) {
        abActive = true
        abPressStartMs = nowMs
        abLongReported = false
        bLongReported = true
    }

    if (abActive) {
        if (stableA && stableB && !abLongReported &&
            nowMs - abPressStartMs >= LONG_PRESS_MS) {
            emitControlEvent(EVENT_AB_LONG_PRESS, nowMs)
            abLongReported = true
        }
        if (!stableA && !stableB) {
            abActive = false
            abLongReported = false
            bLongReported = false
        }
        return
    }

    if (stableB && !bLongReported && nowMs - bPressStartMs >= LONG_PRESS_MS) {
        if (HAND == 1) {
            emitControlEvent(EVENT_B_LONG_PRESS, nowMs)
        }
        bLongReported = true
    }

    if (previousStableA && !stableA) {
        emitControlEvent(EVENT_A_SHORT_PRESS, nowMs)
    }
    if (previousStableB && !stableB && !bLongReported) {
        emitControlEvent(EVENT_B_SHORT_PRESS, nowMs)
    }
}

bluetooth.setTransmitPower(7)
input.setAccelerometerRange(AcceleratorRange.FourG)
basic.showString(HAND == 0 ? "L" : "R")

basic.forever(function () {
    const nowMs = input.runningTime()

    updateDebouncedButtons(nowMs)
    processButtonState(nowMs)

    const eventSent = sendOneDueEventRepeat(nowMs)
    const controlHeld = nowMs < controlHoldUntilMs
    if (!eventSent && !controlHeld && sendDueSensorRepeat(nowMs)) {
        // Keep the previous sample visible for one extra advertising window.
    } else if (!eventSent && !controlHeld && nowMs >= nextSampleDueMs) {
        startNewSensorSample(nowMs)
        nextSampleDueMs += SAMPLE_PERIOD_MS
        if (nowMs - nextSampleDueMs > SAMPLE_PERIOD_MS * 4) {
            nextSampleDueMs = nowMs + SAMPLE_PERIOD_MS
        }
    }

    previousStableA = stableA
    previousStableB = stableB
    basic.pause(10)
})
