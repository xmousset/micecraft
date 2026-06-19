"""
touchscreen_v2.py  -  Refactored touchscreen driver.

Two classes with clear responsibilities:

  ScreenManager
    Owns the pygame display.  All visual state lives here.
    * set_active_area(x_min, y_min, x_max, y_max)  — normalized [0..1] bounds
      within which image positions are expressed.
    * add_image(surface, x_norm, y_norm, name)      — center image at position.
    * add_touch(touch_id, x_px, y_px)               — register a finger.
    * remove_touch(touch_id)
    * hit_test(x_px, y_px) -> list[str]             — which images were hit.
    * render(fps)                                   — clear, blit, flip.

  TouchScreen
    Owns the serial link and image lifecycle.
    * load_image(filepath, name, x_norm, y_norm, size, transparency)
    * create_stripe_surface(w, h, color1, color2, stripe_w, horizontal)
    * add_stripe_image(name, x_norm, y_norm, …)
    * send(message)
    * step()  — one frame of serial + events + render.
    * run()   — blocking main loop.

Run modes (pass as first CLI argument):
  test_screen   - ScreenManager unit test (windowed, no serial)
  test_ts       - TouchScreen unit test  (windowed, no serial)
  test          - both tests in sequence  (default)
  run           - full production loop    (fullscreen + real serial)
"""

import math
import os
import traceback
from time import sleep

import pygame
import serial


class ScreenImage:
    """A pygame.Surface with a name and normalized position."""

    def __init__(
        self,
        surface: pygame.Surface,
        cx: int,
        cy: int,
        name: str,
    ):
        self.surface = surface
        """pygame.Surface of the image to display"""
        self.cx = cx
        """center of image in pixels"""
        self.cy = cy
        """center of image in pixels"""
        self.name = name
        """name of the image"""

    def __str__(self) -> str:
        return self.name


class ScreenTouches:
    """A pygame.Surface of a touch point."""

    def __init__(self, touch_id: int, x: int, y: int):
        self.touch_id = touch_id
        self.x = x
        self.y = y
        self.surface = pygame.Surface((20, 20), pygame.SRCALPHA)
        pygame.draw.circle(self.surface, (0, 255, 0), (10, 10), 10)


class ScreenManager:
    """Pygame display manager.

    All image positions are expressed as normalized coordinates (0.0 - 1.0)
    *within the active area*.  The active area itself is expressed as
    normalized coordinates relative to the full display.
    """

    def __init__(self):
        """Open a pygame window."""
        pygame.init()
        self._surface = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

        pygame.display.set_caption("LMT TouchScreen")
        pygame.mouse.set_visible(False)

        self.screen_full_size = pygame.display.get_window_size()

        self._w = self._surface.get_width()
        self._h = self._surface.get_height()

        # active area: (x_min, y_min, x_max, y_max) in normalized screen coords
        self._area: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

        # name -> TouchScreenImage
        self._images: dict[str, ScreenImage] = {}

        # touch_id -> (x_px, y_px)
        self._touches: dict[int, tuple[int, int]] = {}

        self._show_calibration: bool = False
        self._bg_color: tuple[int, int, int] = (0, 0, 0)
        self._clock = pygame.time.Clock()

    # Area
    # ----------------

    def set_active_area(
        self,
        x_min: float,
        y_min: float,
        x_max: float,
        y_max: float,
    ) -> None:
        """Define the region used for image placement.

        Coordinates are normalized relative to the full display (0.0 - 1.0).
        """
        self._area = (
            max(0.0, min(1.0, float(x_min))),
            max(0.0, min(1.0, float(y_min))),
            max(0.0, min(1.0, float(x_max))),
            max(0.0, min(1.0, float(y_max))),
        )

    def get_active_area(self) -> tuple[float, float, float, float]:
        return self._area

    # ================ CONVERSION ================

    def norm_to_px(self, x_norm: float, y_norm: float) -> tuple[int, int]:
        """Active-area normalized (0..1) → pixel coordinates."""
        ax0, ay0, ax1, ay1 = self._area
        abs_x = ax0 + float(x_norm) * (ax1 - ax0)
        abs_y = ay0 + float(y_norm) * (ay1 - ay0)
        return (int(round(abs_x * self._w)), int(round(abs_y * self._h)))

    def px_to_norm(self, x_px: int, y_px: int) -> tuple[float, float]:
        """Pixel coordinates → active-area normalized (0..1)."""
        ax0, ay0, ax1, ay1 = self._area
        w_area = ax1 - ax0
        h_area = ay1 - ay0
        if w_area == 0.0 or h_area == 0.0:
            return 0.0, 0.0
        abs_x = x_px / self._w
        abs_y = y_px / self._h
        return (abs_x - ax0) / w_area, (abs_y - ay0) / h_area

    @property
    def display_size(self) -> tuple[int, int]:
        """Full display size in pixels."""
        return self._w, self._h

    # Image
    # ----------------

    def add_image(
        self,
        surface: pygame.Surface,
        x_norm: float,
        y_norm: float,
        name: str,
    ) -> None:
        """Add or update a surface centered at the given active-area position.

        Args:
            surface: A pygame.Surface to display.
            x_norm:  Horizontal center [0..1] within the active area.
            y_norm:  Vertical center [0..1] within the active area.
            name:    Unique slot identifier.  Overwrites any existing entry.
        """
        cx, cy = self.norm_to_px(x_norm, y_norm)
        self._images[name] = ScreenImage(surface, cx, cy, name)

    def update_image_position(
        self,
        name: str,
        x_norm: float,
        y_norm: float,
    ) -> bool:
        """Move an already-added image to a new position.  Returns False if not found."""
        if name not in self._images:
            return False
        cx, cy = self.norm_to_px(x_norm, y_norm)
        self._images[name].cx = cx
        self._images[name].cy = cy
        return True

    def remove_image(self, name: str) -> None:
        self._images.pop(name, None)

    def clear_images(self) -> None:
        self._images.clear()

    # Touches
    # ----------------

    def add_touch(self, touch_id, x_px: int, y_px: int) -> None:
        """Register an active touch point (pixel coordinates)."""
        self._touches[touch_id] = (int(x_px), int(y_px))

    def remove_touch(self, touch_id) -> None:
        self._touches.pop(touch_id, None)

    def get_touches(self) -> dict:
        """Return a snapshot of active touch points: {touch_id: (x_px, y_px)}."""
        return dict(self._touches)

    def hit_test(self, x_px: int, y_px: int) -> list[str]:
        """Return names of every image whose bounding rect contains (x_px, y_px)."""
        hits = []
        for name, img in self._images.items():
            s: pygame.Surface = img.surface
            half_w = s.get_width() // 2
            half_h = s.get_height() // 2
            cx, cy = img.cx, img.cy
            if (cx - half_w <= x_px <= cx + half_w) and (
                cy - half_h <= y_px <= cy + half_h
            ):
                hits.append(name)
        return hits

    # Calibration
    # ----------------

    def set_show_calibration(self, enabled: bool) -> None:
        self._show_calibration = bool(enabled)

    def toggle_calibration(self) -> None:
        self._show_calibration = not self._show_calibration

    def _draw_calibration(self) -> None:
        ax0, ay0, ax1, ay1 = self._area
        area_rect = pygame.Rect(
            int(ax0 * self._w),
            int(ay0 * self._h),
            int((ax1 - ax0) * self._w),
            int((ay1 - ay0) * self._h),
        )
        pygame.draw.rect(self._surface, (255, 0, 0), area_rect, 3)

        # Image center markers
        for img in self._images.values():
            cx, cy = img.cx, img.cy
            pygame.draw.circle(self._surface, (255, 255, 0), (cx, cy), 6)

        # Active touch crosses
        for _tid, (xf, yf) in self._touches.items():
            arm = 30
            pygame.draw.line(
                self._surface,
                (0, 255, 0),
                (xf - arm, yf - arm),
                (xf + arm, yf + arm),
                4,
            )
            pygame.draw.line(
                self._surface,
                (0, 255, 0),
                (xf + arm, yf - arm),
                (xf - arm, yf + arm),
                4,
            )

    # Rendering
    # ----------------

    def render(self, fps: int = 30) -> None:
        """Clear the display, blit all images, optionally draw calibration, flip."""
        self._surface.fill(self._bg_color)

        for img in self._images.values():
            s: pygame.Surface = img.surface
            x = img.cx - s.get_width() // 2
            y = img.cy - s.get_height() // 2
            self._surface.blit(s, (x, y))

        if self._show_calibration:
            self._draw_calibration()

        pygame.display.flip()
        self._clock.tick(fps)

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
        screen_manager: ScreenManager,
        serial_port: str = "/dev/ttyS0",
        baud: int = 115200,
    ):
        self._screen = screen_manager
        self._input_buffer: str = ""
        self._last_error: str = ""
        self._running: bool = True

        # surfaces loaded or created by this instance
        self._surfaces: dict[str, pygame.Surface] = {}

        try:
            self._ser = serial.Serial(
                serial_port, baudrate=baud, write_timeout=2, timeout=0
            )
        except Exception:

            class _DummySer:
                name = "dummy"

                def write(self, *a, **k):
                    pass

                def readline(self):
                    return b""

            self._ser = _DummySer()
            print(
                f"[TouchScreen] serial unavailable on {serial_port!r}, using dummy."
            )

        print(f"[TouchScreen] serial: {getattr(self._ser, 'name', 'dummy')}")

    # Surface creation
    # ----------------

    def load_image(
        self,
        filepath: str,
        name: str,
        x_norm: float,
        y_norm: float,
        size: tuple[int, int] | None = None,
        transparency: int = 255,
    ) -> pygame.Surface:
        """Load an image file and place it on the screen.

        Args:
            filepath:     Path to the image file (JPEG, PNG, …).
            name:         Unique slot name used by ScreenManager and hit_test.
            x_norm:       Horizontal center position [0..1] in the active area.
            y_norm:       Vertical center position [0..1] in the active area.
            size:         Scale to (width, height) pixels.  None keeps original.
            transparency: Alpha multiplier 0 (invisible) - 255 (opaque).

        Returns:
            The created pygame.Surface.
        """
        surf = pygame.image.load(filepath).convert_alpha()
        if size is not None:
            surf = pygame.transform.scale(surf, size)
        if transparency < 255:
            surf.fill(
                (255, 255, 255, int(transparency)),
                special_flags=pygame.BLEND_RGBA_MULT,
            )
        self._surfaces[name] = surf
        self._screen.add_image(surf, x_norm, y_norm, name)
        return surf

    def create_stripe_surface(
        self,
        width: int,
        height: int,
        color1: tuple,
        color2: tuple,
        stripe_width: int = 10,
        horizontal: bool = False,
    ) -> pygame.Surface:
        """Create a Surface filled with alternating stripes.

        Args:
            width:        Surface width in pixels.
            height:       Surface height in pixels.
            color1:       First stripe color  (R, G, B) or (R, G, B, A).
            color2:       Second stripe color (R, G, B) or (R, G, B, A).
            stripe_width: Thickness of each stripe in pixels.
            horizontal:   True → horizontal stripes; False → vertical stripes.

        Returns:
            The created pygame.Surface (SRCALPHA).
        """
        surf = pygame.Surface((int(width), int(height)), pygame.SRCALPHA)
        stripe_width = max(1, int(stripe_width))

        if horizontal:
            pos, idx = 0, 0
            while pos < height:
                color = color1 if idx % 2 == 0 else color2
                h = min(stripe_width, height - pos)
                pygame.draw.rect(surf, color, pygame.Rect(0, pos, width, h))
                pos += stripe_width
                idx += 1
        else:
            pos, idx = 0, 0
            while pos < width:
                color = color1 if idx % 2 == 0 else color2
                w = min(stripe_width, width - pos)
                pygame.draw.rect(surf, color, pygame.Rect(pos, 0, w, height))
                pos += stripe_width
                idx += 1

        return surf

    def add_stripe_image(
        self,
        name: str,
        x_norm: float,
        y_norm: float,
        width: int,
        height: int,
        color1: tuple = (255, 255, 255),
        color2: tuple = (0, 0, 0),
        stripe_width: int = 10,
        horizontal: bool = False,
    ) -> pygame.Surface:
        """Create a striped surface and add it to the ScreenManager.

        Args:
            name:    Unique slot name.
            x_norm:  Horizontal center [0..1] within the active area.
            y_norm:  Vertical center [0..1] within the active area.
            width:   Surface width in pixels.
            height:  Surface height in pixels.
            color1:  First stripe color.
            color2:  Second stripe color.
            stripe_width: Stripe thickness in pixels.
            horizontal:   True → horizontal stripes.

        Returns:
            The created pygame.Surface.
        """
        surf = self.create_stripe_surface(
            width, height, color1, color2, stripe_width, horizontal
        )
        self._surfaces[name] = surf
        self._screen.add_image(surf, x_norm, y_norm, name)
        return surf

    # Serial
    # ----------------

    def send(self, message: str) -> None:
        """Write a newline-terminated UTF-8 string to serial."""
        try:
            self._ser.write((message + "\n").encode("utf-8"))
        except Exception:
            pass

    def _read_command(self) -> str | None:
        """Non-blocking: read one complete line from serial, or return None."""
        raw = self._ser.readline()
        try:
            self._input_buffer += raw.decode("utf-8")
        except Exception:
            self._send_error("UTF-8 decode failed")
            return None

        if "\n" not in self._input_buffer:
            return None

        line, _, self._input_buffer = self._input_buffer.partition("\n")
        return line.strip() or None

    def _dispatch(self, command: str) -> None:
        """Parse a single serial command and act on it."""
        parts = command.split()
        if not parts:
            return
        verb = parts[0]

        if verb == "hello":
            self.send("TouchScreen driver v3.0")

        elif verb == "ping":
            self.send("pong")

        elif verb == "clear":
            self._screen.clear_images()

        elif verb == "calibration":
            if "show" in command:
                self._screen.set_show_calibration(True)
            elif "hide" in command:
                self._screen.set_show_calibration(False)

        elif verb == "setArea" and len(parts) >= 5:
            # setArea <x_min> <y_min> <x_max> <y_max>
            self._screen.set_active_area(
                float(parts[1]),
                float(parts[2]),
                float(parts[3]),
                float(parts[4]),
            )

        elif verb == "addImage" and len(parts) >= 4:
            # addImage <name> <x_norm> <y_norm>
            name = parts[1]
            x_norm, y_norm = float(parts[2]), float(parts[3])
            if name in self._surfaces:
                self._screen.add_image(
                    self._surfaces[name], x_norm, y_norm, name
                )
            else:
                self._send_error(f"unknown surface '{name}'")

        elif verb == "moveImage" and len(parts) >= 4:
            # moveImage <name> <x_norm> <y_norm>
            self._screen.update_image_position(
                parts[1], float(parts[2]), float(parts[3])
            )

        elif verb == "removeImage" and len(parts) >= 2:
            self._screen.remove_image(parts[1])

        elif verb == "crash":
            raise RuntimeError("Crash requested by serial command.")

    def _send_error(self, msg: str) -> None:
        if msg != self._last_error:
            self.send(f"error: {msg}")
            self._last_error = msg

    def _process_serial(self) -> None:
        """Drain up to 10 serial commands per frame."""
        for _ in range(10):
            cmd = self._read_command()
            if cmd is None:
                break
            print(f"[serial] {cmd}")
            self._dispatch(cmd)

    # Processing
    # ----------------

    def _process_events(self) -> None:
        """Handle pygame events for one frame."""
        w, h = self._screen.display_size

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    self._running = False
                elif event.key == pygame.K_c:
                    self._screen.toggle_calibration()

            elif event.type == pygame.FINGERDOWN:
                x_px = int(event.x * w)
                y_px = int(event.y * h)
                self._screen.add_touch(event.finger_id, x_px, y_px)
                self._on_finger_down(event.finger_id, x_px, y_px)

            elif event.type == pygame.FINGERUP:
                self._screen.remove_touch(event.finger_id)
                self.send(f"fingerUp {event.finger_id}")

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Desktop testing: treat mouse click as a finger touch
                x_px, y_px = pygame.mouse.get_pos()
                self._screen.add_touch("mouse", x_px, y_px)
                self._on_finger_down("mouse", x_px, y_px)

            elif event.type == pygame.MOUSEBUTTONUP:
                self._screen.remove_touch("mouse")

    def _on_finger_down(self, finger_id, x_px: int, y_px: int) -> None:
        hits = self._screen.hit_test(x_px, y_px)
        if hits:
            for name in hits:
                self.send(f"touched {name} {finger_id} {x_px} {y_px}")
        else:
            self.send(f"missed {finger_id} {x_px} {y_px}")

    # Main loop
    # ----------------

    def step(self, fps: int = 30) -> bool:
        """Process one frame.  Returns False when the app should quit."""
        self._process_serial()
        self._process_events()
        self._screen.render(fps=fps)
        return self._running

    def run(self, fps: int = 30) -> None:
        """Blocking event loop.  Calls quit() when done."""
        while self._running:
            try:
                self.step(fps=fps)
            except Exception:
                print(traceback.format_exc())
                self._running = False
            sleep(0.001)
        self._screen.quit()


def _run_loop(sm: ScreenManager, max_frames: int = 90, fps: int = 30) -> None:
    """Spin a minimal pygame loop for `max_frames` frames then quit."""
    clock = pygame.time.Clock()
    for _ in range(max_frames):
        for event in pygame.event.get():
            if event.type in (pygame.QUIT,):
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q:
                return
        sm.render(fps=fps)
        clock.tick(fps)


def test_screen_manager() -> None:
    """ScreenManager: windowed display with stripes, solid rects, calibration."""
    print("[test] ScreenManager …")
    sm = ScreenManager()
    sm.set_active_area(0.1, 0.1, 0.9, 0.9)
    sm.set_show_calibration(True)

    # -- Solid colored squares at the four corners of the active area
    for label, xn, yn, rgb in [
        ("tl", 0.0, 0.0, (200, 50, 50)),
        ("tr", 1.0, 0.0, (50, 200, 50)),
        ("bl", 0.0, 1.0, (50, 50, 200)),
        ("br", 1.0, 1.0, (200, 200, 50)),
    ]:
        sq = pygame.Surface((80, 80))
        sq.fill(rgb)
        sm.add_image(sq, xn, yn, label)

    # -- Striped rectangle in the center
    stripe = pygame.Surface((200, 200), pygame.SRCALPHA)
    for i in range(0, 200, 20):
        c = (180, 60, 60) if (i // 20) % 2 == 0 else (60, 60, 180)
        pygame.draw.rect(stripe, c, pygame.Rect(i, 0, 20, 200))
    sm.add_image(stripe, 0.5, 0.5, "center_stripe")

    # -- Simulated touch
    sm.add_touch("t1", *sm.norm_to_px(0.5, 0.5))

    # -- Hit test
    cx, cy = sm.norm_to_px(0.5, 0.5)
    hits = sm.hit_test(cx, cy)
    assert (
        "center_stripe" in hits
    ), f"Expected hit on center_stripe, got {hits}"

    _run_loop(sm, max_frames=90)
    sm.quit()
    print("[test] ScreenManager OK")


def test_touchscreen_surfaces() -> None:
    """TouchScreen: image loading, stripe generation, hit test (no serial)."""
    print("[test] TouchScreen surfaces …")
    sm = ScreenManager()
    sm.set_active_area(0.05, 0.05, 0.95, 0.95)
    sm.set_show_calibration(True)

    ts = TouchScreen(sm, serial_port="INVALID_PORT_FOR_TEST")

    # -- Vertical stripes on the left
    ts.add_stripe_image(
        "v_stripes",
        0.25,
        0.5,
        150,
        150,
        color1=(255, 100, 0),
        color2=(0, 100, 255),
        stripe_width=15,
        horizontal=False,
    )

    # -- Horizontal stripes on the right
    ts.add_stripe_image(
        "h_stripes",
        0.75,
        0.5,
        150,
        150,
        color1=(0, 200, 100),
        color2=(200, 0, 100),
        stripe_width=15,
        horizontal=True,
    )

    # -- Load a real image if available
    here = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.join(here, "001_white.png")
    if os.path.isfile(sample):
        ts.load_image(
            sample, "sample_img", 0.5, 0.2, size=(120, 120), transparency=200
        )
        print(f"[test]   loaded {os.path.basename(sample)}")

    # -- Hit test on vertical stripes
    cx, cy = sm.norm_to_px(0.25, 0.5)
    sm.add_touch("t0", cx, cy)
    hits = sm.hit_test(cx, cy)
    assert "v_stripes" in hits, f"Expected hit on v_stripes, got {hits}"
    print(f"[test]   hit_test OK → {hits}")

    # -- Miss test (empty corner)
    miss_x, miss_y = sm.norm_to_px(0.5, 0.9)
    miss_hits = sm.hit_test(miss_x, miss_y)
    assert (
        "v_stripes" not in miss_hits and "h_stripes" not in miss_hits
    ), f"Unexpected hit: {miss_hits}"
    print("[test]   miss_test OK")

    _run_loop(sm, max_frames=90)
    sm.quit()
    print("[test] TouchScreen surfaces OK")


def test_coordinate_conversion() -> None:
    """ScreenManager: round-trip coordinate conversion."""
    print("[test] coordinate conversion …")
    pygame.init()
    sm = ScreenManager()
    sm.set_active_area(0.1, 0.2, 0.9, 0.8)

    for xn, yn in [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.3, 0.7)]:
        px, py = sm.norm_to_px(xn, yn)
        xn2, yn2 = sm.px_to_norm(px, py)
        assert (
            abs(xn2 - xn) < 0.01 and abs(yn2 - yn) < 0.01
        ), f"Round-trip failed: ({xn},{yn}) → px({px},{py}) → ({xn2:.3f},{yn2:.3f})"

    sm.quit()
    print("[test] coordinate conversion OK")


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "test"

    if mode == "test_screen":
        test_screen_manager()

    elif mode == "test_ts":
        test_touchscreen_surfaces()

    elif mode == "test_coords":
        test_coordinate_conversion()

    elif mode == "test":
        test_coordinate_conversion()
        test_screen_manager()
        test_touchscreen_surfaces()

    elif mode == "run":
        # Production: fullscreen + real serial port
        port = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyS0"
        sm = ScreenManager()
        ts = TouchScreen(sm, serial_port=port)
        ts.run()

    else:
        print(
            "Usage: python touchscreen_v2.py [test|test_screen|test_ts|test_coords|run [port]]"
        )
