import contextlib
import os
import threading
import time
import warnings

from gpiozero import AngularServo
from gpiozero.exc import BadPinFactory, PinFactoryFallback, PWMSoftwareFallback

# Pulse timing in seconds. The 1-2 ms range at a 20 ms frame (50 Hz) is the
# safe default for most hobby servos; adjust MIN/MAX if a servo needs a wider
# travel (e.g. 0.5-2.5 ms).
MIN_PULSE_WIDTH = 1 / 1000    # 1 ms  -> servo minimum position
MAX_PULSE_WIDTH = 2 / 1000    # 2 ms  -> servo maximum position
FRAME_WIDTH = 20 / 1000       # 20 ms frame = 50 Hz


class ServoInfo:
    def __init__(self, id: str, name: str, pin: int, min_angle: int,
                 max_angle: int, center: int | None = None):
        self.id = id
        self.name = name
        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.center = center if center is not None else (min_angle + max_angle) // 2

    def clamp(self, angle: int) -> int:
        return max(self.min_angle, min(self.max_angle, angle))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pin": self.pin,
            "min": self.min_angle,
            "max": self.max_angle,
            "center": self.center,
        }


DEFAULT_SERVOS = [
    ServoInfo("front_left_hip", "Front Left Hip", 17, 0, 180, 90),
    ServoInfo("front_left_knee", "Front Left Knee", 18, 0, 180, 90),
    ServoInfo("front_right_hip", "Front Right Hip", 22, 0, 180, 90),
    ServoInfo("front_right_knee", "Front Right Knee", 23, 0, 180, 90),
    ServoInfo("back_left_hip", "Back Left Hip", 24, 0, 180, 90),
    ServoInfo("back_left_knee", "Back Left Knee", 25, 0, 180, 90),
    ServoInfo("back_right_hip", "Back Right Hip", 26, 0, 180, 90),
    ServoInfo("back_right_knee", "Back Right Knee", 27, 0, 180, 90),
]


class ServoController:
    def __init__(self, servos: list[ServoInfo]):
        self._servos: dict[str, ServoInfo] = {s.id: s for s in servos}
        self._current_angles: dict[str, int] = {s.id: s.center for s in servos}
        self._target_angles: dict[str, int] = {s.id: s.center for s in servos}
        # gpiozero AngularServo device per servo id; None means the servo is
        # tracked in software only (dry-run mode, or its pin could not be
        # claimed by GPIO Zero).
        self._devices: dict[str, AngularServo | None] = {s.id: None for s in servos}
        self._dry_run = True
        self._lock = threading.RLock()
        self._init_hardware()

    def _init_hardware(self):
        """Create GPIO Zero devices for every configured servo.

        Falls back to dry-run mode (software-only angle tracking) when GPIO
        Zero cannot load a pin factory, e.g. when the server is running on a
        machine without Raspberry Pi GPIO support.
        """
        self._dry_run = False  # optimistically probe; BadPinFactory flips this back
        created = 0
        for servo in self._servos.values():
            if self._create_device(servo):
                created += 1
        if created == 0:
            self._dry_run = True
            print("ServoController: no GPIO devices created, running in dry-run mode")
        else:
            self._dry_run = False
            print(f"ServoController: gpiozero hardware mode active ({created} servos)")

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def servo_ids(self) -> list[str]:
        return list(self._servos.keys())

    def get_servo(self, servo_id: str) -> ServoInfo | None:
        return self._servos.get(servo_id)

    def get_all_servos(self) -> list[ServoInfo]:
        return list(self._servos.values())

    def update_servo_config(self, servo_id: str, **kwargs) -> bool:
        servo = self._servos.get(servo_id)
        if servo is None:
            return False
        old = (servo.pin, servo.min_angle, servo.max_angle, servo.center)
        for json_key, attr in (("min_angle", "min_angle"), ("min", "min_angle"),
                               ("max_angle", "max_angle"), ("max", "max_angle"),
                               ("center", "center"), ("name", "name"), ("pin", "pin")):
            if json_key in kwargs and kwargs[json_key] is not None:
                setattr(servo, attr, kwargs[json_key])
        if (servo.pin, servo.min_angle, servo.max_angle, servo.center) != old:
            # Recreate the GPIO Zero device so its angle range and pin match
            # the new configuration.
            device = self._devices.pop(servo_id, None)
            if device is not None:
                self._close_device(device)
            self._create_device(servo)
        return True

    def set_angle(self, servo_id: str, angle: int, immediate: bool = False):
        servo = self._servos.get(servo_id)
        if servo is None:
            return
        clamped = servo.clamp(angle)
        with self._lock:
            self._target_angles[servo_id] = clamped
            if immediate:
                self._current_angles[servo_id] = clamped
        if immediate:
            self._write_device(servo, clamped)

    def set_all_angles(self, angles: dict[str, int], immediate: bool = False):
        for servo_id, angle in angles.items():
            self.set_angle(servo_id, angle, immediate)

    def get_current_angle(self, servo_id: str) -> int | None:
        with self._lock:
            return self._current_angles.get(servo_id)

    def get_all_current_angles(self) -> dict[str, int]:
        with self._lock:
            return dict(self._current_angles)

    def get_all_target_angles(self) -> dict[str, int]:
        with self._lock:
            return dict(self._target_angles)

    def step(self, delta: float):
        speed = 180.0
        max_step = max(1.0, speed * delta)
        writes = []
        with self._lock:
            for servo_id, target in self._target_angles.items():
                current = self._current_angles[servo_id]
                if abs(target - current) <= max_step:
                    self._current_angles[servo_id] = target
                elif target > current:
                    self._current_angles[servo_id] = int(current + max_step)
                else:
                    self._current_angles[servo_id] = int(current - max_step)
                writes.append((self._servos[servo_id],
                               self._current_angles[servo_id]))
        for servo, angle in writes:
            self._write_device(servo, angle)

    def add_servo(self, servo: ServoInfo):
        with self._lock:
            if servo.id in self._servos:
                raise ValueError(f"Servo '{servo.id}' already exists")
            self._servos[servo.id] = servo
            self._current_angles[servo.id] = servo.center
            self._target_angles[servo.id] = servo.center
            self._devices[servo.id] = None
        if self._create_device(servo) and self._dry_run:
            # A device was created where previously there was none, so GPIO
            # hardware is genuinely available after all.
            self._dry_run = False

    def remove_servo(self, servo_id: str) -> bool:
        with self._lock:
            servo = self._servos.get(servo_id)
            if servo is None:
                return False
            device = self._devices.pop(servo_id, None)
            if device is not None:
                self._close_device(device)
            del self._servos[servo_id]
            self._current_angles.pop(servo_id, None)
            self._target_angles.pop(servo_id, None)
        return True

    def test_pin(self, pin: int):
        if self._dry_run:
            return
        # Temporarily release any configured servos on this pin so the probe
        # device can claim it; they are recreated afterwards.
        released = []
        with self._lock:
            for servo_id, device in self._devices.items():
                if device is not None and self._servos[servo_id].pin == pin:
                    released.append(servo_id)
                    self._close_device(device)
                    self._devices[servo_id] = None
        probe = None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", PinFactoryFallback)
                warnings.simplefilter("ignore", PWMSoftwareFallback)
                with open(os.devnull, "w") as null, \
                        contextlib.redirect_stdout(null), \
                        contextlib.redirect_stderr(null):
                    probe = AngularServo(
                        pin,
                        min_pulse_width=MIN_PULSE_WIDTH,
                        max_pulse_width=MAX_PULSE_WIDTH,
                        frame_width=FRAME_WIDTH,
                    )
            probe.min()
            time.sleep(0.5)
            probe.mid()
            time.sleep(0.5)
            probe.max()
            time.sleep(0.5)
        except Exception as e:
            print(f"ServoController: pin {pin} test failed: {e}")
        finally:
            if probe is not None:
                self._close_device(probe)
        with self._lock:
            for servo_id in released:
                self._create_device(self._servos[servo_id])

    def goto_idle(self, duration: float = 0.3):
        angles = {s_id: self._servos[s_id].center for s_id in self._servos}
        self.set_all_angles(angles)

    # ── GPIO Zero internals ────────────────────────────────

    def _create_device(self, servo: ServoInfo) -> bool:
        """Create (or refresh) the GPIO Zero device for a servo.

        Returns True if a hardware device now exists. Never raises: failures
        are logged and the servo is tracked in software only.
        """
        if self._dry_run:
            return False
        if servo.max_angle <= servo.min_angle:
            print(f"ServoController: servo '{servo.id}' has no valid angle "
                  "range, skipping hardware device")
            return False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", PinFactoryFallback)
                warnings.simplefilter("ignore", PWMSoftwareFallback)
                # GPIO Zero's factory probing can print noisy fallback banners
                # (e.g. pigpio connection attempts) to the console on machines
                # without Pi GPIO support; keep the server log clean.
                with open(os.devnull, "w") as null, \
                        contextlib.redirect_stdout(null), \
                        contextlib.redirect_stderr(null):
                    device = AngularServo(
                        servo.pin,
                        min_angle=servo.min_angle,
                        max_angle=servo.max_angle,
                        initial_angle=servo.center,
                        min_pulse_width=MIN_PULSE_WIDTH,
                        max_pulse_width=MAX_PULSE_WIDTH,
                        frame_width=FRAME_WIDTH,
                    )
        except BadPinFactory as e:
            self._dry_run = True
            self._teardown_devices()
            print(f"ServoController: gpiozero unavailable ({e}), "
                  "running in dry-run mode")
            return False
        except Exception as e:
            print(f"ServoController: servo '{servo.id}' (pin {servo.pin}) "
                  f"unavailable: {e}")
            return False
        self._devices[servo.id] = device
        return True

    def _write_device(self, servo: ServoInfo, angle: int):
        device = self._devices.get(servo.id)
        if device is None:
            return
        try:
            device.angle = angle
        except Exception:
            pass

    @staticmethod
    def _close_device(device: AngularServo):
        try:
            device.detach()
        except Exception:
            pass
        try:
            device.close()
        except Exception:
            pass

    def _teardown_devices(self):
        with self._lock:
            for servo_id, device in self._devices.items():
                if device is not None:
                    self._close_device(device)
                    self._devices[servo_id] = None

    def shutdown(self):
        with self._lock:
            for device in self._devices.values():
                if device is not None:
                    self._close_device(device)
            self._devices.clear()
