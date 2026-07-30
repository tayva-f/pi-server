# pi-server

Flask + SocketIO web server for controlling a 4-legged robot with 8+ servos via Raspberry Pi GPIO.

## Quick start

```bash
# Install dependencies
uv sync

# Ensure lgpio is available (built into modern Pi OS kernel)
# Grant GPIO access to your user:
sudo usermod -a -G gpio $USER
# Log out and back in for group membership to take effect

# Run the server
uv run main.py
# Or directly:
python main.py
```

The web UI is served at `http://<pi-ip>:3000`.

## Architecture

```
main.py                     Flask + SocketIO server (port 3000)
robot/
  servo.py                  ServoController — GPIO servo management via lgpio
  animation.py              Animation engine — keyframe interpolation, playback
  keymapper.py              Key → animation mapper with hold/release logic
  storage.py                JSON file persistence (data/*.json)
static/
  js/main.js                Mic/audio streaming, tab switching, robot state
  js/editor.js              Animation keyframe timeline editor
  js/keymapper.js           Key binding capture UI
  js/servo-manager.js       Servo CRUD + pin testing UI
  css/style.css             Light theme (Instrument Serif font, #F06449 accent)
templates/
  index.html                Tabbed UI (Home | Editor | Key Mapper | Servos)
data/
  animations.json           Saved animation definitions
  servo_config.json         Servo pin/angle configs
  key_bindings.json         Keyboard → animation name mappings
```

## Tests / verification

This project does not currently have a test runner. The server includes a dry-run mode that activates automatically when pigpio is unavailable, allowing the web UI to be tested without hardware.

To verify Python syntax:

```bash
uv run python -m py_compile main.py robot/servo.py robot/animation.py robot/keymapper.py robot/storage.py
```

## Key behaviors

- **Dry-run mode**: If lgpio is unavailable (/dev/gpiochip0 can't be opened), the server starts in dry-run mode so the web UI remains functional for editing animations and bindings.
- **Hold-to-play, release-to-stop**: Holding a bound key plays the mapped animation in a loop. Releasing returns servos smoothly to their center positions (~300ms).
- **Multi-key support**: Holding multiple bound keys switches to the most recently pressed key's animation. Releasing falls back to the next held key or idle.
- **Smooth loop wrap**: For looping animations, the gap between the last keyframe and the end time interpolates back to the first keyframe's angles (no jarring jumps).
- **New keyframes avoid stacking**: The "Add Keyframe" button scans for an unoccupied time slot to prevent overlapping markers.

## Color scheme

```
Accent/header:  #F06449
Background:     #EDE6E3
Card/sidebar:   #DADAD9
Border:         #C5C0BD
Text:           #1a1a1a (black)
Text secondary: #555
Font:           Instrument Serif (Google Fonts)
```

## Editing guidelines

- Use the existing project conventions: `var` for JS globals, jQuery for DOM, Flask route decorators for API endpoints.
- Python type annotations use PEP 604 union syntax (`str | None`).
- All JS modules expose a single global object (`Editor`, `KeyMapper`, `Servos`).
- The editor tab sidebar is 220px wide, the servo sidebar is 300px.
- Form inputs use the `.servo-form-row` pattern (label right-aligned, input flex-filled).
