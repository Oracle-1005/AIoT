/*
 * micro:bit Radio -> USB serial gateway.
 *
 * This receiver is transport-only: it forwards each radio payload without
 * interpreting wearable sensor fields. That keeps the USB gateway independent
 * from later sensor packet revisions.
 *
 * USB output (115200 baud):
 *   GW1,<gateway_rx_ms>,<rssi_dbm>,<radio_serial>,<payload_hex>
 */

const RADIO_GROUP = 79
const SERIAL_BAUD = BaudRate.BaudRate115200
const PROTOCOL_TAG = "GW1"

let receivedCount = 0
let activityLed = false

function nibbleToHex(value: number): string {
    if (value < 10) {
        return String.fromCharCode(48 + value)
    }
    return String.fromCharCode(55 + value)
}

function bufferToHex(payload: Buffer): string {
    let result = ""
    for (let i = 0; i < payload.length; i++) {
        const value = payload.getUint8(i)
        result += nibbleToHex((value >> 4) & 0x0f)
        result += nibbleToHex(value & 0x0f)
    }
    return result
}

function showGatewayReady(): void {
    basic.clearScreen()
    led.plot(0, 0)
    led.plot(0, 1)
    led.plot(0, 2)
    led.plot(0, 3)
    led.plot(0, 4)
    led.plot(1, 0)
    led.plot(2, 0)
    led.plot(1, 4)
    led.plot(2, 4)
    led.plot(2, 2)
    led.plot(2, 3)
}

serial.redirectToUSB()
serial.setBaudRate(SERIAL_BAUD)
serial.setTxBufferSize(254)
serial.setWriteLinePadding(0)

radio.setGroup(RADIO_GROUP)
radio.setTransmitPower(7)
radio.setTransmitSerialNumber(true)

showGatewayReady()
serial.writeLine(PROTOCOL_TAG + ",READY," + RADIO_GROUP)

radio.onReceivedBuffer(function (payload: Buffer) {
    const gatewayRxMs = input.runningTime()
    const rssi = radio.receivedPacket(RadioPacketProperty.SignalStrength)
    const senderSerial = radio.receivedPacket(RadioPacketProperty.SerialNumber)

    serial.writeLine(
        PROTOCOL_TAG + "," +
        gatewayRxMs + "," +
        rssi + "," +
        senderSerial + "," +
        bufferToHex(payload)
    )

    receivedCount += 1
    activityLed = !activityLed
    if (activityLed) {
        led.plot(4, 4)
    } else {
        led.unplot(4, 4)
    }
})

input.onButtonPressed(Button.A, function () {
    serial.writeLine(
        PROTOCOL_TAG + ",STATUS," +
        input.runningTime() + "," +
        receivedCount + "," +
        RADIO_GROUP
    )
})
