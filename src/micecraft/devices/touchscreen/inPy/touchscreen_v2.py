import math
import random
import traceback
from time import sleep
from typing import Any
from pathlib import Path

import pygame
import serial


class ScreenImage:
    """A pygame.Surface with a name and normalized position."""

    def __init__(
        self,
        surface: pygame.Surface,
        cx: int | float,
        cy: int | float,
        unit: str,
        name: str,
        idx: int | None,
    ):
        self.surface: pygame.Surface = surface
        """pygame.Surface of the image to display"""
        self.cx: float = cx
        """center of image in pixels"""
        self.cy: float = cy
        """center of image in pixels"""
        self.unit: str = unit
        """unit of cx/cy: 'px', 'cm', or 'ratio'"""
        self.name: str = name
        """name of the image"""
        self.idx: int | None = idx
        """index of the image, None if not from list"""

    def __str__(self) -> str:
        return self.name


class ScreenTouches:
    """A pygame.Surface of a touch point."""

    def __init__(self, touch_id: int, x: int, y: int):
        self.touch_id = touch_id
        self.x = x
        self.y = y
        self.surface = pygame.Surface((20, 20), pygame.SRCALPHA)


class DisplayOnlyManager:
    """Pygame display manager.

    All image positions are expressed as normalized coordinates (0.0 - 1.0)
    *within the active area*.  The active area itself is expressed as
    normalized coordinates relative to the full display.
    """

    def __init__(self):
        """Create a pygame window."""
        pygame.init()

        # Create the screen display first.
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        """Whole Screen."""

        pygame.display.set_caption("LMT TouchScreen")
        pygame.mouse.set_visible(False)

        self.area = pygame.Surface(
            self.screen.get_size(),
            flags=pygame.SRCALPHA,
        )
        """Active area of the screen."""
        self.area.fill((0, 0, 0))  # clear the active area to black

        self.area_parameters: tuple[float, tuple[int, int]] = (0.0, (0, 0))
        """(rotation, center).
        Note: The center is the point around which the rotation is applied
        (screen coordinates).
        """

        self.images: dict[str, ScreenImage] = {}
        """all displayed images, keyed by name"""

        self.images_offset: tuple[int, int] = (0, 0)
        """global offset of all images (dx, dy) in pixels"""

        self.touches: dict[int, tuple[int, int]] = {}
        """current touch positions, keyed by touch ID"""

        self.touches_offset: tuple[int, int] = (0, 0)
        """global offset of all touches (dx, dy) in pixels"""

        self.touches_axis_inversion = (False, False)
        """(invert_x, invert_y) whether to invert touch axes"""

        self.touches_size = (40, 5)
        """(size, thickness) of the cross in pixels."""

        self.show_calibration: bool = False
        """Whether to show calibration lines or not."""

        self.clock = pygame.time.Clock()
        """pygame clock for frame rate limiting"""

        self.set_normal_mode()

    # Area
    # ----------------
    def clear_area(self) -> None:
        """Clear the active area to black."""
        self.area.fill((0, 0, 0))

    def set_area_size(self, width: int, height: int) -> None:
        """Set the active area of the screen."""
        self.area = pygame.Surface((width, height), flags=pygame.SRCALPHA)
        self.clear_area()

    def set_area_parameters(
        self,
        angle: float,
        center: tuple[int, int],
    ) -> None:
        """Set the transformation for the active area."""
        self.area_parameters = (angle % 360, center)

    # Utilities
    # ----------------
    def convert_to_px(
        self,
        value: float,
        unit: str,
        axis: str | None = None,
    ) -> int:
        """Convert a value in pixels from pixels, centimeters, area ratio,
        or screen ratio (0.0 - 1.0).

        **units**: "*px*", "*cm*", "*ratio*", "*screen ratio*".

        **ratio**: (0.0 - 1.0) is relative to the specified axis of the
        displayed area (or the full screen).
        """
        if unit == "px":
            return int(value)
        elif unit == "ratio":
            if axis not in ("x", "y"):
                raise ValueError("Axis must be 'x' or 'y' for ratio unit")
            aw, ah = self.area.get_size()
            dim = aw if axis == "x" else ah
            return int(value * dim)
        elif unit == "cm":
            return int(value * self.px_over_cm())
        elif unit == "screen ratio":
            if axis not in ("x", "y"):
                raise ValueError("Axis must be 'x' or 'y' for ratio unit")
            sw, sh = self.screen.get_size()
            dim = sw if axis == "x" else sh
            return int(value * dim)
        else:
            raise ValueError(f"Unknown unit: {unit}")

    def px_over_cm(self) -> float:
        """Return the number of pixels per centimeter for the given axis."""
        ppi = 96  # pixels per inch
        cpi = 2.54  # cm per inches
        return ppi / cpi

    def clear(self) -> None:
        """Clear all images and touches from the display. Also clears the
        active area to black."""
        self.screen.fill((0, 0, 0))  # clear the display to black
        self.remove_all_images()
        self.remove_all_touches()
        self.area.fill((0, 0, 0))  # clear the active area to black

    # Offsets
    # ----------------
    def set_image_offset(self, dx: int, dy: int) -> None:
        """Set a global offset for all images (in pixels)."""
        self.images_offset = (dx, dy)

    def set_touch_offset(self, dx: int, dy: int) -> None:
        """Set a global offset for all touches (in pixels)."""
        self.touches_offset = (dx, dy)

    # Image
    # ----------------

    def add_image(
        self,
        image: ScreenImage,
    ) -> None:
        """Add or update a surface centered at the given active-area position.

        Args:
            surface: A pygame.Surface to display.
            x:  Horizontal center in pixels within the active area.
            y:  Vertical center in pixels within the active area.
            name:    Unique slot identifier.  Overwrites any existing entry.
        """
        self.images[image.name] = image

    def remove_image(self, name: str) -> None:
        if name in self.images:
            self.images.pop(name)

    def remove_all_images(self) -> None:
        self.images.clear()

    def remove_all_touches(self) -> None:
        self.touches.clear()

    # Touches
    # ----------------
    def touch_to_screen_coords(
        self,
        value: float,
        axis: str,
        clip: bool = True,
    ):
        """Convert a normalized touch coordinate (0.0 - 1.0) to screen pixels."""
        if axis not in ("x", "y"):
            raise ValueError("Axis must be 'x' or 'y'")
        ax = 0 if axis == "x" else 1
        s_size = self.screen.get_size()
        dim = s_size[ax]
        if self.touches_axis_inversion[ax]:
            value = 1.0 - value
        coord = int(value * dim)
        if clip:
            coord = max(0, min(coord, dim))
        else:
            if coord < 0 or coord > dim:
                return None
        return coord

    def screen_to_area_coords(
        self, x: int, y: int
    ) -> tuple[tuple[int, int], bool]:
        """Convert screen coordinates into the active-area coordinates and
        indicate if the coordinates are out of bounds.

        This is the exact inverse of the render() transform:
        - render() rotates the area surface CCW by `angle` around its center,
          then blits it so its center lands at area_parameters center (cx, cy).
        - The inverse pivot must therefore be (cx, cy), not the screen center.
        """
        angle, (acx, acy) = self.area_parameters
        aw, ah = self.area.get_size()

        # translate to the rotation pivot used in render()
        dx = x - acx
        dy = y - acy
        theta = math.radians(angle)
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)

        # inverse of the CCW rotation used by pygame.transform.rotate
        a = dx * cos_theta - dy * sin_theta + aw / 2.0
        b = dx * sin_theta + dy * cos_theta + ah / 2.0

        # crop to area bounds
        oob = a < 0 or a >= aw or b < 0 or b >= ah
        return (int(round(a)), int(round(b))), oob

    def add_touch(self, touch_id: Any, x: int, y: int) -> None:
        """Register an active touch point (pixel coordinates)."""
        self.touches[touch_id] = (x, y)

    def remove_touch(self, touch_id: Any) -> None:
        if touch_id in self.touches:
            self.touches.pop(touch_id)

    def get_touches(self) -> dict:
        """Return a snapshot of active touch points: {touch_id: (x, y)}."""
        return dict(self.touches)

    def hit_test(self, x: int, y: int) -> list[ScreenImage]:
        """Return a list of every image whose bounding rect contains (x, y)."""
        images_touched = []
        for img in self.images.values():
            s: pygame.Surface = img.surface
            sw = s.get_width()
            sh = s.get_height()
            cx = self.convert_to_px(img.cx, img.unit, "x")
            cy = self.convert_to_px(img.cy, img.unit, "y")
            if (cx - sw / 2 <= x <= cx + sw / 2) and (
                cy - sh / 2 <= y <= cy + sh / 2
            ):
                images_touched.append(img)
        return images_touched

    # Calibration
    # ----------------
    def set_show_calibration(self, enabled: bool) -> None:
        self.show_calibration = enabled

    def toggle_calibration(self) -> None:
        self.show_calibration = not self.show_calibration

    def get_axes(
        self,
        name: str,
        size: int,
        color: tuple[int, int, int],
        font: pygame.font.Font,
        line_width: int = 3,
    ) -> pygame.Surface:
        """Return a surface with a horizontal and vertical axis drawn."""
        axes = pygame.Surface((size, size), flags=pygame.SRCALPHA)
        # X axis (right)
        pygame.draw.line(
            axes,
            color,
            (0, size // 2),
            (size, size // 2),
            line_width,
        )
        pygame.draw.polygon(
            axes,
            color,
            [
                (size, size // 2),
                (size - 3 * line_width, size // 2 - 2 * line_width),
                (size - 3 * line_width, size // 2 + 2 * line_width),
            ],
        )
        # Y axis (down)
        pygame.draw.line(
            axes,
            color,
            (size // 2, 0),
            (size // 2, size),
            line_width,
        )
        pygame.draw.polygon(
            axes,
            color,
            [
                (size // 2, size),
                (size // 2 - 2 * line_width, size - 3 * line_width),
                (size // 2 + 2 * line_width, size - 3 * line_width),
            ],
        )
        # graph name
        txt = font.render(name, True, color)
        axes.blit(
            txt,
            (
                size // 2 - txt.get_width() - line_width,
                size // 2 - txt.get_height() - line_width,
            ),
        )
        # X axis
        txt = font.render("X axis", True, color)
        axes.blit(
            txt,
            (
                size - txt.get_width(),
                size // 2 + 3 * line_width,
            ),
        )
        # Y axis
        txt = font.render("Y axis", True, color)
        axes.blit(
            txt,
            (
                size // 2 + 3 * line_width,
                size - txt.get_height(),
            ),
        )
        return axes

    def get_calibration(self):
        """Return a pygame.Surface with calibration lines and extra
        diagnostic drawings.

        The surface is divided by the central cross into four quarters.
        Top-left: active-area axis arrows (green)
        Top-right: absolute screen axis arrows (red)
        Bottom-left: area dimensions and transform (px / cm / ratio)
        Bottom-right: three equal squares of 1 cm size with labels
        (px, cm, ratio)
        """
        area_size = self.area.get_size()
        cali = pygame.Surface(area_size, flags=pygame.SRCALPHA)
        cali.fill((0, 0, 0, 0))  # transparent

        aw, ah = area_size

        # Prepare font
        try:
            font = pygame.font.SysFont(None, 18)
        except Exception:
            pygame.font.init()
            font = pygame.font.SysFont(None, 18)

        # Lines
        # ----------------
        # area lines (green)
        pygame.draw.rect(cali, (0, 255, 0), (0, 0, aw, ah), 3)
        pygame.draw.line(cali, (0, 255, 0), (aw // 2, 0), (aw // 2, ah), 3)
        pygame.draw.line(cali, (0, 255, 0), (0, ah // 2), (aw, ah // 2), 3)

        # screen center (red)
        sw, sh = self.screen.get_size()
        (ax, ay), oob = self.screen_to_area_coords(sw // 2, sh // 2)
        if not oob:
            pygame.draw.circle(cali, (255, 0, 0), (ax, ay), 6)

        # Top-left: active-area axes
        # ----------------
        axes = self.get_axes("AREA", min(aw, ah) // 3, (0, 255, 0), font)
        tl_x = aw // 4
        tl_y = ah // 4
        cali.blit(
            axes,
            (tl_x - axes.get_width() // 2, tl_y - axes.get_height() // 2),
        )

        # Top-right: screen axes (red)
        # ----------------
        # Compute an anchor in screen space (near top-right) and map it
        # into area coordinates so the arrows indicate the absolute
        # screen +X/+Y directions (not the area axes).
        axes = self.get_axes("SCREEN", min(aw, ah) // 3, (255, 0, 0), font)
        tr_x = 3 * aw // 4
        tr_y = ah // 4
        axes = pygame.transform.rotate(axes, -self.area_parameters[0])
        cali.blit(
            axes,
            (tr_x - axes.get_width() // 2, tr_y - axes.get_height() // 2),
        )

        # Bottom-left: area dimensions and transform
        # ----------------
        bl_x = aw // 4
        bl_y = 3 * ah // 4
        aw_cm = aw / self.px_over_cm()
        ah_cm = ah / self.px_over_cm()
        aw_ratio = aw / sw
        ah_ratio = ah / sh
        angle, (cx, cy) = self.area_parameters

        lines = [
            f"area: {aw} x {ah} px",
            f"area: {aw_cm:.2f} x {ah_cm:.2f} cm",
            f"area: {aw_ratio:.2f} x {ah_ratio:.2f} ratio",
            f"angle: {angle:.0f} deg",
            f"center: ({cx}, {cy}) px",
        ]
        oy = 0
        for L in lines:
            surf_txt = font.render(L, True, (255, 255, 0))
            cali.blit(surf_txt, (bl_x, bl_y + oy))
            oy += surf_txt.get_height() + 4

        # Bottom-right: three equal squares (1 cm size)
        # ----------------
        br_area_x = 3 * aw // 4
        br_area_y = 3 * ah // 4
        # compute 2cm in pixels on each axis and use their average as square size
        size_px_x = self.convert_to_px(2, "cm", "x")
        size_px_y = self.convert_to_px(2, "cm", "y")
        size_px = int((size_px_x + size_px_y) / 2)
        if size_px < 4:
            size_px = 4
        gap = 8

        units = [
            [f"x: {size_px} px", f"y: {size_px} px"],
            ["x: 2 cm", "y: 2 cm"],
            [f"x: {size_px / aw:.2f} %", f"y: {size_px / ah:.2f} %"],
        ]

        # place three squares along a horizontal line (diagonal visual if desired)
        # centered at (br_area_x, br_area_y)
        total_width = 3 * size_px + 2 * gap
        start_x = int(br_area_x - total_width / 2)
        start_y = int(br_area_y - size_px / 2)

        for i, label in enumerate(units):
            rx = start_x + i * (size_px + gap)
            ry = start_y
            # clamp inside active area
            rx = max(0, min(aw - size_px, rx))
            ry = max(0, min(ah - size_px, ry))

            pygame.draw.rect(
                cali, (255, 255, 255), (rx, ry, size_px, size_px), 2
            )
            txts = [font.render(l, True, (255, 255, 255)) for l in label]
            for j, txt in enumerate(txts):
                tx_off = rx + (size_px - txt.get_width()) // 2
                ty_off = (
                    ry
                    + j * (size_px // len(txts))
                    + (size_px // len(txts) - txt.get_height()) // 2
                )
                cali.blit(txt, (tx_off, ty_off))

        return cali

    # Mode
    # ----------------
    def set_mode(
        self,
        area_size: tuple[float, float],
        area_center: tuple[float, float],
        area_rotation: float,
        coord_unit: str = "px",
    ) -> None:
        """Set the display mode by specifying the active area size, center and
        rotation."""
        self.screen.fill((0, 0, 0))  # clear the display to black

        if coord_unit == "ratio":
            coord_unit = "screen ratio"

        aw = self.convert_to_px(area_size[0], coord_unit, "x")
        ah = self.convert_to_px(area_size[1], coord_unit, "y")
        self.set_area_size(aw, ah)

        acx = self.convert_to_px(area_center[0], coord_unit, "x")
        acy = self.convert_to_px(area_center[1], coord_unit, "y")
        self.set_area_parameters(area_rotation, (acx, acy))

    def set_normal_mode(self) -> None:
        """Set the display to normal mode."""
        self.set_mode(
            area_size=(1, 1),
            area_center=(0.5, 0.5),
            area_rotation=0,
            coord_unit="screen ratio",
        )
        self.touches_axis_inversion = (True, True)

    def set_mouse_mode(self) -> None:
        """Set the display to mouse mode."""
        self.set_mode(
            area_size=(1, 0.5),
            area_center=(0.5, 0.75),
            area_rotation=0,
            coord_unit="screen ratio",
        )
        self.touches_axis_inversion = (False, False)

    def set_rat_mode(self) -> None:
        """Set the display to rat mode."""
        aw = self.convert_to_px(1, "screen ratio", "y")
        ah = self.convert_to_px(0.25, "screen ratio", "x")
        acx = self.convert_to_px(0.125, "screen ratio", "x")
        acy = self.convert_to_px(0.5, "screen ratio", "y")
        self.set_mode(
            area_size=(aw, ah),
            area_center=(acx, acy),
            area_rotation=-90,
            coord_unit="px",
        )
        self.touches_axis_inversion = (True, True)

    # Rendering
    # ----------------

    def render(self, fps: int = 30) -> None:
        """Clear the display, blit all images, optionally draw calibration, flip."""

        # create area copy to draw on
        area = self.area.copy()

        # blit all images
        for img in self.images.values():
            s = img.surface
            cx = self.convert_to_px(img.cx, img.unit, "x")
            cy = self.convert_to_px(img.cy, img.unit, "y")
            x = cx + self.images_offset[0] - s.get_width() // 2
            y = cy + self.images_offset[1] - s.get_height() // 2
            area.blit(s, (x, y))

        # blit all touches
        for x, y in self.touches.values():
            x += self.touches_offset[0]
            y += self.touches_offset[1]
            ts, tt = self.touches_size
            s = pygame.Surface((ts, ts), pygame.SRCALPHA)
            pygame.draw.line(s, (0, 255, 0), (0, 0), (ts, ts), tt)
            pygame.draw.line(s, (0, 255, 0), (0, ts), (ts, 0), tt)
            area.blit(s, (x - ts // 2, y - ts // 2))

        # draw calibration if enabled
        if self.show_calibration:
            cali = self.get_calibration()
            area.blit(cali, (0, 0))

        # rotate window
        angle, (cx, cy) = self.area_parameters
        area = pygame.transform.rotate(area, angle)

        # translate window
        w, h = area.get_size()
        tx = cx - w // 2
        ty = cy - h // 2

        # blit window
        self.screen.blit(area, (tx, ty))

        # update display
        pygame.display.update()

        # limit the frame rate
        self.clock.tick(fps)

    def quit(self) -> None:
        pygame.quit()


class TouchScreen:
    """Serial communication layer and image/surface lifecycle manager.

    Reads commands from a serial port and dispatches them to a ScreenManager.
    Also creates pygame.Surfaces (from files or procedurally) and registers
    them with the ScreenManager.
    """

    def __init__(
        self,
        test_mode: bool = False,
    ):

        print("Starting TouchScreen")

        if not test_mode:
            print("Starting serial...")
            self.ser = serial.Serial(
                "/dev/ttyS0",
                baudrate=115200,
                write_timeout=2,
                timeout=0,
            )  # 115200
            # parity = serial.PARITY_ODD
            # stopbits = serial.STOPBITS_TWO
            # bytesize = serial.SEVENBITS
            print(self.ser.name)
            self.send("Starting touchscreen...")
        else:
            self.ser = None
            self.send("Test mode: no serial")

        self.last_error: str = ""
        self.input_buffer: str = ""
        self.display = DisplayOnlyManager()
        self.running: bool = True
        self._loaded_images: dict[int, pygame.Surface] = {}
        """Dictionary of loaded images: id -> surface"""

        self.imageSize = 256
        """Image size in pixels."""
        self.transparency = 255
        """All image transparency (0-255)."""

        self.send("Touchscreen started")

    # Parameters
    # ----------------
    def getScreenSize(self) -> tuple[int, int]:
        """Return the size of the full screen in pixels."""
        return self.display.screen.get_size()

    def getAreaSize(self) -> tuple[int, int]:
        """Return the size of the active area in pixels."""
        return self.display.area.get_size()

    def getImageSize(self) -> int:
        """Return the size of images in pixels."""
        return self.imageSize

    def setImageSize(
        self,
        size: int,
        unit: str = "px",
        axis: str | None = None,
    ) -> None:
        """Set the size of images in pixels, centimeters, or ratio
        (0.0 - 1.0).

        **units**: "*px*", "*cm*", "*ratio*"
        .
        **axis**: "x" or "y" for ratio unit.

        **ratio**: is relative to the bigger dimension of the displayed area.
        """
        self.imageSize = self.display.convert_to_px(size, unit, axis)
        self.load_all_images()

    # Calibration
    # ----------------
    def setShowCalibration(self, enabled: bool) -> None:
        self.display.show_calibration = bool(enabled)

    def toggleCalibration(self) -> None:
        self.display.show_calibration = not self.display.show_calibration

    # Finger touches
    # ----------------

    def check_if_touch_on_image(
        self,
        area_pos: tuple[int, int],
        screen_pos: tuple[int, int],
    ) -> None:
        ax, ay = area_pos
        images_touched = self.display.hit_test(ax, ay)
        if images_touched:
            for image in images_touched:
                self.send(
                    f"symbol xy touched {image.name} id {image.idx} "
                    f"at {image.cx:.4f},{image.cy:.4f},"
                    f"{screen_pos[0]},{screen_pos[1]}"
                )
        else:
            self.send(f"missed {screen_pos[0]},{screen_pos[1]}")

    # Surface creation
    # ----------------

    def load_image(
        self,
        filepath: Path,
    ) -> tuple[pygame.Surface, int]:
        """Load an image file and create a pygame.Surface."""
        surf = pygame.image.load(filepath).convert_alpha()
        w, h = surf.get_size()
        scale = self.imageSize / max(w, h)
        surf = pygame.transform.scale(surf, (int(w * scale), int(h * scale)))
        surf.fill(
            (255, 255, 255, self.transparency),
            special_flags=pygame.BLEND_RGBA_MULT,
        )

        id = int(filepath.stem.split("_", 1)[0])
        return surf, id

    def load_all_images(self) -> None:
        """Load all images in current working directory and register them."""
        here = Path(__file__).parent
        sfx = [".png", ".jpg", ".jpeg"]
        list_paths = sorted([p for p in here.iterdir() if p.suffix in sfx])

        for path in list_paths:
            surf, idx = self.load_image(path)
            self._loaded_images[idx] = surf

    def getImage(self, index: int) -> pygame.Surface:
        """Return the pygame.Surface for a given image index, or None if not found."""
        image = None
        try:
            image = self._loaded_images[index]
        except:
            self.sendErrorFeedBack(f"getImage: Image key error:{index}")
            image = self._loaded_images[0]  # error image
        return image

    def getStripe(
        self,
        thickness1: int = 10,
        thickness2: int = 10,
        angle: float = 0.0,
        color1: tuple = (255, 255, 255),
        color2: tuple = (0, 0, 0),
    ) -> pygame.Surface:
        """Create a striped surface with specified colors and thicknesses."""
        t1 = max(0, int(thickness1))
        t2 = max(0, int(thickness2))
        stripe_height = t1 + t2

        if stripe_height <= 0:
            return pygame.Surface(
                (self.imageSize, self.imageSize),
                flags=pygame.SRCALPHA,
            )

        diag = math.ceil(math.hypot(self.imageSize, self.imageSize))

        surf = pygame.Surface(
            (diag, diag),
            flags=pygame.SRCALPHA,
        )

        for y in range(0, diag, stripe_height):
            if t1 > 0:
                pygame.draw.rect(surf, color1, (0, y, diag, t1))
            if t2 > 0:
                pygame.draw.rect(surf, color2, (0, y + t1, diag, t2))

        surf = pygame.transform.rotate(surf, angle % 180)

        x = surf.get_width() // 2 - self.imageSize // 2
        y = surf.get_height() // 2 - self.imageSize // 2
        final = pygame.Surface(
            (self.imageSize, self.imageSize),
            flags=pygame.SRCALPHA,
        )
        final.blit(surf, (-x, -y))
        return final

    def setXYImage(
        self,
        name: str,
        index: int,
        x: float,
        y: float,
        r: float = 0.0,
        s: float = 1.0,
        coord_unit: str = "px",
    ) -> None:
        """Set an image by its center coordinates (x, y) in pixels,
        centimeters, or ratio (0.0 - 1.0) depending on the unit.

        **units**: "*px*", "*cm*", "*ratio*".
        **ratio**: is relative to the bigger dimension of the displayed area.
        """

        surf = self.getImage(index)
        if surf is None:
            self.sendErrorFeedBack(f"setXYImage: index {index:03d} not found")
            return
        surf = pygame.transform.rotozoom(surf, r, s)
        image = ScreenImage(surf, x, y, coord_unit, name, index)
        self.display.add_image(image)

    def setXYStripes(
        self,
        name: str,
        x: float,
        y: float,
        r: float = 0.0,
        s: float = 1.0,
        stripe_angle: float = 0.0,
        thickness1: int = 10,
        thickness2: int = 10,
        color1: tuple = (255, 255, 255),
        color2: tuple = (0, 0, 0),
        coord_unit: str = "px",
    ) -> pygame.Surface:
        """Set an image by its center coordinates (x, y) in pixels,
        centimeters, or ratio (0.0 - 1.0) depending on the unit.

        Parameters:
        -----------
        name: str
            Name of the image.
        x: float
            X coordinate of the image center (according to the specified unit).
        y: float
            Y coordinate of the image center (according to the specified unit).
        r: float
            Rotation angle in degrees.
        s: float
            Scale factor.
        stripe_angle: float
            Angle of the stripes in degrees.
        thickness1: int
            Thickness of the first stripe color in pixels.
        thickness2: int
            Thickness of the second stripe color in pixels.
        color1: tuple
            RGB color of the first stripe.
        color2: tuple
            RGB color of the second stripe.
        coord_unit: str
            Unit of the (x, y) coordinates ('px', 'cm', or 'ratio'). 'ratio'
            is relative to the displayed area dimensions.
        """
        surf = self.getStripe(
            thickness1,
            thickness2,
            stripe_angle,
            color1,
            color2,
        )
        surf = pygame.transform.rotozoom(surf, r, s)
        image = ScreenImage(surf, x, y, coord_unit, name, None)
        self.display.add_image(image)
        return surf

    def removeXYImage(self, name: str) -> None:
        """Remove an image by its name."""
        self.display.remove_image(name)

    def removeXYStripes(self, name: str) -> None:
        """Remove a striped image by its name."""
        self.display.remove_image(name)

    def removeAllImages(self) -> None:
        """Remove all images from the screen."""
        self.display.remove_all_images()

    # Background
    # ----------------
    def setBgColor(self, color: tuple[int, int, int]) -> None:
        """Set the background color of the screen."""
        self.display.area.fill(color)

    def setBgStripes(
        self,
        thickness1: int = 10,
        thickness2: int = 10,
        angle: float = 0.0,
        color1: tuple = (255, 255, 255),
        color2: tuple = (0, 0, 0),
    ) -> None:
        """Set the background to a striped pattern.

        Parameters:
        -----------
        thickness1: int
            Thickness of the first stripe color in pixels.
        thickness2: int
            Thickness of the second stripe color in pixels.
        angle: float
            Angle of the stripes in degrees.
        color1: tuple
            RGB color of the first stripe.
        color2: tuple
            RGB color of the second stripe.
        """

        diag = math.ceil(
            math.hypot(
                self.display.area.get_width(),
                self.display.area.get_height(),
            )
        )

        big_bg = pygame.Surface((diag, diag), flags=pygame.SRCALPHA)

        stripe_height = thickness1 + thickness2
        t1 = thickness1
        t2 = thickness2

        for y in range(0, diag, stripe_height):
            if t1 > 0:
                pygame.draw.rect(big_bg, color1, (0, y, diag, t1))
            if t2 > 0:
                pygame.draw.rect(big_bg, color2, (0, y + t1, diag, t2))

        big_bg = pygame.transform.rotate(big_bg, angle % 180)

        area_w = self.display.area.get_width()
        area_h = self.display.area.get_height()
        x = (area_w - big_bg.get_width()) // 2
        y = (area_h - big_bg.get_height()) // 2
        self.display.clear_area()
        self.display.area.blit(big_bg, (x, y))

    # Serial
    # ----------------

    def send(self, message: str) -> None:
        """Write a newline-terminated UTF-8 string to serial."""
        if self.ser is None:
            print(f"[no serial] {message}")
            return
        self.ser.write((message + "\n").encode("utf-8"))

    def sendErrorFeedBack(self, error):
        # check error to avoid repeating the same one all the time
        if self.ser is None:
            print(f"[no serial] Touchscreen - error - traceback: {error}")
            return
        if self.last_error == error:
            return
        self.send(f"Touchscreen - error - traceback: {error}")
        self.last_error = error

    def read_command(self) -> str | None:
        """Non-blocking: read one complete line from serial, or return None."""
        if self.ser is None:
            return None

        data_in = self.ser.readline()
        try:
            data_in = data_in.decode("utf-8")
        except Exception:
            self.send_error_feedback("Can't uf8-decode command")
            return None

        self.input_buffer += data_in

        if "\n" not in self.input_buffer:
            return None

        line, _, self.input_buffer = self.input_buffer.partition("\n")

        return line.strip() or None

    def execute_command(self, command: str | None):
        """Parse a single serial command and act on it."""
        if command is None:
            return

        c = command.strip().split(" ")

        if not c:
            return

        if "hello" in c[0]:
            # hello
            self.send("Touchscreen - driver v3.0")

        elif "ping" in c[0]:
            # ping
            self.send("pong")

        elif "clear" in c[0]:
            # clear
            self.display.clear()

        elif "calibration" in c[0]:
            # calibration <show|hide|toggle>
            if "show" in command:
                self.display.set_show_calibration(True)
            elif "hide" in command:
                self.display.set_show_calibration(False)
            else:
                self.display.toggle_calibration()

        elif "removeAllImages" in c[0]:
            # removeAllImages
            self.display.remove_all_images()

        elif "setXYImage" in c[0]:
            # setXYImage <name> <index> <x> <y> <r> <s> <coord_unit>
            name = c[1]
            idx = int(c[2])
            unit = c[7] if len(c) > 7 else "px"
            x = float(c[3])
            y = float(c[4])
            if len(c) > 5:
                r = float(c[5])
            else:
                r = 0.0
            if len(c) > 6:
                s = float(c[6])
            else:
                s = 1.0
            self.setXYImage(name, idx, x, y, r, s, unit)

        elif "removeXYImage" in c[0]:
            # removeXYImage <name>
            self.display.remove_image(c[1])

        elif "setXYStripes" in c[0]:
            # setXYStripes <name> <x> <y> <r> <s> <stripe_angle> <thickness1> <thickness2> <color1> <color2> <coord_unit>
            name = c[1]
            x = float(c[2])
            y = float(c[3])
            r = float(c[4]) if len(c) > 4 else 0.0
            s = float(c[5]) if len(c) > 5 else 1.0
            stripe_angle = float(c[6]) if len(c) > 6 else 0.0
            thickness1 = int(c[7]) if len(c) > 7 else 10
            thickness2 = int(c[8]) if len(c) > 8 else 10
            color1 = (
                tuple(map(int, c[9].split(",")))
                if len(c) > 9
                else (255, 255, 255)
            )
            color2 = (
                tuple(map(int, c[10].split(","))) if len(c) > 10 else (0, 0, 0)
            )
            coord_unit = c[11] if len(c) > 11 else "px"

            self.setXYStripes(
                name,
                x,
                y,
                r,
                s,
                stripe_angle,
                thickness1,
                thickness2,
                color1,
                color2,
                coord_unit,
            )

        elif "removeXYStripes" in c[0]:
            # removeXYStripes <name>
            self.display.remove_image(c[1])

        elif "removeImage" in c[0]:
            # removeImage <name>
            self.display.remove_image(c[1])

        elif "moveImage" in c[0]:
            # moveImage <name> <x> <y> <coord_unit>
            self.display.images[c[1]].cx = self.display.convert_to_px(
                float(c[2]), c[4] if len(c) > 4 else "px", "x"
            )
            self.display.images[c[1]].cy = self.display.convert_to_px(
                float(c[3]), c[4] if len(c) > 4 else "px", "y"
            )
            self.display.images[c[1]].unit = c[4] if len(c) > 4 else "px"

        elif "transparency" in c[0]:
            # transparency <value>
            self.transparency = int(c[1])

        elif "imageSize" in c[0]:
            # imageSize <value> <unit>
            coord_unit = c[2] if len(c) > 2 else "px"
            self.setImageSize(int(c[1]), coord_unit)

        elif "setBgColor" in c[0]:
            # setBgColor <r> <g> <b>
            r = int(c[1])
            g = int(c[2])
            b = int(c[3])
            self.setBgColor((r, g, b))

        elif "setBgStripes" in c[0]:
            # setBgStripes <thickness1> <thickness2> <angle> <r1> <g1> <b1> <r2> <g2> <b2>
            thickness1 = int(c[1])
            thickness2 = int(c[2])
            angle = float(c[3])
            color1 = (int(c[4]), int(c[5]), int(c[6]))
            color2 = (int(c[7]), int(c[8]), int(c[9]))
            self.setBgStripes(thickness1, thickness2, angle, color1, color2)

        elif "setImageOffset" in c[0]:
            # setImageOffset <dx> <dy> <coord_unit>
            coord_unit = c[3] if len(c) > 3 else "px"
            dx = self.display.convert_to_px(float(c[1]), coord_unit, "x")
            dy = self.display.convert_to_px(float(c[2]), coord_unit, "y")
            self.display.set_image_offset(dx, dy)

        elif "setTouchOffset" in c[0]:
            # setTouchOffset <dx> <dy> <coord_unit>
            coord_unit = c[3] if len(c) > 3 else "px"
            dx = self.display.convert_to_px(float(c[1]), coord_unit, "x")
            dy = self.display.convert_to_px(float(c[2]), coord_unit, "y")
            self.display.set_touch_offset(dx, dy)

        elif "mouseMode" in c[0]:
            # mouseMode
            self.display.set_mouse_mode()

        elif "ratMode" in c[0]:
            # ratMode
            self.display.set_rat_mode()

        elif "normalMode" in c[0]:
            # normalMode
            self.display.set_normal_mode()

        elif "setMode" in c[0]:
            # setMode <area_width> <area_height> <center_x> <center_y> <rotation_angle> <coord_unit>
            area_width = float(c[1])
            area_height = float(c[2])
            center_x = float(c[3])
            center_y = float(c[4])
            rotation_angle = float(c[5])
            coord_unit = c[6] if len(c) > 6 else "px"
            self.display.set_mode(
                (area_width, area_height),
                (center_x, center_y),
                rotation_angle,
                coord_unit,
            )

        elif "crash" in c[0]:
            raise Exception("Crash asked by user")

        return command

    def send_error_feedback(self, error: str) -> None:
        # check error to avoid repeating the same one all the time
        if error == self.last_error:
            return
        self.send(f"Touchscreen - error - traceback: {error}")
        self.last_error = error

    # Processing
    # ----------------

    def process_commands(self) -> None:
        """Handle pygame events for one frame."""
        for _ in range(10):
            cmd = self.read_command()
            self.execute_command(cmd)
            if cmd is None:
                break

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            # Key-oriented controls (Q to quit, C to toggle calibration)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q or event.key == pygame.K_ESCAPE:
                    self.running = False
                    print("Q or ESC key hit: exit")
                elif event.key == pygame.K_c:
                    self.display.toggle_calibration()
                    print("C key hit: toggle calibration")
                elif event.key == pygame.K_o:
                    self.display.clear()
                    print("O key hit: clear display")
                elif event.key == pygame.K_a:
                    self.removeAllImages()
                    print("A key hit: remove all images")
                elif event.key == pygame.K_i:
                    self.removeXYImage("random_image")
                    self.setXYImage(
                        "random_image",
                        random.choice(list(self._loaded_images.keys())),
                        random.random(),
                        random.random(),
                        random.uniform(0, 360),
                        random.uniform(0.5, 1.5),
                        "ratio",
                    )
                    print("I key hit: add random image at random position")
                elif event.key == pygame.K_s:
                    self.removeXYStripes("random_stripes")
                    self.setXYStripes(
                        "random_stripes",
                        random.random(),
                        random.random(),
                        random.uniform(0, 360),
                        random.uniform(0.5, 1.5),
                        random.uniform(0, 180),
                        random.randint(1, 50),
                        random.randint(1, 50),
                        (
                            random.randint(0, 255),
                            random.randint(0, 255),
                            random.randint(0, 255),
                        ),
                        (
                            random.randint(0, 255),
                            random.randint(0, 255),
                            random.randint(0, 255),
                        ),
                        "ratio",
                    )
                    print("S key hit: add random stripes at random position")
                elif event.key == pygame.K_b:
                    self.setBgColor(
                        (
                            random.randint(0, 255),
                            random.randint(0, 255),
                            random.randint(0, 255),
                        )
                    )
                    print("B key hit: set random background color")
                elif event.key == pygame.K_v:
                    self.setBgStripes(
                        random.randint(1, 500),
                        random.randint(1, 500),
                        random.uniform(0, 360),
                        (
                            random.randint(0, 255),
                            random.randint(0, 255),
                            random.randint(0, 255),
                        ),
                        (
                            random.randint(0, 255),
                            random.randint(0, 255),
                            random.randint(0, 255),
                        ),
                    )
                    print("V key hit: set random background stripes")
                elif event.key == pygame.K_RIGHT:
                    dx, dy = self.display.touches_offset
                    self.display.touches_offset = (dx + 1, dy)
                    print("RIGHT key hit: increase touch offset along x")
                elif event.key == pygame.K_LEFT:
                    dx, dy = self.display.touches_offset
                    self.display.touches_offset = (dx - 1, dy)
                    print("LEFT key hit: decrease touch offset along x")
                elif event.key == pygame.K_DOWN:
                    dx, dy = self.display.touches_offset
                    self.display.touches_offset = (dx, dy + 1)
                    print("DOWN key hit: increase touch offset along y")
                elif event.key == pygame.K_UP:
                    dx, dy = self.display.touches_offset
                    self.display.touches_offset = (dx, dy - 1)
                    print("UP key hit: decrease touch offset along y")
                elif event.key == pygame.K_KP_PLUS:
                    self.setImageSize(self.imageSize + 10)
                    print("KP_PLUS key hit: increase image size")
                elif event.key == pygame.K_KP_MINUS:
                    self.setImageSize(self.imageSize - 10)
                    print("KP_MINUS key hit: decrease image size")
                elif event.key == pygame.K_KP1:
                    self.setXYImage("KP0", 0, 0.25, 0.75, coord_unit="ratio")
                    print("KP0 key hit: place image (ID 1) accordingly")
                elif event.key == pygame.K_KP2:
                    self.setXYImage("KP2", 2, 0.5, 0.75, coord_unit="ratio")
                    print("KP2 key hit: place image (ID 2) accordingly")
                elif event.key == pygame.K_KP3:
                    self.setXYImage("KP3", 3, 0.75, 0.75, coord_unit="ratio")
                    print("KP3 key hit: place image (ID 3) accordingly")
                elif event.key == pygame.K_KP4:
                    self.setXYImage("KP4", 4, 0.25, 0.5, coord_unit="ratio")
                    print("KP4 key hit: place image (ID 4) accordingly")
                elif event.key == pygame.K_KP5:
                    self.setXYImage("KP5", 5, 0.5, 0.5, coord_unit="ratio")
                    print("KP5 key hit: place image (ID 5) accordingly")
                elif event.key == pygame.K_KP6:
                    self.setXYImage("KP6", 6, 0.75, 0.5, coord_unit="ratio")
                    print("KP6 key hit: place image (ID 6) accordingly")
                elif event.key == pygame.K_KP7:
                    self.setXYImage("KP7", 7, 0.25, 0.25, coord_unit="ratio")
                    print("KP7 key hit: place image (ID 7) accordingly")
                elif event.key == pygame.K_KP8:
                    self.setXYImage("KP8", 8, 0.5, 0.25, coord_unit="ratio")
                    print("KP8 key hit: place image (ID 8) accordingly")
                elif event.key == pygame.K_KP9:
                    self.setXYImage("KP9", 9, 0.75, 0.25, coord_unit="ratio")
                    print("KP9 key hit: place image (ID 9) accordingly")
                elif event.key == pygame.K_n:
                    self.display.set_normal_mode()
                    print("N key hit: set normal mode")
                elif event.key == pygame.K_m:
                    self.display.set_mouse_mode()
                    print("M key hit: set mouse mode")
                elif event.key == pygame.K_r:
                    self.display.set_rat_mode()
                    print("R key hit: set rat mode")

            # Mouse events (desktop testing)
            if event.type == pygame.MOUSEBUTTONDOWN:
                x, y = pygame.mouse.get_pos()
                (ax, ay), oob = self.display.screen_to_area_coords(x, y)
                if not oob:
                    self.display.add_touch("mouse", ax, ay)
                    print(f"mouse down: add touch ({ax},{ay})")
                    self.check_if_touch_on_image((ax, ay), (x, y))
            if event.type == pygame.MOUSEBUTTONUP:
                self.display.remove_touch("mouse")
                print("mouse up: remove touch")

            # Finger events (touchscreen)
            if event.type == pygame.FINGERDOWN:
                # event values are normalized to [0.0, 1.0]
                x = self.display.touch_to_screen_coords(event.x, "x")
                y = self.display.touch_to_screen_coords(event.y, "y")
                if x is None or y is None:
                    continue
                (ax, ay), oob = self.display.screen_to_area_coords(x, y)
                if not oob:
                    self.display.add_touch(event.finger_id, ax, ay)
                    print(f"finger down: add touch ({ax},{ay})")
                    self.check_if_touch_on_image((ax, ay), (x, y))
            if event.type == pygame.FINGERUP:
                self.display.remove_touch(event.finger_id)
                self.send(f"finger up: {event.finger_id}")

            self.display.render(fps=30)

    # Main loop
    # ----------------

    def step(self, fps: int = 30) -> bool:
        """Process one frame. Returns False when the app should quit."""
        self.read_command()
        self.process_commands()
        self.display.render(fps=fps)
        return self.running

    def run(self, fps: int = 30) -> None:
        """Blocking event loop.  Calls quit() when done."""
        while self.running:
            try:
                self.step(fps=fps)
            except Exception:
                print(traceback.format_exc())
                self.running = False
            sleep(0.001)

    def quit(self) -> None:
        """Quit the application."""
        self.running = False
        self.display.quit()
        if self.ser is not None:
            self.ser.close()
        pygame.quit()
        print("Quit TouchScreen")

    def get_keyboard_commands(self) -> list[str]:
        """Return a list of keyboard commands for testing purposes."""
        return [
            "Q / ESC: Quit",
            "C: Toggle calibration",
            "O: Clear display",
            "A: Remove all images",
            "I: Add random image at random position",
            "S: Add random stripes at random position",
            "B: Set random background color",
            "V: Set random background stripes",
            "KP_PLUS / KP_MINUS: Increase / decrease image size",
            "Arrow keys: Adjust touch offset (Left/Right/Up/Down)",
            "KP1..KP9: Place images in a 3x3 grid (IDs 1..9)",
            "Mouse click: Add simulated touch at click position",
            "Finger events: Touchscreen finger down / up",
            "N: Set normal mode",
            "M: Set mouse mode",
            "R: Set rat mode",
        ]


if __name__ == "__main__":
    TEST_MODE = False
    ts = TouchScreen(TEST_MODE)
    ts.load_all_images()
    if ts.ser is None:
        print("=== TEST MODE ===")
        for command in ts.get_keyboard_commands():
            print(command)
    ts.run()
    ts.quit()
