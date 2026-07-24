from flask import Flask, render_template, request, jsonify
from monitor import start_monitor, stop_monitor
import threading

app = Flask(__name__)

monitor_thread = None

alarm_data = {
    "active": False,
    "station": "",
    "destination": "",
    "train": "",
    "history": []
}

stats = {
    "today": 0,
    "total": 0
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():

    global monitor_thread

    station = request.form["station"]
    destination = request.form["destination"]
    train = request.form["train"]

    stop_monitor()

    monitor_thread = threading.Thread(
        target=start_monitor,
        args=(station, destination, train, alarm_data),
        daemon=True
    )

    monitor_thread.start()

    return render_template(
        "index.html",
        message="監視開始しました"
    )


@app.route("/stop", methods=["POST"])
def stop():

    stop_monitor()

    alarm_data["active"] = False

    return render_template(
        "index.html",
        message="監視停止しました"
    )


@app.route("/status")
def status():
    return jsonify(alarm_data)


@app.route("/history")
def history():

    stats["today"] = len(alarm_data["history"])
    stats["total"] = len(alarm_data["history"])

    return jsonify(alarm_data["history"])


@app.route("/stats")
def get_stats():

    stats["today"] = len(alarm_data["history"])
    stats["total"] = len(alarm_data["history"])

    return jsonify(stats)


@app.route("/ack", methods=["POST"])
def ack():

    alarm_data["active"] = False

    return "OK"


@app.route("/test", methods=["POST"])
def test():

    alarm_data["active"] = True
    alarm_data["station"] = "木場"
    alarm_data["destination"] = "東陽町"
    alarm_data["train"] = "TEST123"

    alarm_data["history"].insert(0, {
        "time": "TEST",
        "station": "木場",
        "destination": "東陽町",
        "train": "TEST123"
    })

    alarm_data["history"] = alarm_data["history"][:100]

    return "OK"


if __name__ == "__main__":
    app.run(debug=True)