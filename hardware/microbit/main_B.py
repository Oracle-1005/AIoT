"""
Micro:bit V2 Accelerometer Firmware (USB Serial)
=================================================
Outputs accelerometer data at ~50Hz over USB Serial (CDC).

Data format: "A,acc_x,acc_y,acc_z,running_time_ms\n"
Set DEVICE_ID = "B" for the second micro:bit.
"""

from microbit import *

DEVICE_ID = "B"
SAMPLE_RATE_HZ = 50
SAMPLE_INTERVAL = 1000 // SAMPLE_RATE_HZ

display.show(Image.HEART)
sleep(500)
display.clear()

last_sample = 0
sample_count = 0

while True:
    now = running_time()
    if now - last_sample >= SAMPLE_INTERVAL:
        last_sample = now
        x = accelerometer.get_x()
        y = accelerometer.get_y()
        z = accelerometer.get_z()

        # Output: use format() instead of f-string for compat
        print("{},{},{},{},{}".format(DEVICE_ID, x, y, z, now))

        sample_count += 1
        if sample_count % 50 == 0:
            display.set_pixel(2, 2, 9)
        else:
            display.set_pixel(2, 2, 0)

    sleep(1)
