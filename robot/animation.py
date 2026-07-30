import time
import threading
from typing import Optional, Callable

from robot.servo import ServoController


class Keyframe:
    def __init__(self, id: str, time_ms: float, angles: dict[str, int]):
        self.id = id
        self.time_ms = time_ms
        self.angles = angles

    def to_dict(self) -> dict:
        return {"id": self.id, "time": self.time_ms, "angles": self.angles}

    @classmethod
    def from_dict(cls, data: dict) -> "Keyframe":
        return cls(data["id"], data["time"], data["angles"])


class Animation:
    def __init__(self, name: str, loop: bool = True,
                 duration_ms: float = 2000,
                 keyframes: Optional[list[Keyframe]] = None):
        self.name = name
        self.loop = loop
        self.duration_ms = duration_ms
        self._raw_keyframes = keyframes or []
        self._sorted_keyframes: list[Keyframe] = sorted(
            self._raw_keyframes, key=lambda k: k.time_ms
        )

    @property
    def keyframes(self) -> list[Keyframe]:
        return self._raw_keyframes

    @keyframes.setter
    def keyframes(self, value: list[Keyframe]):
        self._raw_keyframes = value
        self._sorted_keyframes = sorted(value, key=lambda k: k.time_ms)

    def total_duration(self) -> float:
        if not self._sorted_keyframes:
            return self.duration_ms
        return max(self._sorted_keyframes[-1].time_ms, self.duration_ms)

    def sorted_keyframes(self) -> list[Keyframe]:
        return self._sorted_keyframes

    def interpolate(self, elapsed_ms: float, servo_centers: dict[str, int] | None = None) -> dict[str, int]:
        if not self._sorted_keyframes:
            return {}
        centers = servo_centers or {}
        first = self._sorted_keyframes[0]
        last = self._sorted_keyframes[-1]
        dur = self.total_duration()
        if dur <= 0:
            return dict(first.angles)
        t = elapsed_ms % dur if self.loop else min(elapsed_ms, dur)
        if t <= first.time_ms:
            return dict(first.angles)
        if t >= last.time_ms:
            if self.loop and dur > last.time_ms:
                ratio = (t - last.time_ms) / (dur - last.time_ms)
            else:
                return dict(last.angles)
            result = {}
            all_ids = set(last.angles.keys()) | set(first.angles.keys())
            for servo_id in all_ids:
                va = last.angles.get(servo_id, centers.get(servo_id, 90))
                vb = first.angles.get(servo_id, centers.get(servo_id, 90))
                result[servo_id] = int(va + (vb - va) * ratio)
            return result
        for i in range(len(self._sorted_keyframes) - 1):
            a, b = self._sorted_keyframes[i], self._sorted_keyframes[i + 1]
            if a.time_ms <= t <= b.time_ms:
                if b.time_ms == a.time_ms:
                    return dict(a.angles)
                ratio = (t - a.time_ms) / (b.time_ms - a.time_ms)
                result = {}
                all_ids = set(a.angles.keys()) | set(b.angles.keys())
                for servo_id in all_ids:
                    va = a.angles.get(servo_id, centers.get(servo_id, 90))
                    vb = b.angles.get(servo_id, centers.get(servo_id, 90))
                    result[servo_id] = int(va + (vb - va) * ratio)
                return result
        return dict(last.angles)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "loop": self.loop,
            "duration": self.duration_ms,
            "keyframes": [kf.to_dict() for kf in self._raw_keyframes],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Animation":
        kfs = [Keyframe.from_dict(k) for k in data.get("keyframes", [])]
        return cls(
            name=data["name"],
            loop=data.get("loop", True),
            duration_ms=data.get("duration", 2000),
            keyframes=kfs,
        )


class AnimationPlayer:
    def __init__(self, controller: ServoController, tick_rate: float = 0.02):
        self._controller = controller
        self._tick_rate = tick_rate
        self._active: Optional[Animation] = None
        self._playing = False
        self._elapsed = 0.0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._idle_return_active = False
        self._idle_elapsed = 0.0
        self._idle_duration = 0.3
        self._idle_start_angles: dict[str, int] = {}
        self._idle_animation: Optional[Animation] = None
        self._idle_anim_elapsed = 0.0
        self._paused = False
        self._on_state_change: Optional[Callable[[str, Optional[str], bool], None]] = None

    def set_state_callback(self, cb: Callable[[str, Optional[str], bool], None]):
        self._on_state_change = cb

    @property
    def active_animation(self) -> Optional[str]:
        with self._lock:
            return self._active.name if self._active else None

    @property
    def idle_animation_name(self) -> Optional[str]:
        with self._lock:
            return self._idle_animation.name if self._idle_animation else None

    def set_idle_animation(self, animation: Optional[Animation]):
        with self._lock:
            self._idle_animation = animation
            if not self._playing and not self._idle_return_active:
                self._idle_anim_elapsed = 0.0
        self._notify_state()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool):
        with self._lock:
            self._paused = paused
            if not paused:
                if not self._playing and not self._idle_return_active:
                    self._idle_anim_elapsed = 0.0
        self._notify_state()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def play(self, animation: Animation):
        with self._lock:
            self._active = animation
            self._playing = True
            self._elapsed = 0.0
            self._idle_return_active = False
            self._idle_anim_elapsed = 0.0
        self._notify_state("playing", animation.name)

    def stop_playback(self, return_to_idle: bool = True):
        with self._lock:
            was_playing = self._playing or self._idle_return_active
            self._playing = False
            self._active = None
            if return_to_idle and was_playing and not self._paused:
                if self._idle_animation:
                    self._idle_anim_elapsed = 0.0
                    self._idle_return_active = False
                else:
                    self._idle_start_angles = dict(self._controller.get_all_current_angles())
                    self._idle_elapsed = 0.0
                    self._idle_return_active = True
            else:
                self._idle_return_active = False
        self._notify_state("idle", None)

    def _loop(self):
        last_time = time.perf_counter()
        while self._running:
            now = time.perf_counter()
            dt = now - last_time
            last_time = now

            with self._lock:
                if self._paused:
                    pass
                elif self._idle_return_active:
                    self._idle_elapsed += dt
                    ratio = min(1.0, self._idle_elapsed / self._idle_duration)
                    angles = {}
                    for s_id, start_angle in self._idle_start_angles.items():
                        servo = self._controller.get_servo(s_id)
                        if servo:
                            target = servo.center
                            a = int(start_angle + (target - start_angle) * ratio)
                            angles[s_id] = a
                    self._controller.set_all_angles(angles)
                elif self._playing and self._active:
                    self._elapsed += dt * 1000.0
                    centers = {s.id: s.center for s in self._controller.get_all_servos()}
                    angles = self._active.interpolate(self._elapsed, centers)
                    self._controller.set_all_angles(angles)
                elif self._idle_animation:
                    self._idle_anim_elapsed += dt * 1000.0
                    centers = {s.id: s.center for s in self._controller.get_all_servos()}
                    angles = self._idle_animation.interpolate(self._idle_anim_elapsed, centers)
                    self._controller.set_all_angles(angles)

            if not self._paused:
                self._controller.step(dt)

            with self._lock:
                if self._idle_return_active and self._idle_elapsed >= self._idle_duration:
                    self._idle_return_active = False

            elapsed = time.perf_counter() - now
            sleep_time = max(0, self._tick_rate - elapsed)
            time.sleep(sleep_time)

    def _notify_state(self, state: Optional[str] = None, animation_name: Optional[str] = None):
        if self._on_state_change:
            if state is None:
                state = "playing" if self._playing else "idle"
            if animation_name is None:
                animation_name = self.active_animation or self.idle_animation_name
            self._on_state_change(state, animation_name, self._paused)
