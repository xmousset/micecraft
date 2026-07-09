from typing import Any, Callable
import math

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtGui import QPaintEvent, QPainter, QFont, QPen, QColor
from PyQt6.QtCore import (
    QLineF,
    QLine,
    QMargins,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import QWidget, QMenu

from micecraft.soft.device_event.DeviceEvent import DeviceEvent
from micecraft.devices.touchscreen.TouchScreen2 import TouchScreen2
from micecraft.devices.touchscreen.inPy.ts_img_manager import TSImage
from micecraft.soft.gui.VisualDeviceAlarmStatus import VisualDeviceAlarmStatus


class WScreenTouch:
    """A small widget to show a touch point indicator at a given position."""

    def __init__(
        self,
        touch_point: QPointF,
        update_callback: Callable,
        visible_time: int = 3,
        fading_time: int = 2,
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
        self.visible_time: int = visible_time * 1_000
        """Time in milliseconds for which the indicator should be visible."""
        self.fading_time: int = fading_time * 1_000
        """Time in milliseconds for which the indicator should fade out
        (included in the visible time)."""
        self.update_callback: Callable = update_callback

        self.timer: QTimer | None = None

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
        if not isinstance(other, WScreenTouch):
            return False
        return self.touch_point == other.touch_point

    def start_timer(self):
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.end_timer)
        self.timer.start(self.visible_time)

    def end_timer(self):
        if self.timer is not None:
            self.timer.stop()
        self.show = False
        self.update_callback()

    def get_alpha(self) -> int:
        """Get the current alpha value for the indicator, based on the
        remaining time before it disappears."""
        if self.timer is None or not self.timer.isActive():
            return 0
        rt = self.timer.remainingTime()
        if rt < self.fading_time:
            return int(255 * rt / self.fading_time)
        else:
            return 255


class WTouchScreen(QWidget):
    """
    Visual widget for a TouchScreen device. All calculations are based on the
    horizontal orientation. The rotation is applied during the `paintEvent`
    method by swapping x and y coordinates.

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
    IMAGE_RECT = QRect(-16, -16, 33, 33)
    """(x, y, width, height) in *px* for the image rect centered on (0,0)."""

    BG_COLOR = QColor(33, 33, 33)
    CONTOUR_COLOR = QColor(94, 94, 94)
    LIGHT_COLOR = QColor(244, 244, 244)
    DARK_COLOR = QColor(33, 33, 33)
    TOUCH_COLOR = QColor(255, 133, 194)
    CALIBRATION_COLOR = QColor(0, 194, 0)

    def __init__(
        self,
        x: float = 0,
        y: float = 0,
        angle: int = 0,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.angle = angle
        ww = WTouchScreen.WIDGET_SIZE.width()
        wh = WTouchScreen.WIDGET_SIZE.height()

        self.max_dim = max(ww, wh)

        rect = QRect(
            int(x * 200 + 100) - self.max_dim // 2,
            int(y * 200 + 100) - self.max_dim // 2,
            self.max_dim,
            self.max_dim,
        )

        self.setGeometry(rect)
        self.touchscreen = None
        self.name = "WTS"
        self.visualDeviceAlarmStatus = VisualDeviceAlarmStatus()
        self.indicators: list[WScreenTouch] = []
        self.show_calibration = False

    def get_element_rect(
        self,
        element: str,
    ) -> QRect:
        """Get the rectangle for a given element of the widget, with an
        optional transform to apply the block wall rotation.

        Possible values for element:
            - "widget"  : the entire widget
            - "inner"   : the inner area of the widget (without margins)
            - "name"    : the area displaying the widget's name
            - "screen"  : the whole display area (left + margins + right)
        """
        text_h = WTouchScreen.WIDGET_TEXT_HEIGHT
        margin = WTouchScreen.WIDGET_MARGIN

        widget_rect = QRect(
            self.max_dim // 2 - WTouchScreen.WIDGET_SIZE.width() // 2,
            self.max_dim // 2 - WTouchScreen.WIDGET_SIZE.height() // 2,
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

        match element:
            case "widget":
                rect = widget_rect
            case "inner":
                rect = inner_rect
            case "name":
                rect = name_rect
            case "screen":
                rect = screen_rect
            case _:
                raise ValueError(f"Invalid element value: {element}")

        return rect

    def get_touch_cross(
        self,
        indicator: WScreenTouch,
    ) -> tuple[QLineF, QLineF]:
        """Get the horizontal and vertical lines to draw for a given touch
        point indicator, based on its position and the widget's block wall
        orientation."""

        screen = WTouchScreen.SCREEN_SIZE
        wscreen = self.get_element_rect("screen")

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

        cross_center = cross_rect.center().toPointF()

        hline = QLineF(-indicator.size, 0, indicator.size, 0)
        vline = QLineF(0, -indicator.size, 0, indicator.size)

        hline.translate(cross_center)
        vline.translate(cross_center)

        return hline, vline

    def setName(self, name: str):
        self.name = name
        self.update()

    def bindToTouchScreen(self, ts: TouchScreen2):
        """Bind this widget to a TouchScreen device instance or to a
        VirtualTouchScreen instance for testing."""
        if self.touchscreen is not None:
            self.touchscreen.removeDeviceListener(
                self.widget_touchscreen_listener
            )

        self.touchscreen = ts
        self.name = ts.name
        ts.addDeviceListener(self.widget_touchscreen_listener)
        self.update()

    def get_current_display(self) -> list[dict[str, Any]]:
        """Return the active display list from the bound touchscreen."""
        if self.touchscreen is not None:
            return self.touchscreen.getCurrentImageList()
        return []

    # ================ Device Listener ================

    def widget_touchscreen_listener(self, event: DeviceEvent):
        desc = event.description
        point = None

        if "symbol xy touched" in desc:
            # data = (name, id, x, y, xf, yf)
            _, _, _, _, xf, yf = event.data  # type: ignore
            point = QPointF(xf, yf)

        if "missed" in desc:
            # data = (xf, yf)
            xf, yf = event.data  # type: ignore
            point = QPointF(xf, yf)

        if point is not None:
            indicator = WScreenTouch(point, self.update)
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

        p.drawText(QRect(rect), Qt.AlignmentFlag.AlignCenter, txt)
        p.restore()

    def paintEvent(self, event: QPaintEvent):  # type: ignore[override]
        super().paintEvent(event)

        # timers must be created here for thread affinity reasons
        for indicator in self.indicators:
            if indicator.timer is None:
                indicator.start_timer()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self.angle)
        p.translate(-self.width() / 2, -self.height() / 2)

        # background
        p.fillRect(
            self.get_element_rect("widget"),
            WTouchScreen.BG_COLOR,
        )

        # widget contour
        p.setPen(QPen(WTouchScreen.CONTOUR_COLOR, 2))
        contour_rect = self.get_element_rect("widget")
        contour_rect = contour_rect.marginsRemoved(QMargins(1, 1, 1, 1))
        p.drawRect(contour_rect)

        # display images
        for img in self.get_current_display():
            # {
            #     "name": name,
            #     "type": "xy_stripes",
            #     "centerX": centerX,
            #     "centerY": centerY,
            #     "rotation": rotation,
            #     "scale": scale,
            #     "stripe_angle": stripe_angle,
            #     "thickness1": thickness1,
            #     "thickness2": thickness2,
            #     "color1": color1,
            #     "color2": color2,
            #     "unit": unit,
            # }{
            #     "name": name,
            #     "type": "xy_image",
            #     "id": id,
            #     "centerX": centerX,
            #     "centerY": centerY,
            #     "rotation": rotation,
            #     "scale": scale,
            #     "unit": unit,
            # }
            if img["type"] not in ["xy_image", "xy_stripes"]:
                continue

            # side contour
            contour_rect = self.IMAGE_RECT
            margins = QMargins(1, 1, 1, 1)
            contour_rect = contour_rect.marginsAdded(margins)
            p.fillRect(contour_rect, WTouchScreen.CONTOUR_COLOR)

            if img["type"] == "xy_image":
                # image
                img_id = img["id"]
                img_cx = img["centerX"]
                img_cy = img["centerY"]
                img_rot = img.get("rotation", 0)

                screen_rect = self.get_element_rect("screen")
                if img["unit"] == "ratio":
                    img_cx = img_cx * screen_rect.width()
                    img_cy = img_cy * screen_rect.height()

                name = TSImage.get_unicode_from_id(img_id)
                if img_id == TSImage.LIGHT.value:
                    img_clr = WTouchScreen.LIGHT_COLOR
                    pen_clr = WTouchScreen.DARK_COLOR
                else:
                    img_clr = WTouchScreen.DARK_COLOR
                    pen_clr = WTouchScreen.LIGHT_COLOR

                cx_px = int(screen_rect.x() + img_cx)
                cy_px = int(screen_rect.y() + img_cy)

                p.save()
                p.translate(cx_px, cy_px)
                p.rotate(img_rot)
                p.fillRect(self.IMAGE_RECT, img_clr)
                p.setPen(pen_clr)
                font = QFont("Calibri", 16)
                font.setBold(True)
                p.setFont(font)
                self.draw_text(p, self.IMAGE_RECT, name)
                p.restore()

            if img["type"] == "xy_stripes":
                # stripes: position relative, scale and rotation applied
                stripe_angle = img.get("stripe_angle", 0)
                thickness1 = img.get("thickness1", 4)
                thickness2 = img.get("thickness2", 2)
                color1 = QColor(*img.get("color1", (200, 200, 200)))
                color2 = QColor(*img.get("color2", (100, 100, 100)))
                unit = img.get("unit", "ratio")
                img_rot = img.get("rotation", 0)
                img_scale = img.get("scale", 1)
                img_cx = img.get("centerX", 0.5)
                img_cy = img.get("centerY", 0.5)

                screen_rect = self.get_element_rect("screen")
                if unit == "ratio":
                    img_cx = img_cx * screen_rect.width()
                    img_cy = img_cy * screen_rect.height()

                cx_px = int(screen_rect.x() + img_cx)
                cy_px = int(screen_rect.y() + img_cy)

                base_w = WTouchScreen.IMAGE_RECT.width()
                base_h = WTouchScreen.IMAGE_RECT.height()
                w = max(1, int(base_w * img_scale))
                h = max(1, int(base_h * img_scale))

                p.save()
                p.translate(cx_px, cy_px)
                p.rotate(img_rot)
                target_rect = QRect(-w // 2, -h // 2, w, h)
                # base fill
                p.fillRect(target_rect, color1)
                # clip to target rect so stripes don't overflow
                p.setClipRect(target_rect)
                p.setPen(QPen(color2, thickness2))
                p.save()
                p.rotate(stripe_angle)
                # draw stripes across an extended area
                ext = int(math.hypot(w, h) // 2) + max(w, h)
                spacing = max(1, thickness1 + thickness2)
                for i in range(-ext, ext + spacing, spacing):
                    x = i
                    p.drawLine(x, -ext, x, ext)
                p.restore()
                p.restore()

        if self.touchscreen is not None and not self.touchscreen.enabled:
            # display DISABLED
            p.setPen(WTouchScreen.BG_COLOR.darker(200))
            font = QFont("Calibri", 13)
            font.setBold(False)
            p.setFont(font)
            self.draw_text(p, self.get_element_rect("screen"), "DISABLED")

        # calibration overlay
        if self.show_calibration:
            p.setPen(QPen(WTouchScreen.CALIBRATION_COLOR, 2))
            contour_rect = self.get_element_rect("screen")
            p.drawRect(contour_rect)
            dx = contour_rect.width() // 2
            dy = contour_rect.height() // 2
            top_bottom = QLine(
                contour_rect.topLeft(), contour_rect.bottomLeft()
            ).translated(dx, 0)
            left_right = QLine(
                contour_rect.topLeft(), contour_rect.topRight()
            ).translated(0, dy)
            p.drawLine(top_bottom)
            p.drawLine(left_right)

        # display touch indicators
        all_indicators = self.indicators.copy()
        for indicator in all_indicators:

            if not indicator.show:
                self.indicators.remove(indicator)
                continue

            hline, vline = self.get_touch_cross(indicator)
            p.save()
            p.translate(1, 1)  # correct pen width
            touch_color = WTouchScreen.TOUCH_COLOR
            touch_color.setAlpha(indicator.get_alpha())
            p.setPen(QPen(touch_color, 2))
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
        self.draw_text(p, self.get_element_rect("name"), self.name)

        # if isinstance(self.touchscreen, TouchScreen):
        #     self.visualDeviceAlarmStatus.draw(
        #         p,
        #         self.touchscreen,
        #         ellipseRect=QRect(22, 60, 10, 10),
        #         textRect=QRect(-25, 13, 100, 50),
        #     )

        p.end()

    # ================ MENU ================

    def contextMenuEvent(self, event):  # type: ignore[override]
        menu = QMenu(self)

        actions: dict[QtGui.QAction, tuple[Callable, tuple]] = {}

        title = QtGui.QAction("TouchScreen Actions", menu)
        title.setDisabled(True)
        menu.addAction(title)
        menu.addSeparator()

        display_left = QMenu("Display on left", menu)
        menu.addMenu(display_left)
        display_right = QMenu("Display on right", menu)
        menu.addMenu(display_right)
        action = QtGui.QAction("Clear Images", menu)
        menu.addAction(action)
        actions[action] = (self.clear_all_images, ())

        mode_menu = QMenu("Set mode", menu)
        menu.addMenu(mode_menu)
        normal_mode = QtGui.QAction("Normal", menu)
        mode_menu.addAction(normal_mode)
        actions[normal_mode] = (self.set_mode, ("normal",))
        mouse_mode = QtGui.QAction("Mouse", menu)
        mode_menu.addAction(mouse_mode)
        actions[mouse_mode] = (self.set_mode, ("mouse",))
        rat_mode = QtGui.QAction("Rat", menu)
        mode_menu.addAction(rat_mode)
        actions[rat_mode] = (self.set_mode, ("rat",))

        action = QtGui.QAction("Touch left", menu)
        menu.addAction(action)
        actions[action] = (self.touch_on, ("left",))
        action = QtGui.QAction("Touch right", menu)
        menu.addAction(action)
        actions[action] = (self.touch_on, ("right",))

        action = QtGui.QAction("Toggle Calibration", menu)
        menu.addAction(action)
        actions[action] = (self.toggle_calibration, ())

        other_images_left = QMenu("Other Images", display_left)
        display_left.addMenu(other_images_left)
        other_images_right = QMenu("Other Images", display_right)
        display_right.addMenu(other_images_right)

        main_images = [
            TSImage.DARK,
            TSImage.LIGHT,
            TSImage.PLANE,
            TSImage.FLOWER,
            TSImage.TRUE,
            TSImage.FALSE,
        ]
        for member in TSImage._member_map_.values():
            # use the member object to check membership, but pass the integer
            # value to callbacks so callers always receive a plain int
            name = str(member)
            id = member.value
            if member in main_images:
                action = QtGui.QAction(name, display_left)
                display_left.addAction(action)
                actions[action] = (self.display_image, (id, 0.25))

                action = QtGui.QAction(name, display_right)
                display_right.addAction(action)
                actions[action] = (self.display_image, (id, 0.75))
            else:
                action = QtGui.QAction(name, other_images_left)
                other_images_left.addAction(action)
                actions[action] = (self.display_image, (id, 0.25))

                action = QtGui.QAction(name, other_images_right)
                other_images_right.addAction(action)
                actions[action] = (self.display_image, (id, 0.75))

        chosen = menu.exec(self.mapToGlobal(event.pos()))

        if chosen is None:
            print(
                "No action as there is no hardware device bound to this component"
            )
            return

        actions[chosen][0](*actions[chosen][1])

    def display_image(
        self,
        id: int,
        cx: float = 0.5,
        cy: float = 0.5,
        unit: str = "ratio",
    ):
        """Set the image based on its id at the given coordinates."""
        if self.touchscreen is None:
            return

        name = f"simulation_image_{TSImage.get_name_from_id(id)}"

        img = {
            "name": name,
            "type": "xy",
            "id": id,
            "centerX": cx,
            "centerY": cy,
            "rotation": 0,
            "scale": 1,
            "unit": unit,
        }
        self.touchscreen.setXYImage(
            img["name"],
            img["id"],
            img["centerX"],
            img["centerY"],
            img["rotation"],
            img["scale"],
            img["unit"],
        )
        self.update()

    def clear_all_images(self):
        """Clear all images from the display."""
        if self.touchscreen is None:
            return
        self.touchscreen.clear()
        self.update()

    def set_mode(self, mode: str):
        """Set the mode of the touchscreen device."""
        if not isinstance(self.touchscreen, TouchScreen2):
            return
        if mode == "normal":
            self.touchscreen.setNormalMode()
        if mode == "mouse":
            self.touchscreen.setMouseMode()
        if mode == "rat":
            self.touchscreen.setRatMode()

    def touch_on(self, side: str):
        """Simulate a touch at the given side ('left' or 'right')."""
        x = WTouchScreen.SCREEN_SIZE.width() // 2
        x += -400 if side == "left" else 400
        y = 750

        if self.touchscreen is None:
            return

        img = None
        i = 0
        display_list = self.get_current_display()
        while img is None and i < len(display_list):
            if side in display_list[i]["name"]:
                img = display_list[i]
            i += 1

        if img is None:
            self.touchscreen.fireEvent(
                DeviceEvent(
                    "touchscreen",
                    self.touchscreen,
                    f"missed {x},{y}",
                    (x, y),
                )
            )
            return

        name = (
            f"simulation_{side}_image_"
            f"{TSImage.get_name_from_id(img['id'])}"
        )
        self.touchscreen.fireEvent(
            DeviceEvent(
                "touchscreen",
                self.touchscreen,
                f"symbol xy touched {name} id {img['id']} at 0,0,{x},{y}",
                (name, img["id"], 0, 0, x, y),
            )
        )

    def toggle_calibration(self):
        """Toggle the calibration mode of the touchscreen device."""
        self.show_calibration = not self.show_calibration
        if not isinstance(self.touchscreen, TouchScreen2):
            return
        self.touchscreen.toggleCalibration()


def test_mode(comPort: str, widget_angle: int = 0):
    """Test mode with a physical touchscreen device on the given COM port."""
    import sys

    ts = TouchScreen2(comPort)
    app = QtWidgets.QApplication(sys.argv)
    wts = WTouchScreen(angle=widget_angle)
    wts.bindToTouchScreen(ts)
    wts.setName("TouchScreen Widget - Test Mode")
    wts.show()
    screen = app.primaryScreen()
    if screen:
        screen = screen.geometry()
    else:
        raise RuntimeError("No primary screen found")
    wts.move(
        screen.width() // 3 - wts.width() // 2,
        screen.height() // 3 - wts.height() // 2,
    )
    wts.display_image(29, cx=0.25, cy=0.5)
    wts.display_image(30, cx=0.75, cy=0.5)
    sys.exit(app.exec())


if __name__ == "__main__":
    test_mode("COM4", widget_angle=0)
