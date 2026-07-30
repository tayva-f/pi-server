from flask import Flask, Response, render_template, request, jsonify
from flask_socketio import SocketIO
import cv2
import time
import sounddevice as sd

from robot.servo import ServoController, ServoInfo, DEFAULT_SERVOS
from robot.animation import Animation, AnimationPlayer
from robot.keymapper import KeyMapper
from robot import storage

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

cam = cv2.VideoCapture(1)
if not cam.isOpened():
    cam = cv2.VideoCapture(0)

output = None
try:
    output = sd.RawOutputStream(
        samplerate=48000,
        channels=1,
        dtype="int16",
    )
    output.start()
except Exception as e:
    print(f"Audio output not available: {e}")

servo_config_data = storage.load_servo_config()
servos = [
    ServoInfo(
        id=sid,
        name=cfg["name"],
        pin=cfg["pin"],
        min_angle=cfg["min"],
        max_angle=cfg["max"],
        center=cfg["center"],
    )
    for sid, cfg in servo_config_data.items()
]
controller = ServoController(servos)

player = AnimationPlayer(controller)

animations: dict[str, Animation] = {}
anim_data = storage.load_animations()
for a in anim_data:
    anim = Animation.from_dict(a)
    animations[anim.name] = anim

settings = storage.load_settings()
if settings.get("idle_animation") in animations:
    player.set_idle_animation(animations[settings["idle_animation"]])
if settings.get("paused"):
    player.set_paused(True)

bindings_data = storage.load_key_bindings()

def on_play(anim_name: str):
    anim = animations.get(anim_name)
    if anim:
        player.play(anim)

def on_stop():
    player.stop_playback(return_to_idle=True)

keymapper = KeyMapper(bindings_data, on_play, on_stop)


def on_player_state(state: str, anim_name: str | None, paused: bool = False):
    socketio.emit("robot_state", {
        "state": state,
        "animation": anim_name,
        "paused": paused,
    })


player.set_state_callback(on_player_state)

player.start()


def get_webcam_image():
    global cam
    while True:
        time.sleep(1 / 60)
        ok, img = cam.read()
        if not ok:
            time.sleep(0.5)
            continue
        try:
            _, frame = cv2.imencode(".jpg", img)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame.tobytes() + b'\r\n')
        except cv2.error:
            time.sleep(0.5)


@app.route("/camera")
def camera():
    return Response(get_webcam_image(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/")
def index():
    return render_template("index.html")


# ── Servo API ──────────────────────────────────────────────

@app.get("/api/servos")
def get_servos():
    srv_list = [s.to_dict() for s in controller.get_all_servos()]
    angles = controller.get_all_current_angles()
    for s in srv_list:
        s["current_angle"] = angles.get(s["id"], s["center"])
    return jsonify(srv_list)


@app.post("/api/servos/<servo_id>/angle")
def set_servo_angle(servo_id: str):
    data = request.get_json()
    if data is None or "angle" not in data:
        return jsonify({"error": "Missing 'angle'"}), 400
    controller.set_angle(servo_id, int(data["angle"]), immediate=True)
    return jsonify({"success": True})


@app.post("/api/servos/<servo_id>/config")
def update_servo_config(servo_id: str):
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Missing body"}), 400
    ok = controller.update_servo_config(servo_id, **data)
    if not ok:
        return jsonify({"error": "Servo not found"}), 404
    _save_servo_config()
    return jsonify({"success": True})


@app.post("/api/servos")
def create_servo():
    data = request.get_json()
    if data is None or "name" not in data or "pin" not in data:
        return jsonify({"error": "Missing 'name' and 'pin' fields"}), 400
    servo_id = data.get("id") or data["name"].lower().replace(" ", "_")
    try:
        pin = int(data["pin"])
    except (ValueError, TypeError):
        return jsonify({"error": "Pin must be an integer"}), 400
    info = ServoInfo(
        id=servo_id,
        name=data["name"],
        pin=pin,
        min_angle=int(data.get("min", 0)),
        max_angle=int(data.get("max", 180)),
        center=int(data.get("center", 90)),
    )
    try:
        controller.add_servo(info)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    _save_servo_config()
    return jsonify(info.to_dict()), 201


@app.delete("/api/servos/<servo_id>")
def delete_servo(servo_id: str):
    ok = controller.remove_servo(servo_id)
    if not ok:
        return jsonify({"error": "Servo not found"}), 404
    _save_servo_config()
    return jsonify({"success": True})


@app.post("/api/servos/<servo_id>/test")
def test_servo(servo_id: str):
    servo = controller.get_servo(servo_id)
    if servo is None:
        return jsonify({"error": "Servo not found"}), 404
    player.stop_playback(return_to_idle=True)
    def _sweep():
        time.sleep(0.1)
        controller.set_angle(servo_id, servo.min_angle, immediate=True)
        time.sleep(0.5)
        mid = (servo.min_angle + servo.max_angle) // 2
        controller.set_angle(servo_id, mid, immediate=True)
        time.sleep(0.5)
        controller.set_angle(servo_id, servo.max_angle, immediate=True)
        time.sleep(0.5)
        controller.set_angle(servo_id, servo.center, immediate=True)
    import threading
    threading.Thread(target=_sweep, daemon=True).start()
    return jsonify({"success": True})


@app.post("/api/servo-pin/test")
def test_pin():
    data = request.get_json()
    if data is None or "pin" not in data:
        return jsonify({"error": "Missing 'pin'"}), 400
    try:
        pin = int(data["pin"])
    except (ValueError, TypeError):
        return jsonify({"error": "Pin must be an integer"}), 400
    player.stop_playback(return_to_idle=True)
    import threading
    threading.Thread(target=lambda: controller.test_pin(pin), daemon=True).start()
    return jsonify({"success": True})


def _save_servo_config():
    config = {}
    for s in controller.get_all_servos():
        config[s.id] = {"pin": s.pin, "min": s.min_angle, "max": s.max_angle,
                        "center": s.center, "name": s.name}
    storage.save_servo_config(config)


# ── Animation API ──────────────────────────────────────────

@app.get("/api/animations")
def get_animations():
    result = []
    for name, anim in animations.items():
        d = anim.to_dict()
        d["keyframe_count"] = len(anim.keyframes)
        result.append(d)
    return jsonify(result)


@app.post("/api/animations")
def create_animation():
    data = request.get_json()
    if data is None or "name" not in data:
        return jsonify({"error": "Missing 'name'"}), 400
    name = data["name"]
    if name in animations:
        return jsonify({"error": "Animation already exists"}), 409
    anim = Animation.from_dict(data)
    animations[name] = anim
    _save_animations()
    return jsonify(anim.to_dict()), 201


@app.get("/api/animations/<name>")
def get_animation(name: str):
    anim = animations.get(name)
    if anim is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(anim.to_dict())


@app.put("/api/animations/<name>")
def update_animation(name: str):
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Missing body"}), 400
    anim = Animation.from_dict(data)
    anim.name = name
    if name not in animations:
        return jsonify({"error": "Not found"}), 404
    animations[name] = anim
    _save_animations()
    return jsonify(anim.to_dict())


@app.delete("/api/animations/<name>")
def delete_animation(name: str):
    if name not in animations:
        return jsonify({"error": "Not found"}), 404
    del animations[name]
    _save_animations()
    return jsonify({"success": True})


@app.post("/api/animations/<name>/preview")
def preview_animation(name: str):
    anim = animations.get(name)
    if anim is None:
        return jsonify({"error": "Not found"}), 404
    player.play(anim)
    return jsonify({"success": True})


@app.post("/api/animations/stop")
def stop_animation():
    player.stop_playback(return_to_idle=True)
    return jsonify({"success": True})


# ── Key Bindings API ───────────────────────────────────────

@app.get("/api/bindings")
def get_bindings():
    return jsonify(keymapper.bindings)


@app.put("/api/bindings")
def update_bindings():
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Missing body"}), 400
    keymapper.update_bindings(data)
    storage.save_key_bindings(data)
    return jsonify({"success": True})


# ── Key Input ──────────────────────────────────────────────

@app.post("/keydown")
def keydown():
    key = request.form.get("key", "")
    keymapper.handle_keydown(key)
    return jsonify({"success": True})


@app.post("/keyup")
def keyup():
    key = request.form.get("key", "")
    keymapper.handle_keyup(key)
    return jsonify({"success": True})


# ── Settings API ───────────────────────────────────────────

@app.get("/api/idle-animation")
def get_idle_animation():
    return jsonify({"name": player.idle_animation_name})


@app.post("/api/idle-animation")
def set_idle_animation():
    data = request.get_json()
    if data is None:
        return jsonify({"error": "Missing body"}), 400
    name = data.get("name")
    if name is None:
        player.set_idle_animation(None)
    elif name not in animations:
        return jsonify({"error": "Animation not found"}), 404
    else:
        player.set_idle_animation(animations[name])
    _save_settings()
    return jsonify({"success": True})


@app.get("/api/animation-paused")
def get_animation_paused():
    return jsonify({"paused": player.paused})


@app.post("/api/animation-paused")
def set_animation_paused():
    data = request.get_json()
    if data is None or "paused" not in data:
        return jsonify({"error": "Missing 'paused'"}), 400
    player.set_paused(bool(data["paused"]))
    _save_settings()
    return jsonify({"success": True})


@socketio.on("audio")
def receive_audio(data):
    if output is None:
        return
    try:
        output.write(data)
    except Exception as e:
        print(f"Audio playback error: {e}")


@socketio.on("keydown")
def on_keydown(data):
    key = data.get("key", "")
    keymapper.handle_keydown(key)


@socketio.on("keyup")
def on_keyup(data):
    key = data.get("key", "")
    keymapper.handle_keyup(key)


@socketio.on("servo_set")
def on_servo_set(data):
    servo_id = data.get("id")
    angle = data.get("angle")
    if servo_id and angle is not None:
        controller.set_angle(servo_id, int(angle), immediate=True)


@socketio.on("connect")
def on_connect():
    socketio.emit("robot_state", {
        "state": "playing" if player.active_animation else "idle",
        "animation": player.active_animation or player.idle_animation_name,
        "paused": player.paused,
    })


def _save_animations():
    storage.save_animations([a.to_dict() for a in animations.values()])


def _save_settings():
    storage.save_settings({
        "idle_animation": player.idle_animation_name,
        "paused": player.paused,
    })


def main():
    print("Starting pi-server...")


if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=3000)
