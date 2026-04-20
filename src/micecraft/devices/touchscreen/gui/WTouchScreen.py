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
        orientation: Literal["horizontal", "vertical"] | str = "horizontal",
    ) -> list[tuple[int, int, int, int]]:
        """Return [(x1, y1, x2, y2), ...] for the cross lines."""
        x, y = self.screen_pos
        sw, sh = screen_size
        ww, wh = widget_size
        if orientation == "vertical":
            ww, wh = wh, ww

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

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        block_wall: Literal["left", "top", "right", "bottom"] = "top",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        match block_wall:
            case "top":
                dx = 0
                dy = 1
                self.orientation = "horizontal"
            case "bottom":
                dx = 0
                dy = 0
                self.orientation = "horizontal"
            case "left":
                dx = 0.5
                dy = 0.5
                self.orientation = "vertical"
            case "right":
                dx = 1.5
                dy = 0.5
                self.orientation = "vertical"

        self.xy_pos = ((x + dx) * 200, (y + dy) * 200)
        self.block_wall = block_wall
        _, _, ww, wh = self.get_rect("widget")
        if self.orientation == "horizontal":
            geo_dx = -ww // 2
            geo_dy = (100 - wh) // 2
        else:
            geo_dx = (100 - wh) // 2
            geo_dy = ww // 2

        self.setGeometry(
            int(self.xy_pos[0]) + geo_dx,
            int(self.xy_pos[1]) + geo_dy,
            ww,
            wh,
        )

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

    def get_rect(
        self,
        box: str,
    ) -> tuple[int, int, int, int]:
        """(x, y, width, height)

        box: "left", "right", "full", "name", "contour", "widget"
        """
        W, H = WTouchScreen.WIDGET_SIZE
        margin = 6

        match box:
            case "left":
                x = margin
                y = margin
                w = (W - 3 * margin) // 2
                h = H - 2 * margin
            case "right":
                x = W - margin - (W - 3 * margin) // 2
                y = margin
                w = (W - 3 * margin) // 2
                h = H - 2 * margin
            case "full":
                x = margin
                y = margin
                w = W - 2 * margin
                h = H - 2 * margin
            case "name":
                x = margin
                y = 0
                w = W - 2 * margin
                h = 2 * margin
            case "contour":
                x = 1
                y = 1
                w = W - 2
                h = H - 2
            case _:
                x = 0
                y = 0
                w = W
                h = H

        if self.orientation == "vertical":
            x, y, w, h = H - y - h, x, h, w
        return (x, y, w, h)

    def setName(self, name: str):
        self.name = name
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

    # ================ Device Listener ================

    def widget_touchscreen_listener(self, event: DeviceEvent):
        desc = event.description

        if "setImage" in desc:
            # data = (id, x, y)
            data = desc.split(" ")[1:]
            id, x, y = data

            if float(x) < self.SCREEN_SIZE[0] / 2:
                side = "left"
            else:
                side = "right"
            self.img_id[side] = int(id)

        if "removeImage" in desc:
            # data = (x, y)
            data = desc.split(" ")[1:]
            x, y = data

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
            if self.orientation == "vertical":
                x, y = -y, x
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        if "symbol xy touched" in desc:
            # data = (name, id, x, y, xf, yf)
            _, _, _, _, x, y = event.data  # type: ignore
            if self.orientation == "vertical":
                x, y = -y, x
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        elif "missed" in desc:
            # data = (xf, yf)
            x, y = event.data  # type: ignore
            if self.orientation == "vertical":
                x, y = -y, x
            pos = (x, y)
            self.indicators.append(WTouchPointIndicator(pos, self.update))

        if "clear" in desc:
            for side in ["left", "right"]:
                self.img_id[side] = None
                self.img_name[side] = None

        self.update()

    # ================ PAINT ================

    def draw_text(
        self,
        p: QPainter,
        xywh: tuple[int, int, int, int],
        txt: str,
    ):
        """Draw text in the given rectangle, rotated if vertical orientation."""

        x, y, w, h = xywh
        if self.orientation == "vertical":
            p.save()
            p.translate(x + w / 2, y + h / 2)
            p.rotate(90)
            p.drawText(
                QRect(int(-h / 2), int(-w / 2), h, w),
                Qt.AlignmentFlag.AlignCenter,
                txt,
            )
            p.restore()
        else:
            p.drawText(
                QRect(x, y, w, h),
                Qt.AlignmentFlag.AlignCenter,
                txt,
            )

    def paintEvent(self, event: QPaintEvent):  # type: ignore[override]
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # background
        p.fillRect(*self.get_rect("widget"), WTouchScreen.BG_COLOR)

        # contour
        p.setPen(QPen(WTouchScreen.BG_COLOR.darker(200), 2))
        p.drawRect(*self.get_rect("contour"))

        # disabled overlay
        if self.touchscreen is not None and not self.touchscreen.enabled:
            p.setPen(WTouchScreen.DARK_COLOR)
            font = QFont("Calibri", 16)
            font.setBold(True)
            p.setFont(font)
            self.draw_text(p, self.get_rect("full"), "DISABLED")
        else:
            # display images
            for side in ["left", "right"]:
                id = self.img_id[side]
                if id is None:
                    continue
                name = self.NAME_DICT.get(id, f"UNKNOWN")
                img_clr = (
                    WTouchScreen.DARK_COLOR
                    if id == 8
                    else WTouchScreen.LIGHT_COLOR
                )

                p.fillRect(*self.get_rect(side), img_clr)

                pen_clr = (
                    WTouchScreen.LIGHT_COLOR
                    if img_clr == WTouchScreen.DARK_COLOR
                    else WTouchScreen.DARK_COLOR
                )
                p.setPen(pen_clr)
                font = QFont("Calibri", 11)
                font.setBold(True)
                p.setFont(font)
                self.draw_text(p, self.get_rect(side), name)

        # display touch indicators
        all_indicators = self.indicators.copy()
        for indicator in all_indicators:

            if not indicator.show:
                self.indicators.remove(indicator)
                continue

            cross_lines = indicator.get_cross(
                (self.width(), self.height()),
                WTouchScreen.SCREEN_SIZE,
                self.orientation,
            )

            p.setPen(QPen(QColor(255, 0, 0), 2))
            for line in cross_lines:
                p.drawLine(*line)

        # name
        name_clr = WTouchScreen.BG_COLOR.darker(200)
        name_clr.setAlpha(100)
        p.setPen(name_clr)
        font_name = QFont("Calibri", 8)
        font_name.setBold(True)
        p.setFont(font_name)
        self.draw_text(p, self.get_rect("name"), self.name)

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

        title = QtGui.QAction("TouchScreen Actions", menu)
        title.setDisabled(True)
        menu.addAction(title)
        menu.addSeparator()

        display_menu = QMenu("Display", menu)
        menu.addMenu(display_menu)
        display_left = QMenu("on left", display_menu)
        display_menu.addMenu(display_left)
        display_right = QMenu("on right", display_menu)
        display_menu.addMenu(display_right)

        clear_menu = QMenu("Clear", menu)
        menu.addMenu(clear_menu)

        touch_menu = QMenu("Touch", menu)
        menu.addMenu(touch_menu)

        for img_id, img_name in WTouchScreen.NAME_DICT.items():
            action = QtGui.QAction(img_name, display_left)
            display_left.addAction(action)
            actions[action] = (self.display_image, ("left", img_id))

            action = QtGui.QAction(img_name, display_right)
            display_right.addAction(action)
            actions[action] = (self.display_image, ("right", img_id))

        action = QtGui.QAction("on left", clear_menu)
        clear_menu.addAction(action)
        actions[action] = (self.clear_image, ("left",))

        action = QtGui.QAction("on right", clear_menu)
        clear_menu.addAction(action)
        actions[action] = (self.clear_image, ("right",))

        action = QtGui.QAction("on left", touch_menu)
        touch_menu.addAction(action)
        actions[action] = (self.touch_at, ("left",))

        action = QtGui.QAction("on right", touch_menu)
        touch_menu.addAction(action)
        actions[action] = (self.touch_at, ("right",))

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
        self.simulate_set_xy_image(side, img_id)
        self.update()

    def clear_image(self, side: str):
        """Clear the image on the given side ('left' or 'right')."""
        if side not in ["left", "right"]:
            return
        self.img_id[side] = None
        self.img_name[side] = None
        self.simulate_remove_xy_image(side)
        self.update()

    def touch_at(self, side: str):
        """Simulate a touch at the given side ('left' or 'right')."""
        x = WTouchScreen.SCREEN_SIZE[0] / 2
        x += -400 if side == "left" else 400
        y = 750
        self.indicators.append(WTouchPointIndicator((x, y), self.update))
        self.simulate_touch_event(side)
        self.update()

    def simulate_set_xy_image(self, side: str, img_id: int):
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

    def simulate_remove_xy_image(self, side: str):
        """Simulate a 'removeImage' event on the given side ('left' or 'right')."""
        if self.touchscreen is None:
            return
        name = self.img_name[side]
        self.touchscreen.removeXYImage(name)
        self.img_id[side] = None
        self.img_name[side] = None

    def simulate_touch_event(self, side: str, id: int | None = None):
        """Fire a synthetic 'symbol xy touched' event through the device."""
        if self.touchscreen is None:
            return
        if id is None:
            id = 7
        x = WTouchScreen.SCREEN_SIZE[0] / 2
        x += -400 if side == "left" else 400
        y = 750
        name = side + "_simulation"
        self.touchscreen.fireEvent(
            DeviceEvent(
                "touchscreen",
                self.touchscreen,
                f"symbol xy touched {name} id {id} at 0,0,{x},{y}",
                (name, id, 0, 0, x, y),
            )
        )


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    ts = WTouchScreen(block_wall="bottom")
    # ts = WTouchScreen(block_wall="right")
    ts.setName("Example TouchScreen")
    ts.show()
    screen = app.primaryScreen()
    if screen:
        screen = screen.geometry()
    else:
        raise RuntimeError("No primary screen found")
    ts.move(
        screen.width() // 3 - ts.width() // 2,
        screen.height() // 3 - ts.height() // 2,
    )
    ts.display_image("left", 8)
    ts.display_image("right", 7)
    ts.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 100, 100)
        )
    )
    ts.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 500, 100)
        )
    )
    ts.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen", None, "symbol touched 100 100", (0, 0, 0, 500, 500)
        )
    )
    sys.exit(app.exec())
