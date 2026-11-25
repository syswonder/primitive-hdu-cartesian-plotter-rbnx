---
description: XYZ pen-plotter primitive — direct PLC motion, homing, and the global speed/pen-height profile.
---

# XYZ plotter primitive (`cartesian_plotter`)

Owns the three-axis gantry and the TCP connection to its PLC. Skills convert
text or images into `(x, y, z)` waypoints; this primitive executes them.

## MCP tools

### `plotter_home`

Send the gantry to the PLC's fixed home position and block until the motion
completes.

- No arguments.
- Returns `success`, `message`, and `elapsed_s`.
- Home is always `(0, 0, 0)`; no target can be supplied.
- Use it before the first job after power-up, after a failed job, or whenever
  the user asks to home, park, or reset the machine.
- Fails while a trajectory is running.

### `plotter_set_params`

Set the **global** motion profile and pen heights for subsequent motions.
SET_PARAM does not move the machine.

Arguments (all `float64`; **0 means "keep the current value"**):

| Field | Unit | Meaning |
| --- | --- | --- |
| `velocity` | mm/s | Traverse speed |
| `acceleration` | mm/s² | Acceleration |
| `deceleration` | mm/s² | Deceleration |
| `jerk` | mm/s³ | Jerk limit |
| `z_up` | mm | Pen-up height (default -46; machine-specific) |
| `z_down` | mm | Pen-down height (default -50; machine-specific) |

Rules:

- Pass only the fields you want to change; send `0` for the rest. Example:
  `{"velocity": 40, "acceleration": 0, "deceleration": 0, "jerk": 0,
  "z_up": 0, "z_down": 0}` doubles speed and keeps everything else.
- After merging, pen heights must satisfy the primitive's configured
  `z_min <= z_down < z_up <= z_max` (defaults `-50` / `0` on this rig).
  Changing the paper or pen requires recalibration.
- Motion values must be finite and positive after merging.
- The profile persists until the next `plotter_set_params` or a PLC restart.
  If the PLC is offline the primitive caches the values and reapplies them on
  reconnect.
- There is **no readback**: the primitive mirrors the last values it sent.
  Never claim to know PLC-side values that were set by another process.
- The profile is global; there is no per-point velocity.
- Pen heights in a trajectory are encoded in each waypoint's `z`. The skills
  use their own configured workspace heights, so changing `z_up`/`z_down`
  here affects the primitive's pre-move safety lift but does not rewrite a
  skill's planned waypoint heights.

## Not MCP tools

- `robonix/primitive/plotter/trajectory` — gRPC only; used by the text and
  draw skills to execute waypoint lists.
- `robonix/primitive/plotter/status` — gRPC server stream with connection,
  busy, last error, and last commanded position.
- `robonix/primitive/plotter/geometry` — gRPC only; static drawable area and
  pen heights, read once by the skills on activation.
- `robonix/primitive/plotter/driver` — lifecycle only.

## Coordinates and limits

- Units: millimetres. Paper origin `(0, 0)` is the lower-left corner; +X right,
  +Y up.
- Machine zero `(0, 0, 0)` is 50 mm above the paper; paper surface `z = -50`.
- Travel: X 0–`area_x_max` mm, Y 0–`area_y_max` mm (defaults 180 × 150).
- The PLC has no STOP command. On failure the pen stops in place; recover with
  `plotter_home`.
- Always home after power-up before the first motion.