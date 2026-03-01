from dataclasses import dataclass, field
from enum import Enum

from syma import NEUTRAL
from syma.controller import SymaController

# How much throttle changes per keypress (incremental, persists)
THROTTLE_STEP = 4

# How far spring-back axes deflect from neutral when held
DEFLECTION = 0x40


class KeyAction(Enum):
    THROTTLE_UP = "throttle_up"
    THROTTLE_DOWN = "throttle_down"
    ELEVATOR_FWD = "elevator_fwd"
    ELEVATOR_BACK = "elevator_back"
    RUDDER_LEFT = "rudder_left"
    RUDDER_RIGHT = "rudder_right"
    AILERON_LEFT = "aileron_left"
    AILERON_RIGHT = "aileron_right"
    TAKEOFF = "takeoff"
    LAND = "land"
    CALIBRATE = "calibrate"
    EMERGENCY_STOP = "emergency_stop"
    RESET = "reset"
    QUIT = "quit"


# Kivy keycodes (integer key values)
KEY_MAP: dict[int, KeyAction] = {
    119: KeyAction.THROTTLE_UP,  # w
    115: KeyAction.THROTTLE_DOWN,  # s
    273: KeyAction.ELEVATOR_FWD,  # up arrow
    274: KeyAction.ELEVATOR_BACK,  # down arrow
    276: KeyAction.AILERON_LEFT,  # left arrow
    275: KeyAction.AILERON_RIGHT,  # right arrow
    97: KeyAction.RUDDER_LEFT,  # a
    100: KeyAction.RUDDER_RIGHT,  # d
    116: KeyAction.TAKEOFF,  # t
    108: KeyAction.LAND,  # l
    99: KeyAction.CALIBRATE,  # c
    32: KeyAction.EMERGENCY_STOP,  # spacebar
    27: KeyAction.EMERGENCY_STOP,  # escape
    114: KeyAction.RESET,  # r
    113: KeyAction.QUIT,  # q
}

# Actions that correspond to spring-back axis deflections
_SPRING_BACK_ACTIONS = {
    KeyAction.ELEVATOR_FWD,
    KeyAction.ELEVATOR_BACK,
    KeyAction.RUDDER_LEFT,
    KeyAction.RUDDER_RIGHT,
    KeyAction.AILERON_LEFT,
    KeyAction.AILERON_RIGHT,
}

# Map from key_down action to axis name and direction
_AXIS_ACTION_MAP: dict[KeyAction, tuple[str, int]] = {
    KeyAction.THROTTLE_UP: ("throttle", +THROTTLE_STEP),
    KeyAction.THROTTLE_DOWN: ("throttle", -THROTTLE_STEP),
    KeyAction.ELEVATOR_FWD: ("elevator", +DEFLECTION),
    KeyAction.ELEVATOR_BACK: ("elevator", -DEFLECTION),
    KeyAction.RUDDER_LEFT: ("rudder", -DEFLECTION),
    KeyAction.RUDDER_RIGHT: ("rudder", +DEFLECTION),
    KeyAction.AILERON_LEFT: ("aileron", -DEFLECTION),
    KeyAction.AILERON_RIGHT: ("aileron", +DEFLECTION),
}


@dataclass
class AxisManager:
    """Manages axis values with key-down/key-up semantics. No GUI dependency."""

    throttle: int = NEUTRAL
    elevator: int = NEUTRAL
    rudder: int = NEUTRAL
    aileron: int = NEUTRAL

    _held: set = field(default_factory=set)

    def key_down(self, action: KeyAction) -> bool:
        """Handle a key press. Returns True if it was an axis action."""
        if action not in _AXIS_ACTION_MAP:
            return False

        axis_name, delta = _AXIS_ACTION_MAP[action]

        if action in _SPRING_BACK_ACTIONS:
            self._held.add(action)
            setattr(self, axis_name, max(0x00, min(0xFF, NEUTRAL + delta)))
        else:
            # Incremental (throttle)
            current = getattr(self, axis_name)
            setattr(self, axis_name, max(0x00, min(0xFF, current + delta)))

        return True

    def key_up(self, action: KeyAction) -> bool:
        """Handle a key release. Returns True if it was a spring-back action."""
        if action not in _SPRING_BACK_ACTIONS:
            return False

        self._held.discard(action)
        axis_name, _ = _AXIS_ACTION_MAP[action]

        # Only spring back if no other action for this axis is still held
        still_held_for_axis = any(
            a in self._held
            for a, (name, _) in _AXIS_ACTION_MAP.items()
            if name == axis_name
        )
        if not still_held_for_axis:
            setattr(self, axis_name, NEUTRAL)

        return True

    def reset_all(self):
        """Reset all axes to neutral."""
        self.throttle = NEUTRAL
        self.elevator = NEUTRAL
        self.rudder = NEUTRAL
        self.aileron = NEUTRAL
        self._held.clear()

    def apply_to_controller(self, ctrl: SymaController):
        """Push current axis values to the SymaController."""
        ctrl.throttle = self.throttle
        ctrl.elevator = self.elevator
        ctrl.rudder = self.rudder
        ctrl.aileron = self.aileron
