from syma import NEUTRAL
from syma.controller import SymaController

from drone_ui.axes import (
    DEFLECTION,
    KEY_MAP,
    THROTTLE_STEP,
    AxisManager,
    KeyAction,
)


class TestKeyMap:
    def test_wasd_keys_mapped(self):
        assert KEY_MAP[119] == KeyAction.THROTTLE_UP  # w
        assert KEY_MAP[115] == KeyAction.THROTTLE_DOWN  # s
        assert KEY_MAP[97] == KeyAction.RUDDER_LEFT  # a
        assert KEY_MAP[100] == KeyAction.RUDDER_RIGHT  # d

    def test_arrow_keys_mapped(self):
        assert KEY_MAP[273] == KeyAction.ELEVATOR_FWD  # up
        assert KEY_MAP[274] == KeyAction.ELEVATOR_BACK  # down
        assert KEY_MAP[276] == KeyAction.AILERON_LEFT  # left
        assert KEY_MAP[275] == KeyAction.AILERON_RIGHT  # right

    def test_command_keys_mapped(self):
        assert KEY_MAP[116] == KeyAction.TAKEOFF  # t
        assert KEY_MAP[108] == KeyAction.LAND  # l
        assert KEY_MAP[99] == KeyAction.CALIBRATE  # c
        assert KEY_MAP[32] == KeyAction.EMERGENCY_STOP  # space
        assert KEY_MAP[27] == KeyAction.EMERGENCY_STOP  # escape
        assert KEY_MAP[114] == KeyAction.RESET  # r
        assert KEY_MAP[113] == KeyAction.QUIT  # q


class TestAxisManager:
    def test_initial_values_neutral(self):
        am = AxisManager()
        assert am.throttle == NEUTRAL
        assert am.elevator == NEUTRAL
        assert am.rudder == NEUTRAL
        assert am.aileron == NEUTRAL

    def test_throttle_up_increments(self):
        am = AxisManager()
        am.key_down(KeyAction.THROTTLE_UP)
        assert am.throttle == NEUTRAL + THROTTLE_STEP

    def test_throttle_down_decrements(self):
        am = AxisManager()
        am.key_down(KeyAction.THROTTLE_DOWN)
        assert am.throttle == NEUTRAL - THROTTLE_STEP

    def test_throttle_no_spring_back(self):
        am = AxisManager()
        am.key_down(KeyAction.THROTTLE_UP)
        am.key_up(KeyAction.THROTTLE_UP)
        assert am.throttle == NEUTRAL + THROTTLE_STEP

    def test_throttle_clamp_max(self):
        am = AxisManager()
        am.throttle = 0xFE
        am.key_down(KeyAction.THROTTLE_UP)
        assert am.throttle == 0xFF

    def test_throttle_clamp_min(self):
        am = AxisManager()
        am.throttle = 0x01
        am.key_down(KeyAction.THROTTLE_DOWN)
        assert am.throttle == 0x00

    def test_elevator_deflects_on_key_down(self):
        am = AxisManager()
        am.key_down(KeyAction.ELEVATOR_FWD)
        assert am.elevator == NEUTRAL + DEFLECTION

    def test_elevator_springs_back_on_key_up(self):
        am = AxisManager()
        am.key_down(KeyAction.ELEVATOR_FWD)
        am.key_up(KeyAction.ELEVATOR_FWD)
        assert am.elevator == NEUTRAL

    def test_rudder_deflects_on_key_down(self):
        am = AxisManager()
        am.key_down(KeyAction.RUDDER_LEFT)
        assert am.rudder == NEUTRAL - DEFLECTION

    def test_rudder_springs_back_on_key_up(self):
        am = AxisManager()
        am.key_down(KeyAction.RUDDER_LEFT)
        am.key_up(KeyAction.RUDDER_LEFT)
        assert am.rudder == NEUTRAL

    def test_aileron_deflects_on_key_down(self):
        am = AxisManager()
        am.key_down(KeyAction.AILERON_RIGHT)
        assert am.aileron == NEUTRAL + DEFLECTION

    def test_aileron_springs_back_on_key_up(self):
        am = AxisManager()
        am.key_down(KeyAction.AILERON_RIGHT)
        am.key_up(KeyAction.AILERON_RIGHT)
        assert am.aileron == NEUTRAL

    def test_simultaneous_axes(self):
        am = AxisManager()
        am.key_down(KeyAction.ELEVATOR_FWD)
        am.key_down(KeyAction.AILERON_LEFT)
        assert am.elevator == NEUTRAL + DEFLECTION
        assert am.aileron == NEUTRAL - DEFLECTION
        am.key_up(KeyAction.ELEVATOR_FWD)
        assert am.elevator == NEUTRAL
        assert am.aileron == NEUTRAL - DEFLECTION  # still held

    def test_opposite_directions_last_wins(self):
        am = AxisManager()
        am.key_down(KeyAction.ELEVATOR_FWD)
        am.key_down(KeyAction.ELEVATOR_BACK)
        # Last key_down sets the value
        assert am.elevator == NEUTRAL - DEFLECTION
        # Release backward, forward still held — but spring-back checks held set
        am.key_up(KeyAction.ELEVATOR_BACK)
        # Forward is still held, so elevator should not spring back
        assert am.elevator != NEUTRAL  # forward still active

    def test_reset_all(self):
        am = AxisManager()
        am.throttle = 0xFF
        am.elevator = 0x00
        am.rudder = 0xC0
        am.aileron = 0x40
        am.reset_all()
        assert am.throttle == NEUTRAL
        assert am.elevator == NEUTRAL
        assert am.rudder == NEUTRAL
        assert am.aileron == NEUTRAL

    def test_non_axis_action_returns_false(self):
        am = AxisManager()
        assert am.key_down(KeyAction.TAKEOFF) is False

    def test_axis_action_returns_true(self):
        am = AxisManager()
        assert am.key_down(KeyAction.THROTTLE_UP) is True

    def test_spring_back_returns_true(self):
        am = AxisManager()
        am.key_down(KeyAction.ELEVATOR_FWD)
        assert am.key_up(KeyAction.ELEVATOR_FWD) is True

    def test_throttle_key_up_returns_false(self):
        am = AxisManager()
        assert am.key_up(KeyAction.THROTTLE_UP) is False


class TestApplyToController:
    def test_apply_to_controller(self):
        am = AxisManager()
        am.throttle = 0xC0
        am.elevator = 0x60
        am.rudder = 0xA0
        am.aileron = 0x40

        ctrl = SymaController()
        am.apply_to_controller(ctrl)

        assert ctrl.throttle == 0xC0
        assert ctrl.elevator == 0x60
        assert ctrl.rudder == 0xA0
        assert ctrl.aileron == 0x40
