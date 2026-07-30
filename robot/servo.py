import time
import threading
from typing import Optional


class ServoInfo:
    def __init__(self, id: str, name: str, pin: int, min_angle: int,
                 max_angle: int, center: Optional[int] = None):
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
        self._chip = -1
        self._dry_run = True
        self._lock = threading.Lock()
        self._init_hardware()

    def _init_hardware(self):
        try:
            import lgpio  # type: ignore
            h = lgpio.gpiochip_open(0)
            if h < 0:
                raise OSError(f"gpiochip_open failed with error {h}")
            self._chip = h
            self._dry_run = False
            print("ServoController: lgpio gpiochip0 opened, hardware mode active")
        except Exception as e:
            self._chip = -1
            self._dry_run = True
            print(f"ServoController: lgpio not available ({e}), running in dry-run mode")

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def servo_ids(self) -> list[str]:
        return list(self._servos.keys())

    def get_servo(self, servo_id: str) -> Optional[ServoInfo]:
        return self._servos.get(servo_id)

    def get_all_servos(self) -> list[ServoInfo]:
        return list(self._servos.values())

    def update_servo_config(self, servo_id: str, **kwargs) -> bool:
        servo = self._servos.get(servo_id)
        if servo is None:
            return False
        for json_key, attr in (("min_angle", "min_angle"), ("min", "min_angle"),
                               ("max_angle", "max_angle"), ("max", "max_angle"),
                               ("center", "center"), ("name", "name"), ("pin", "pin")):
            if json_key in kwargs and kwargs[json_key] is not None:
                setattr(servo, attr, kwargs[json_key])
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
            self._set_hardware(servo, clamped)

    def set_all_angles(self, angles: dict[str, int], immediate: bool = False):
        for servo_id, angle in angles.items():
            self.set_angle(servo_id, angle, immediate)

    def get_current_angle(self, servo_id: str) -> Optional[int]:
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
            self._set_hardware(servo, angle)

    def add_servo(self, servo: ServoInfo):
        with self._lock:
            if servo.id in self._servos:
                raise ValueError(f"Servo '{servo.id}' already exists")
            self._servos[servo.id] = servo
            self._current_angles[servo.id] = servo.center
            self._target_angles[servo.id] = servo.center
        self._set_hardware(servo, servo.center)

    def remove_servo(self, servo_id: str) -> bool:
        with self._lock:
            servo = self._servos.get(servo_id)
            if servo is None:
                return False
            self._stop_pin(servo.pin)
            del self._servos[servo_id]
            self._current_angles.pop(servo_id, None)
            self._target_angles.pop(servo_id, None)
        return True

    def test_pin(self, pin: int):
        if self._dry_run or self._chip < 0:
            return
        import lgpio  # type: ignore
        try:
            lgpio.tx_pwm(self._chip, pin, 50.0, ServoController._angle_to_duty(0))
            time.sleep(0.5)
            lgpio.tx_pwm(self._chip, pin, 50.0, ServoController._angle_to_duty(90))
            time.sleep(0.5)
            lgpio.tx_pwm(self._chip, pin, 50.0, ServoController._angle_to_duty(180))
            time.sleep(0.5)
            lgpio.tx_pwm(self._chip, pin, 0, 0)
        except Exception as e:
            print(f"ServoController: pin {pin} test failed: {e}")

    def goto_idle(self, duration: float = 0.3):
        angles = {s_id: self._servos[s_id].center for s_id in self._servos}
        self.set_all_angles(angles)

    def _set_hardware(self, servo: ServoInfo, angle: int):
        if self._dry_run or self._chip < 0:
            return
        import lgpio  # type: ignore
        try:
            duty = ServoController._angle_to_duty(angle)
            lgpio.tx_pwm(self._chip, servo.pin, 50.0, duty)
        except Exception:
            pass

    def _stop_pin(self, pin: int):
        if self._dry_run or self._chip < 0:
            return
        import lgpio  # type: ignore
        try:
            lgpio.tx_pwm(self._chip, pin, 0, 0)
        except Exception:
            pass

    @staticmethod
    def _angle_to_duty(angle: int) -> int:
        pulse_us = 500 + (angle / 180.0) * 2000
        return int(pulse_us * 50)

    def shutdown(self):
        for servo in self._servos.values():
            self._stop_pin(servo.pin)
        if self._chip >= 0:
            import lgpio  # type: ignore
            try:
                lgpio.gpiochip_close(self._chip)
            except Exception:
                pass
            self._chip = -1
