from typing import Optional, Callable
import threading


class KeyMapper:
    def __init__(self, bindings: dict[str, str],
                 play_cb: Callable[[str], None],
                 stop_cb: Callable[[], None]):
        self._bindings = bindings
        self._play_cb = play_cb
        self._stop_cb = stop_cb
        self._held_keys: set[str] = set()
        self._lock = threading.Lock()

    @property
    def bindings(self) -> dict[str, str]:
        with self._lock:
            return dict(self._bindings)

    def update_bindings(self, bindings: dict[str, str]):
        with self._lock:
            self._bindings = dict(bindings)

    def get_binding(self, key: str) -> Optional[str]:
        with self._lock:
            return self._bindings.get(key)

    def handle_keydown(self, key: str):
        with self._lock:
            self._held_keys.add(key)
            anim = self._bindings.get(key)
        if anim:
            self._play_cb(anim)

    def handle_keyup(self, key: str):
        still_bound = False
        next_anim = None
        with self._lock:
            self._held_keys.discard(key)
            for k in list(self._held_keys):
                if k in self._bindings:
                    still_bound = True
                    next_anim = self._bindings[k]
                    break
        if still_bound and next_anim:
            self._play_cb(next_anim)
        elif not still_bound:
            self._stop_cb()
