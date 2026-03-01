import asyncio

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar

from syma import NEUTRAL
from syma.controller import SymaController

from drone_ui.axes import KEY_MAP, AxisManager, KeyAction


class DroneApp(App):
    title = "Syma X22W Controller"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.axes = AxisManager()
        self.controller = SymaController()
        self.status = "Disconnected"
        self._controller_task = None

        # UI widget references
        self._throttle_bar = None
        self._elevator_bar = None
        self._rudder_bar = None
        self._aileron_bar = None
        self._throttle_label = None
        self._elevator_label = None
        self._rudder_label = None
        self._aileron_label = None
        self._status_label = None

    def build(self):
        Window.bind(on_key_down=self._on_key_down)
        Window.bind(on_key_up=self._on_key_up)

        root = BoxLayout(orientation="vertical", padding=10, spacing=5)

        title = Label(
            text="Syma X22W Drone Controller",
            size_hint_y=None,
            height=40,
            bold=True,
            font_size=20,
        )
        root.add_widget(title)

        # Axis displays
        axes_layout = BoxLayout(orientation="vertical", spacing=2)
        for name in ("Throttle", "Elevator", "Rudder", "Aileron"):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=30)
            label = Label(text=f"{name}: 0x80", size_hint_x=0.3, halign="left")
            label.bind(size=label.setter("text_size"))
            bar = ProgressBar(max=255, value=NEUTRAL, size_hint_x=0.7)
            row.add_widget(label)
            row.add_widget(bar)
            axes_layout.add_widget(row)

            attr = name.lower()
            setattr(self, f"_{attr}_label", label)
            setattr(self, f"_{attr}_bar", bar)

        root.add_widget(axes_layout)

        # Status
        self._status_label = Label(
            text="Status: Disconnected",
            size_hint_y=None,
            height=30,
        )
        root.add_widget(self._status_label)

        # Key bindings reference
        keys_text = (
            "[b]Controls:[/b]  W/S: Throttle  |  Arrows: Elevator/Aileron  |  "
            "A/D: Rudder\n"
            "T: Takeoff  |  L: Land  |  C: Calibrate  |  "
            "Space: ESTOP  |  R: Reset  |  Q: Quit"
        )
        keys_label = Label(
            text=keys_text,
            size_hint_y=None,
            height=50,
            markup=True,
        )
        root.add_widget(keys_label)

        return root

    def on_start(self):
        Clock.schedule_interval(self._update_display, 1 / 20)
        Clock.schedule_interval(self._sync_controller, 1 / 60)
        self._controller_task = asyncio.ensure_future(self._connect_controller())

    async def _connect_controller(self):
        try:
            await self.controller.connect()
            self.status = "Connected - Idle"
        except Exception as e:
            self.status = f"Connection failed: {e}"

    def _on_key_down(self, window, key, scancode, codepoint, modifiers):
        action = KEY_MAP.get(key)
        if action is None:
            return False

        if action == KeyAction.QUIT:
            self.stop()
            return True

        if self.axes.key_down(action):
            return True

        # Command actions
        if action == KeyAction.TAKEOFF:
            self.status = "Taking off..."
            asyncio.ensure_future(self._do_takeoff())
        elif action == KeyAction.LAND:
            self.status = "Landing..."
            asyncio.ensure_future(self._do_land())
        elif action == KeyAction.CALIBRATE:
            self.status = "Calibrating..."
            asyncio.ensure_future(self._do_calibrate())
        elif action == KeyAction.EMERGENCY_STOP:
            asyncio.ensure_future(self._do_emergency_stop())
            self.axes.reset_all()
            self.status = "EMERGENCY STOP"
        elif action == KeyAction.RESET:
            self.axes.reset_all()
            self.status = "Sticks reset"

        return True

    def _on_key_up(self, window, key, scancode):
        action = KEY_MAP.get(key)
        if action is not None:
            self.axes.key_up(action)
        return True

    async def _do_takeoff(self):
        await self.controller.takeoff()
        self.status = "Flying"

    async def _do_land(self):
        await self.controller.land()
        self.status = "Landed"

    async def _do_calibrate(self):
        await self.controller.calibrate()
        self.status = "Calibrated"

    async def _do_emergency_stop(self):
        await self.controller.emergency_stop()

    def _sync_controller(self, dt):
        self.axes.apply_to_controller(self.controller)

    def _update_display(self, dt):
        for name in ("throttle", "elevator", "rudder", "aileron"):
            value = getattr(self.axes, name)
            label = getattr(self, f"_{name}_label")
            bar = getattr(self, f"_{name}_bar")
            label.text = f"{name.capitalize()}: 0x{value:02X}"
            bar.value = value

        if self._status_label:
            self._status_label.text = f"Status: {self.status}"

    def on_stop(self):
        if self._controller_task and not self._controller_task.done():
            self._controller_task.cancel()
        asyncio.ensure_future(self.controller.disconnect())


async def main():
    app = DroneApp()
    await app.async_run("asyncio")


def main_cli():
    asyncio.run(main())


if __name__ == "__main__":
    main_cli()
