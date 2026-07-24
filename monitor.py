import requests
import time
import csv
import os
from datetime import datetime

running = False

URL = "https://nkth.info/traffic_info/ODPT/now?line=TokyoMetro_Tozai"

# 通知済み列車
notified_trains = set()


def save_csv(station, destination, train):

    filename = "history.csv"

    new_file = not os.path.exists(filename)

    with open(filename, "a", newline="", encoding="utf-8-sig") as f:

        writer = csv.writer(f)

        if new_file:
            writer.writerow([
                "日時",
                "駅",
                "行先",
                "列番"
            ])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            station,
            destination,
            train
        ])


def start_monitor(station, destination, train, alarm_data):

    global running
    global notified_trains

    running = True

    while running:

        try:

            response = requests.get(URL, timeout=10)
            data = response.json()

            trains = data.get("noRunning", [])

            current_trains = set()

            for t in trains:

                # 行先判定
                if destination:
                    if t.get("destination") != destination:
                        continue

                # 列番判定
                if train:
                    if t.get("number") != train:
                        continue

                # 現在位置判定
                now = t.get("now", [])

                if station not in now:
                    continue

                number = t.get("number", "")

                current_trains.add(number)

                # 同じ列車は一度だけ通知
                if number in notified_trains:
                    continue

                notified_trains.add(number)

                print(f"🚨 検知 : {number}")

                alarm_data["active"] = True
                alarm_data["station"] = station
                alarm_data["destination"] = t.get("destination", "")
                alarm_data["train"] = number

                alarm_data["history"].insert(0, {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "station": station,
                    "destination": t.get("destination", ""),
                    "train": number
                })

                # 最大100件保存
                alarm_data["history"] = alarm_data["history"][:100]

                # CSV保存
                save_csv(
                    station,
                    t.get("destination", ""),
                    number
                )

            # 駅から離れた列車は再通知可能にする
            notified_trains.intersection_update(current_trains)

        except Exception as e:

            print("Monitor Error:", e)

        time.sleep(2)


def stop_monitor():

    global running
    global notified_trains

    running = False
    notified_trains.clear()