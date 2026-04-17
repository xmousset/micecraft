from typing import Callable, Literal

from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtGui import QPaintEvent, QPainter, QFont, QPen, QColor, QBrush
from PyQt6.QtCore import QRect, Qt, QTimer, QPoint
from PyQt6.QtWidgets import QWidget, QMenu

from micecraft.soft.device_event.DeviceEvent import DeviceEvent
from micecraft.devices.touchscreen.TouchScreen import TouchScreen
from micecraft.soft.gui.VisualDeviceAlarmStatus import VisualDeviceAlarmStatus


class WTouchPointIndicator:
    """A small widget to show a touch point indicator at a given position."""

    def __init__(
        self,
        screen_pos: tuple[float, float],
        update_callback: Callable,
        visible_time: int = 3000,
        size: int = 3,
    ):
        self.screen_pos: tuple[float, float] = screen_pos
        """Position (x, y) on the screen."""
        self.show = True
        self.size = size
        self.visible_time = visible_time
        self.update_callback = update_callback

        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.end_timer)

        self.start_timer()

    def get_cross(
        self,
        widget_size: tuple[int, int],
        screen_size: tuple[int, int],
    ) -> list[tuple[int, int, int, int]]:
        """Return [(x1, y1, x2, y2), ...] for the cross lines."""
        x, y = self.screen_pos
        sw, sh = screen_size
        ww, wh = widget_size

        x = int(x / sw * ww)
        y = int(y / sh * wh)
        return [
            (x - self.size, y, x + self.size, y),
            (x, y - self.size, x, y + self.size),
        ]

    def start_timer(self):
        self.timer.start(self.visible_time)

    def end_timer(self):
        try:
            self.timer.stop()
        except Exception:
            pass
        self.show = False
        self.update_callback()


class WTouchScreen(QWidget):
    """
    Visual widget for a TouchScreen device.

    - Shows two display areas (left / right halves of the screen) reflecting
      the current image state: full-light, image name, or colour hint.
    - Renders a cross-hair touch indicator at the last touched position.
    - Shows an enabled / disabled status dot and overlay.
    - Right-click menu: simulate left / right touch, set an image on an area.
    """

    SCREEN_SIZE = (1920, 1080)
    """(width, height) in *px*"""
    WIDGET_SIZE = (150, 40)
    """(width, height) in *px*"""

    NAME_DICT: dict[int, str] = {
        8: "DARK",
        7: "LIGHT",
        1: "FLOWER",
        0: "PLANE",
    }

    BG_COLOR = QColor(220, 220, 220)
    LIGHT_COLOR = QColor(60, 180, 240)  # QColor(233, 233, 133)
    DARK_COLOR = QColor(33, 33, 33)

    @staticmethod
    def get_rect(
        box: Literal["left", "right", "full", "widget", "name"] | str,
    ) -> tuple[int, int, int, int]:
        """(x, y, width, height)"""
        x, y, w, h = (0, 0, *WTouchScreen.WIDGET_SIZE)
        margin_x = 6
        margin_y = 6

        match box:
            case "left":
                x = margin_x
                y = margin_y
                w = (w - 4 * margin_x) // 2
                h = h - 2 * margin_y
            case "right":
                x = margin_x + w // 2
                y = margin_y
                w = (w - 4 * margin_x) // 2
                h = h - 2 * margin_y
            case "full":
                x = margin_x
                y = margin_y
                w = w - 2 * margin_x
                h = h - 2 * margin_y
            case "name":
                x = margin_x
                y = 0
                w = w - 2 * margin_x
                h = 12

        return (x, y, w, h)

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        angle: float = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.xy_pos = (x * 200 + 100, y * 200 + 100)
        self.angle = angle
        _, _, ww, wh = WTouchScreen.get_rect("widget")
        self.setGeometry(int(self.xy_pos[0]), int(self.xy_pos[1]), ww, wh)

        self.touchscreen = None
        self.name = "WTS"

        self.visualDeviceAlarmStatus = VisualDeviceAlarmStatus()

        self.img_id: dict[str, int | None] = {
            "left": None,
            "right": None,
        }
        self.img_name: dict[str, str | None] = {
            "left": None,
            "right": None,
        }
        self.indicators: list[WTouchPointIndicator] = []

    def setName(self, name: str):
        self.name = name
        self.update()

    def setAngle(self, angle: float):
        self.angle = angle
        self.update()

    def bindToTouchScreen(self, ts: TouchScreen):
        """Bind this widget to a TouchScreen device instance."""
        if self.touchscreen is not None:
            self.touchscreen.removeDeviceListener(
                self.widget_touchscreen_listener
            )

        self.touchscreen = ts
        self.name = ts.name
        ts.addDeviceListener(self.widget_touchscreen_listener)
        self.update()

    # ------------------------------------------------------------------
    # Device event listener
    # ------------------------------------------------------------------

    def widget_touchscreen_listener(self, event: DeviceEvent):
        desc = event.description

        if "setImage" in desc:
            # data = (id, x, y)
            data = desc.split(" ")[1:]
            id, x, _ = data

            if float(x) < self.SCREEN_SIZE[0] / 2:
                side = "left"
            else:
                side = "right"
            self.img_id[side] = int(id)

        if "removeImage" in desc:
            # data = (x, y)
            data = desc.split(" ")[1:]
            x, _ = data

            if float(x) < self.SCREEN_SIZE[0] / 2:
                side = "left"
            else:
                side = "right"

            self.img_id[side] = None

        if "setXYImage" in desc:
            # data = (name, id, centerX, centerY, rotation, scale)
            name = event.data[0]  # type: ignore
            id = event.data[1]  # type: ignore
            cx = event.data[2]  # type: ignore

            if cx < self.SCREEN_SIZE[0] / 2:
                side = "left"
            else:
                side = "right"

            self.img_id[side] = id
            self.img_name[side] = name

        if "removeXYImage" in desc:
            # data = (name,)
            name = event.data[0]  # type: ignore
            if name == self.img_name["left"]:
                side = "left"
            elif name == self.img_name["right"]:
                side = "right"
            else:
                return
            self.img_id[side] = None
            self.img_name[side] = None

        if "symbol touched" in desc:
            # data = (id, x, y, xf, yf)
            _, _, _, x, y = event.data  # type: ignore
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        if "symbol xy touched" in desc:
            # data = (name, id, x, y, xf, yf)
            _, _, _, _, x, y = event.data  # type: ignore
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        elif "missed" in desc:
            # data = (xf, yf)
            x, y = event.data  # type: ignore
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        if "clear" in desc:
            for side in ["left", "right"]:
                self.img_id[side] = None
                self.img_name[side] = None

        self.update()

    # ================ PAINT ================

    def paintEvent(self, event: QPaintEvent):  # type: ignore[override]
        super().paintEvent(event)

        # block
        w = 30

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.translate(w / 2, h / 2)
        p.rotate(self.angle)
        p.translate(-w / 2, -h / 2)

        # background
        p.fillRect(0, 0, w, h, WTouchScreen.BG_COLOR)

        # disabled overlay
        if self.touchscreen is not None and not self.touchscreen.enabled:
            p.setPen(WTouchScreen.DARK_COLOR)
            font = QFont("Calibri", 16)
            font.setBold(True)
            p.setFont(font)
            p.drawText(
                QRect(*WTouchScreen.get_rect("full")),
                Qt.AlignmentFlag.AlignCenter,
                "DISABLED",
            )
        else:
            # display images
            for side in ["left", "right"]:
                id = self.img_id[side]
                if id is None:
                    continue
                name = self.NAME_DICT.get(id, f"UNKOWN")
                img_clr = (
                    WTouchScreen.DARK_COLOR
                    if id == 8
                    else WTouchScreen.LIGHT_COLOR
                )
                p.fillRect(*WTouchScreen.get_rect(side), img_clr)

                pen_clr = (
                    WTouchScreen.LIGHT_COLOR
                    if img_clr == WTouchScreen.DARK_COLOR
                    else WTouchScreen.DARK_COLOR
                )
                p.setPen(pen_clr)
                font = QFont("Calibri", 11)
                font.setBold(True)
                p.setFont(font)
                p.drawText(
                    *WTouchScreen.get_rect(side),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )

        # display touch indicator
        all_indicators = self.indicators.copy()
        for indicator in all_indicators:

            if not indicator.show:
                self.indicators.remove(indicator)
                continue

            if not indicator.show:
                self.indicators.remove(indicator)
                continue

            cross_lines = indicator.get_cross(
                (self.width(), self.height()),
                WTouchScreen.SCREEN_SIZE,
            )

            p.setPen(QPen(QColor(255, 0, 0), 2))
            for line in cross_lines:
                p.drawLine(*line)

        # name strip
        name_clr = WTouchScreen.BG_COLOR.darker(200)
        name_clr.setAlpha(100)
        p.setPen(name_clr)
        font_name = QFont("Calibri", 8)
        font_name.setBold(True)
        p.setFont(font_name)
        p.drawText(
            *WTouchScreen.get_rect("name"),
            Qt.AlignmentFlag.AlignCenter,
            self.name,
        )

        # self.visualDeviceAlarmStatus.draw(
        #     p,
        #     self.touchscreen,
        #     ellipseRect=QRect(22, 60, 10, 10),
        #     textRect=QRect(-25, 13, 100, 50),
        # )

        p.end()

    # ================ MENU ================

    def contextMenuEvent(self, event):  # type: ignore[override]
        menu = QMenu(self)

        actions: dict[QtGui.QAction, tuple[Callable, tuple]] = {}

        title = QtGui.QAction("Touch Screen Actions", menu)
        title.setDisabled(True)
        menu.addAction(title)
        menu.addSeparator()

        # display menu
        test = QMenu("Test (no event)", menu)
        menu.addMenu(test)

        display = QMenu("Display", test)
        test.addMenu(display)
        display_left = QMenu("on left", display)
        display.addMenu(display_left)
        display_right = QMenu("on right", display)
        display.addMenu(display_right)

        test_clear = QMenu("Clear", test)
        test.addMenu(test_clear)

        for img_id, img_name in WTouchScreen.NAME_DICT.items():
            action = QtGui.QAction(img_name, display_left)
            display_left.addAction(action)
            actions[action] = (self.display_image, ("left", img_id))

            action = QtGui.QAction(img_name, display_right)
            display_right.addAction(action)
            actions[action] = (self.display_image, ("right", img_id))

        action = QtGui.QAction("on left", test_clear)
        test_clear.addAction(action)
        actions[action] = (self.clear_image, ("left",))

        action = QtGui.QAction("on right", test_clear)
        test_clear.addAction(action)
        actions[action] = (self.clear_image, ("right",))

        # simulation menu
        simulate = QMenu("Simulate event", menu)
        menu.addMenu(simulate)

        if self.touchscreen is None:
            msgs = [
                "Warning: no TouchScreen found",
                "=> simulations will have no effect",
            ]
            for msg in msgs:
                warning = QtGui.QAction(msg, simulate)
                warning.setDisabled(True)
                simulate.addAction(warning)

        sim_set = QMenu("setImage event", simulate)
        simulate.addMenu(sim_set)
        sim_left = QMenu("on left", sim_set)
        sim_set.addMenu(sim_left)
        sim_right = QMenu("on right", sim_set)
        sim_set.addMenu(sim_right)

        sim_remove = QMenu("removeImage event", simulate)
        simulate.addMenu(sim_remove)

        sim_touch = QMenu("touch event", simulate)
        simulate.addMenu(sim_touch)

        for img_id, img_name in WTouchScreen.NAME_DICT.items():
            action = QtGui.QAction(img_name, sim_left)
            sim_left.addAction(action)
            actions[action] = (self.simulate_set_image, ("left", img_id))

            action = QtGui.QAction(img_name, sim_right)
            sim_right.addAction(action)
            actions[action] = (self.simulate_set_image, ("right", img_id))

        action = QtGui.QAction("on left", sim_remove)
        sim_remove.addAction(action)
        actions[action] = (self.simulate_remove_image, ("left",))

        action = QtGui.QAction("on right", sim_remove)
        sim_remove.addAction(action)
        actions[action] = (self.simulate_remove_image, ("right",))

        action = QtGui.QAction("on left", sim_touch)
        sim_touch.addAction(action)
        actions[action] = (
            self.simulate_touch_event,
            ("left", self.img_id["left"]),
        )

        action = QtGui.QAction("on right", sim_touch)
        sim_touch.addAction(action)
        actions[action] = (
            self.simulate_touch_event,
            ("right", self.img_id["right"]),
        )

        chosen = menu.exec(self.mapToGlobal(event.pos()))

        if chosen is None:
            return
        actions[chosen][0](*actions[chosen][1])

    def display_image(self, side: str, img_id: int):
        """Set the image on the given side ('left' or 'right') based on the
        img_id."""
        if side not in ["left", "right"]:
            return
        self.img_id[side] = img_id
        self.update()

    def clear_image(self, side: str):
        """Clear the image on the given side ('left' or 'right')."""
        if side not in ["left", "right"]:
            return
        self.img_id[side] = None
        self.img_name[side] = None
        self.update()

    def simulate_set_image(self, side: str, img_id: int):
        """Simulate a 'setImage' event on the given side ('left' or 'right')
        with the given img_id."""
        if self.touchscreen is None:
            return
        x = WTouchScreen.SCREEN_SIZE[0] / 2
        x += -400 if side == "left" else 400
        y = 750
        name = f"{side}_image_{WTouchScreen.NAME_DICT[img_id]}"
        self.touchscreen.setXYImage(
            name,
            img_id,
            x,
            y,
            0,
            1,
        )
        self.img_id[side] = img_id
        self.img_name[side] = name
        self.update()

    def simulate_remove_image(self, side: str):
        """Simulate a 'removeImage' event on the given side ('left' or 'right')."""
        if self.touchscreen is None:
            return
        name = self.img_name[side]
        self.touchscreen.removeXYImage(name)
        self.img_id[side] = None
        self.img_name[side] = None
        self.update()

    def simulate_touch_event(self, side: str, id: int | None = None):
        """Fire a synthetic 'symbol xy touched' event through the device."""
        if self.touchscreen is None:
            return
        if id is None:
            id = 7
        x = 0 if side == "left" else self.SCREEN_SIZE[0]
        y = 0.5 * self.SCREEN_SIZE[1]
        name = side + "_simulation"
        self.touchscreen.fireEvent(
            DeviceEvent(
                "touchscreen",
                self.touchscreen,
                f"symbol xy touched {name} id {id} at 0,0,{x},{y}",
                (name, id, 0, 0, x, y),
            )
        )
        self.update()


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    w = WTouchScreen()
    w.setName("Example TouchScreen")
    w.show()
    w.display_image("left", 8)
    w.display_image("right", 7)
    w.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 100, 100)
        )
    )
    w.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 500, 100)
        )
    )
    w.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 500, 500)
        )
    )
    sys.exit(app.exec())
