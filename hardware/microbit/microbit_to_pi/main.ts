/*
 * Wearable micro:bit -> Radio -> USB gateway sender.
 *
 * The 17-byte sensor packet and 11-byte control packet are identical to the
 * protocol previously reconstructed by the ESP32 gateway. Keeping that wire
 * format lets the Raspberry Pi reuse parsing, filtering, fusion and backend
 * output unchanged.
 */

// 0 = left hand, 1 = right hand. Change to 1 before flashing the right board.
const HAND: number = 0

const RADIO_GROUP = 79
// Different coprime periods prevent two independently booted wearables from
// remaining phase-locked and repeatedly colliding on the same radio slots.
const SAMPLE_PERIOD_MS = HAND == 0 ? 47 : 53
const SENSOR_REPEAT_TOTAL = 2
const SENSOR_REPEAT_INTERVAL_MS = 15

const DEBOUNCE_MS = 60
const LONG_PRESS_MS = 1000
const EVENT_REPEAT_TOTAL = 7
const EVENT_REPEAT_INTERVAL_MS = 40
const EVENT_QUEUE_MAX = 8

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

function sendFrame(packet: Buffer): void {
    radio.sendBuffer(packet)
}

function sendSensor(sample: PendingSensor): void {
    const packet = pins.createBuffer(17)
    packet.setUint8(0, makeHeader(MESSAGE_SENSOR_STATE))
    packet.setNumber(NumberFormat.UInt16LE, 1, sample.sequence)
    packet.setNumber(NumberFormat.UInt32LE, 3, sample.timestampMs)
    packet.setNumber(NumberFormat.Int16LE, 7, sample.axMg)
    packet.setNumber(NumberFormat.Int16LE, 9, sample.ayMg)
    packet.setNumber(NumberFormat.Int16LE, 11, sample.azMg)
    packet.setNumber(NumberFormat.Int16LE, 13, sample.pitchDeg)
    packet.setNumber(NumberFormat.Int16LE, 15, sample.rollDeg)
    sendFrame(packet)
}

function sendControl(event: PendingEvent): void {
    const packet = pins.createBuffer(11)
    packet.setUint8(0, makeHeader(MESSAGE_CONTROL_EVENT))
    packet.setNumber(NumberFormat.UInt16LE, 1, event.sequence)
    packet.setNumber(NumberFormat.UInt32LE, 3, event.timestampMs)
    packet.setUint8(7, event.eventCode)
    packet.setUint8(8, event.priority)
    packet.setUint8(9, event.repeatIndex)
    packet.setUint8(10, EVENT_REPEAT_TOTAL)
    sendFrame(packet)
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
            sendControl(event)
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
    sendSensor(pendingSensor)
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

radio.setGroup(RADIO_GROUP)
radio.setTransmitPower(7)
radio.setTransmitSerialNumber(true)
input.setAccelerometerRange(AcceleratorRange.FourG)
basic.showString(HAND == 0 ? "L" : "R")

basic.forever(function () {
    const nowMs = input.runningTime()

    updateDebouncedButtons(nowMs)
    processButtonState(nowMs)

    const eventSent = sendOneDueEventRepeat(nowMs)
    if (!eventSent && sendDueSensorRepeat(nowMs)) {
        // Send at most one radio packet per loop iteration.
    } else if (!eventSent && nowMs >= nextSampleDueMs) {
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
