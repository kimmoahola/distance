import datetime
import sqlite3
import pytz

import RPi.GPIO as GPIO
import time
import argparse
import smtplib
from email.mime.text import MIMEText
from collections import Counter
import warnings


REPORT_DISTANCES = [
    {
        'name': 'Sähköpumppu',
        'empty_distance_from_celling_cm': 352,
    },
    {
        'name': 'Käsipumppu',
        'empty_distance_from_celling_cm': 372,
    },
]


SENSOR_FROM_CELLING_CM = 120
FULL_DISTANCE_FROM_CELLING_CM = 125

SENSOR_CALIBRATION = -4  # Kun mitattu etäisyys on 232 cm

GPIO_TRIGGER = 15
GPIO_ECHO = 14
TRIGGER_TIME = 0.00001
MAX_TIME = 0.04  # max time waiting for response in case something is missed


def get_now():
    return datetime.datetime.utcnow().replace(tzinfo=pytz.utc, microsecond=0)


def setup_measure():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        GPIO.cleanup()

    # Define GPIO to use on Pi
    GPIO.setmode(GPIO.BCM)

    GPIO.setup(GPIO_TRIGGER, GPIO.OUT)  # Trigger
    GPIO.setup(GPIO_ECHO, GPIO.IN)
    # GPIO.setup(GPIO_ECHO, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Echo

    GPIO.output(GPIO_TRIGGER, False)

    time.sleep(0.5)


def measure():
    """
    Returns a distance in centimeters.
    """

    # Pulse the trigger/echo line to initiate a measurement
    GPIO.output(GPIO_TRIGGER, True)
    time.sleep(TRIGGER_TIME)
    GPIO.output(GPIO_TRIGGER, False)

    distance = -1

    start = time.time()
    timeout = start + MAX_TIME
    while GPIO.input(GPIO_ECHO) == 0 and start <= timeout:
        start = time.time()

    if start <= timeout:
        wait_result = GPIO.wait_for_edge(GPIO_ECHO, GPIO.FALLING, timeout=int(MAX_TIME*1000))
        stop = time.time()
        if wait_result:
            elapsed = stop - start
            distance = elapsed * 34300.0 / 2.0
#            distance = int(round(elapsed * 34300.0 / 2.0))
    #     else:
    #         print('timeout 2')
    # else:
    #     print('timeout 1')

    return distance


def read_n_and_take_middle_value(n):
    setup_measure()

    readings = []

    for i in range(n):
        if i > 0:
            # Sleep only between reads
            time.sleep(0.06)
        reading = measure()
        if reading > -1:
            readings.append(reading)

    if len(readings) < n:
        print('Warning: %d timeouts occurred' % (n - len(readings)))

    readings = sorted(readings)

    # Take the middle value
    if len(readings) > 0:
#        c = Counter()
#        for r in readings:
#            for e in list(c):
#                print(r, e)
#                if e*0.9 <= r <= e*1.1:
#                    c.update([e])
#                else:
#                    c.update([r])
#            else:
#                c.update([r])
#        print(c.most_common(5))
#        print(Counter(readings).most_common(5))
        # print(list(map(lambda x: int(round(x)), readings)))

        throw_away = int(len(readings) * 0.2)
        if throw_away > 0:
            readings = readings[throw_away:-throw_away]
        # print(list(map(lambda x: int(round(x)), readings)))
        if readings:
            return max(readings)
            # return sum(readings) / len(readings)
        else:
            return -1

#        return max(readings)
        # return readings[len(readings)//2]
    else:
        return -1


def send_email(address, mime_text):
    s = smtplib.SMTP('localhost')
    s.sendmail(address, [address], mime_text.as_string())
    s.quit()


def email(addresses, subject, message):

    for address in addresses:

        mime_text = MIMEText(message.encode('utf-8'), 'plain', 'utf-8')
        mime_text['Subject'] = subject
        mime_text['From'] = address
        mime_text['To'] = address

        send_email(address, mime_text)


def result_str(distance, calibrated, water_level):
    if distance > -1:
        msg = ''

        for report_distance in REPORT_DISTANCES:
            water_remaining_cm = report_distance['empty_distance_from_celling_cm'] - SENSOR_FROM_CELLING_CM - calibrated
            water_liters = water_remaining_cm / 100 * 3.1415 * 0.4 * 0.4 * 1000
            percentage = water_remaining_cm / (
                    report_distance['empty_distance_from_celling_cm'] - FULL_DISTANCE_FROM_CELLING_CM) * 100

            msg += '\nReport name: %s. Water remaining = %.1f cm = %.1f liters = %d%% from full.' % (
                report_distance['name'], water_remaining_cm, water_liters, percentage
            )

        return "Measured Distance = %.1f cm. Calibrated = %.1f cm. Water level = %.1f cm. %s\n" % (
            distance, calibrated, water_level, msg)
    else:
        return "No distance"


def init_sqlite(c, table_name):
    c.execute("""CREATE TABLE IF NOT EXISTS %s
                  (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      ts DATETIME NOT NULL,
                      water_level DECIMAL(6,2) NOT NULL
                  )""" % table_name)


def write_to_sqlite(file_name, table_name, ts, water_level):
    conn = sqlite3.connect(file_name)
    c = conn.cursor()

    init_sqlite(c, table_name)

    c.execute('INSERT INTO %s (ts, water_level) VALUES (?, ?)' % table_name, (ts, water_level))

    conn.commit()
    conn.close()


def calc_water_level(distance):
    if distance > -1:
        calibrated = distance + SENSOR_CALIBRATION
        water_level = -calibrated - SENSOR_FROM_CELLING_CM
    else:
        calibrated = 0
        water_level = 0

    return calibrated, water_level


def main():

    parser = argparse.ArgumentParser(description='Read distance')
    parser.add_argument('--address', type=str, required=False, action='append',
                        help='Email address to send alerts. --address can be given multiple times.')
    args = parser.parse_args()

    distance = read_n_and_take_middle_value(1000)
    GPIO.cleanup()
    calibrated, water_level = calc_water_level(distance)
    write_to_sqlite('db.sqlite', 'water_level', get_now(), water_level)

    if args.address:
        email(args.address, 'Distance', result_str(distance, calibrated, water_level))

    # else:
    #     try:
    #         while True:
    #             distance = read_n_and_take_middle_value(300)
    #             calibrated, water_level = calc_water_level(distance)
    #             print(result_str(distance, calibrated, water_level))
    #             time.sleep(5)
    #     except KeyboardInterrupt:
    #         GPIO.cleanup()


if __name__ == '__main__':
    main()
