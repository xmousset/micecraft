from typing import Any, Callable, Literal

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtGui import QPaintEvent, QPainter, QFont, QPen, QColor
from PyQt6.QtCore import QLineF, QMargins, QPointF, QRect, QSize, Qt, QTimer
from PyQt6.QtWidgets import QWidget, QMenu

from micecraft.soft.device_event.DeviceEvent import DeviceEvent
from micecraft.devices.touchscreen.TouchScreen import TouchScreen
from micecraft.soft.gui.VisualDeviceAlarmStatus import VisualDeviceAlarmStatus


class WTouchPointIndicator:
    """A small widget to show a touch point indicator at a given position."""

    def __init__(
        self,
        touch_point: QPointF,
        update_callback: Callable,
        visible_time: int = 10,
        size: int = 3,
    ):
        """Initialize the touch point indicator.

        Parameters:
        -----------
        touch_point: QPointF
            The position (x, y) of the touch point on the screen.
        update_callback: Callable
            A callback function to call when the indicator needs to be updated
            (e.g. removed after the timer ends).
        visible_time: int
            The time in seconds for which the indicator should be visible
            before being removed.
        size: int
            The size in pixels of the cross-hair lines to indicate the touch
            point.
        """
        self.touch_point: QPointF = touch_point
        """Position (x, y) on the screen."""
        self.show: bool = True
        self.size: int = size
        self.visible_time: int = visible_time
        """Time in seconds for which the indicator should be visible."""
        self.update_callback: Callable = update_callback

        self.timer: QTimer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.end_timer)

        self.start_timer()

    def get_rect(self) -> QRect:
        """Get the rectangle area covered by this indicator, based on its
        position and size."""
        return QRect(
            int(self.touch_point.x() - self.size),
            int(self.touch_point.y() - self.size),
            int(self.size * 2),
            int(self.size * 2),
        )

    def __eq__(self, other):
        if not isinstance(other, WTouchPointIndicator):
            return False
        return self.touch_point == other.touch_point

    def start_timer(self):
        self.timer.start(self.visible_time * 1000)

    def end_timer(self):
        try:
            self.timer.stop()
        except Exception:
            pass
        self.show = False
        self.update_callback()

    def get_alpha(self) -> int:
        """Get the current alpha value for the indicator, based on the
        remaining time before it disappears."""
        if not self.timer.isActive():
            return 0
        return int(255 * self.timer.remainingTime() / self.timer.interval())


class WTouchScreen(QWidget):
    """
    Visual widget for a TouchScreen device. All calculations are based on the
    horizontal orientation. The rotation is applied during the `paintEvent`
    method by swapping x and y coordinates.

    - Shows two display areas (left / right halves of the screen) reflecting
      the current image state: full-light, image name, or colour hint.
    - Renders a cross-hair touch indicator at the last touched position.
    - Shows an enabled / disabled status dot and overlay.
    - Right-click menu: simulate left / right touch, set an image on an area.
    """

    SCREEN_SIZE = QSize(1920, 1080)
    """(width, height) in *px* for horizontal orientation."""
    WIDGET_SIZE = QSize(150, 60)
    """(width, height) in *px* for horizontal orientation."""
    WIDGET_TEXT_HEIGHT = 12
    """Margin in *px* between the widget border and the text."""
    WIDGET_MARGIN = 6
    """Margin in *px* between every elements."""

    NAME_DICT: dict[int, str] = {
        8: "DARK",
        7: "LIGHT",
        1: "FLOWER",
        0: "PLANE",
    }
    IMG_DICT: dict[int, str] = {
        8: "",
        7: "",
        1: "✿",
        0: "✈",
    }

    BG_COLOR = QColor(220, 220, 220)
    LIGHT_COLOR = QColor(255, 133, 194)
    DARK_COLOR = QColor(33, 33, 33)

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        block_wall: Literal["left", "top", "right", "bottom"] = "top",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.block_wall = block_wall
        widget_size = WTouchScreen.WIDGET_SIZE
        rect = QRect(
            int((x + 1) * 200),
            int((y + 0.5) * 200),
            widget_size.width(),
            widget_size.height(),
        )
        match block_wall:
            case "top":
                rect.translate(
                    -widget_size.width() // 2,
                    100 - widget_size.height() // 2,
                )
            case "bottom":
                rect.translate(
                    -widget_size.width() // 2,
                    -100 - widget_size.height() // 2,
                )
            case "left":
                widget_size = widget_size.transposed()
                rect.translate(
                    -100 - widget_size.width() // 2,
                    -widget_size.height() // 2,
                )
                rect = rect.transposed()
            case "right":
                widget_size = widget_size.transposed()
                rect.translate(
                    100 - widget_size.width() // 2,
                    -widget_size.height() // 2,
                )
                rect = rect.transposed()
            case _:
                raise ValueError(f"Invalid block_wall value: {block_wall}")

        self.setGeometry(rect)

        self.widget_display: list[dict[str, Any]] = []
        self.touchscreen = None
        self.name = "WTS"

        self.visualDeviceAlarmStatus = VisualDeviceAlarmStatus()

        self.indicators: list[WTouchPointIndicator] = []

    def get_element_rect(
        self,
        element: str,
        transform: bool = False,
    ) -> QRect:
        """Get the rectangle for a given element of the widget, with an
        optional transform to apply the block wall rotation.

        Possible values for element:
            - "widget"  : the entire widget
            - "inner" : the inner border of the widget (inside margins)
            - "name"    : the area displaying the widget's name
            - "screen"  : the whole display area (left + margins + right)
            - "left"    : the left display area
            - "right"   : the right display area
        """
        text_h = WTouchScreen.WIDGET_TEXT_HEIGHT
        margin = WTouchScreen.WIDGET_MARGIN

        # Always compute rects in horizontal space (WIDGET_SIZE = W x H).
        # transform_rect() will map them to the actual widget coordinate space.
        widget_rect = QRect(
            0,
            0,
            WTouchScreen.WIDGET_SIZE.width(),
            WTouchScreen.WIDGET_SIZE.height(),
        )
        inner_rect = widget_rect.marginsRemoved(
            QMargins(margin, margin, margin, margin)
        )

        name_rect = QRect(
            inner_rect.x(),
            inner_rect.y(),
            inner_rect.width(),
            text_h,
        )
        screen_rect = QRect(
            inner_rect.x(),
            inner_rect.y() + text_h + margin,
            inner_rect.width(),
            inner_rect.height() - text_h - margin,
        )
        left_rect = QRect(
            screen_rect.x(),
            screen_rect.y(),
            (screen_rect.width() - margin) // 2,
            screen_rect.height(),
        )
        right_rect = left_rect.translated(left_rect.width() + margin, 0)

        match element:
            case "widget":
                rect = widget_rect
            case "inner":
                rect = inner_rect
            case "name" | "name_area":
                rect = name_rect
            case "screen" | "display_area":
                rect = screen_rect
            case "left":
                rect = left_rect
            case "right":
                rect = right_rect
            case _:
                rect = widget_rect

        if transform:
            rect = self.transform_rect(rect)

        return rect

    def transform_rect(
        self,
        rect: QRect,
    ) -> QRect:
        """Map a rectangle from horizontal space (WIDGET_SIZE = W x H) to
        the actual widget coordinate space, depending on `self.block_wall`.

        Transformations applied to a point (x, y):
            - 'top'    : (x, y)         -> (x, y)       [no change]
            - 'bottom' : (x, y)         -> (W-x, H-y)   [180° rotation]
            - 'right'  : (x, y)         -> (H-y, x)     [90° clockwise]
            - 'left'   : (x, y)         -> (y, W-x)     [90° counter-clockwise]
        """
        W = WTouchScreen.WIDGET_SIZE.width()
        H = WTouchScreen.WIDGET_SIZE.height()
        rx, ry, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()

        match self.block_wall:
            case "top":
                return QRect(rx, ry, rw, rh)
            case "bottom":
                # 180°: (x,y) -> (W-x, H-y)
                return QRect(W - rx - rw, H - ry - rh, rw, rh)
            case "right":
                # 90° CW: (x,y) -> (H-y, x), size: (rw,rh) -> (rh,rw)
                return QRect(H - ry - rh, rx, rh, rw)
            case "left":
                # 90° CCW: (x,y) -> (y, W-x), size: (rw,rh) -> (rh,rw)
                return QRect(ry, W - rx - rw, rh, rw)
            case _:
                raise ValueError(
                    f"Invalid 'block_wall' value: {self.block_wall}"
                )

    def get_line(
        self,
        indicator: WTouchPointIndicator,
    ) -> tuple[QLineF, QLineF]:
        """Get the horizontal and vertical lines to draw for a given touch
        point indicator, based on its position and the widget's block wall
        orientation."""

        screen = WTouchScreen.SCREEN_SIZE
        wscreen = self.get_element_rect("display_area")  # horizontal

        cross_rect = QRect(
            int(
                indicator.touch_point.x() / screen.width() * wscreen.width()
                + wscreen.x()
                - indicator.size
            ),
            int(
                indicator.touch_point.y() / screen.height() * wscreen.height()
                + wscreen.y()
                - indicator.size
            ),
            2 * indicator.size,
            2 * indicator.size,
        )

        cross_rect = self.transform_rect(cross_rect)
        cross_center = cross_rect.center().toPointF()

        hline = QLineF(-indicator.size, 0, indicator.size, 0)
        vline = QLineF(0, -indicator.size, 0, indicator.size)

        hline.translate(cross_center)
        vline.translate(cross_center)

        return hline, vline

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

    def get_current_display(self):
        if self.touchscreen is None:
            return self.widget_display
        else:
            return self.touchscreen.getCurrentImageList()

    # ================ Device Listener ================

    def widget_touchscreen_listener(self, event: DeviceEvent):
        desc = event.description
        point = None

        if "symbol touched" in desc:
            # data = (id, x, y, xf, yf)
            _, _, _, x, y = event.data  # type: ignore
            point = QPointF(x, y)

        if "symbol xy touched" in desc:
            # data = (name, id, x, y, xf, yf)
            _, _, _, _, x, y = event.data  # type: ignore
            point = QPointF(x, y)

        if "missed" in desc:
            # data = (xf, yf)
            x, y = event.data  # type: ignore
            point = QPointF(x, y)

        if point is not None:
            indicator = WTouchPointIndicator(point, self.update)
            if indicator in self.indicators:
                self.indicators.remove(indicator)
            self.indicators.append(indicator)

        self.update()

    # ================ PAINT ================

    def draw_text(
        self,
        p: QPainter,
        rect: QRect,
        txt: str,
    ):
        """Draw text in the given rectangle, rotated if vertical orientation."""

        p.save()
        p.translate(rect.center())

        match self.block_wall:
            case "left":
                p.rotate(-90)
            case "right":
                p.rotate(90)
            case "bottom":
                p.rotate(180)
        p.drawText(
            QRect(
                int(-rect.height() / 2),
                int(-rect.width() / 2),
                rect.height(),
                rect.width(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            txt,
        )
        p.restore()

    def paintEvent(self, event: QPaintEvent):  # type: ignore[override]
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # background
        p.fillRect(
            self.get_element_rect("widget", True), WTouchScreen.BG_COLOR
        )

        # contour
        p.setPen(QPen(WTouchScreen.BG_COLOR.darker(200), 2))
        p.drawRect(self.get_element_rect("contour", True))

        # display images
        for img in self.widget_display:
            if "left" in img["name"]:
                side = "left"
            elif "right" in img["name"]:
                side = "right"
            else:
                continue

            name = self.IMG_DICT.get(img["id"], f"UNKNOWN")
            img_clr = (
                WTouchScreen.DARK_COLOR
                if img["id"] == 8
                else WTouchScreen.LIGHT_COLOR
            )

            p.fillRect(self.get_element_rect(side, True), img_clr)

            pen_clr = (
                WTouchScreen.LIGHT_COLOR
                if img_clr == WTouchScreen.DARK_COLOR
                else WTouchScreen.DARK_COLOR
            )
            p.setPen(pen_clr)
            font = QFont("Calibri", 16)
            font.setBold(True)
            p.setFont(font)
            self.draw_text(p, self.get_element_rect(side, True), name)

        if self.touchscreen is not None and not self.touchscreen.enabled:
            # disabled DISABLED
            p.setPen(WTouchScreen.BG_COLOR.darker(200))
            font = QFont("Calibri", 13)
            font.setBold(False)
            p.setFont(font)
            self.draw_text(
                p, self.get_element_rect("display_area", True), "DISABLED"
            )

        # display touch indicators
        all_indicators = self.indicators.copy()
        for indicator in all_indicators:

            if not indicator.show:
                self.indicators.remove(indicator)
                continue

            hline, vline = self.get_line(indicator)
            p.save()
            p.translate(1, 1)  # correct pen width
            p.setPen(QPen(QColor(255, 0, 0, alpha=indicator.get_alpha()), 2))
            p.drawLine(hline)
            p.drawLine(vline)
            p.restore()

        # name
        name_clr = WTouchScreen.BG_COLOR.darker(200)
        name_clr.setAlpha(100)
        p.setPen(name_clr)
        font_name = QFont("Calibri", 8)
        font_name.setBold(True)
        p.setFont(font_name)
        self.draw_text(p, self.get_element_rect("name_area", True), self.name)

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

        cx = WTouchScreen.SCREEN_SIZE.width() / 2
        cx += -400 if side == "left" else 400
        cy = 750
        name = f"simulation_{side}_image_{WTouchScreen.NAME_DICT[img_id]}"

        img = {
            "name": name,
            "type": "xy",
            "id": img_id,
            "centerX": cx,
            "centerY": cy,
            "rotation": 0,
            "scale": 1,
        }

        self.widget_display.append(img)

        if self.touchscreen is not None:
            self.touchscreen.setXYImage(
                img["name"],
                img["id"],
                img["centerX"],
                img["centerY"],
                img["rotation"],
                img["scale"],
            )
        self.update()

    def clear_image(self, side: str):
        """Clear the image on the given side ('left' or 'right')."""
        if side not in ["left", "right"]:
            return
        if self.touchscreen is not None:
            img_to_remove = [
                img
                for img in self.touchscreen.getCurrentImageList()
                if side not in img["name"]
            ]
            for img in img_to_remove:
                self.touchscreen.removeXYImage(img["name"])

        img_to_remove = [
            img for img in self.widget_display if side in img["name"]
        ]
        for img in img_to_remove:
            self.widget_display = [
                img for img in self.widget_display if side not in img["name"]
            ]
        self.update()

    def touch_at(self, side: str):
        """Simulate a touch at the given side ('left' or 'right')."""
        x = WTouchScreen.SCREEN_SIZE.width() // 2
        x += -400 if side == "left" else 400
        y = 750
        self.indicators.append(
            WTouchPointIndicator(QPointF(x, y), self.update)
        )

        if self.touchscreen is None:
            self.update()
            return

        img = None
        i = 0
        while img is None and i < len(self.widget_display):
            if side in self.widget_display[i]["name"]:
                img = self.widget_display[i]
            i += 1

        if img is None:
            return

        name = (
            f"simulation_{side}_image_"
            f"{WTouchScreen.NAME_DICT.get(img['id'], 'UNKNOWN')}"
        )
        self.touchscreen.fireEvent(
            DeviceEvent(
                "touchscreen",
                self.touchscreen,
                f"symbol xy touched {name} id {img['id']} at 0,0,{x},{y}",
                (name, img["id"], 0, 0, x, y),
            )
        )


def start_touch(x: float, y: float):
    ts.widget_touchscreen_listener(
        DeviceEvent(
            "touchscreen",
            None,
            "symbol touched 100 100",
            (
                0,
                0,
                0,
                x,
                y,
            ),
        )
    )


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    # ts = WTouchScreen(block_wall="top")
    ts = WTouchScreen(block_wall="bottom")
    # ts = WTouchScreen(block_wall="left")
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
    start_touch(560, 750)
    start_touch(1360, 750)
    start_touch(
        WTouchScreen.SCREEN_SIZE.width() / 2,
        WTouchScreen.SCREEN_SIZE.height() / 2,
    )
    start_touch(0, 0)
    start_touch(
        WTouchScreen.SCREEN_SIZE.width(),
        0,
    )
    start_touch(
        0,
        WTouchScreen.SCREEN_SIZE.height(),
    )
    start_touch(
        WTouchScreen.SCREEN_SIZE.width(),
        WTouchScreen.SCREEN_SIZE.height(),
    )
    sys.exit(app.exec())
