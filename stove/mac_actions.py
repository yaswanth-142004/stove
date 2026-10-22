"""Small, local macOS action adapters for Stove."""

from __future__ import annotations

import ctypes
import platform
import re
import subprocess
import time

from AppKit import (NSApplicationActivateAllWindows, NSApplicationActivateIgnoringOtherApps,
                    NSRunningApplication, NSWorkspace)


def permission_name() -> str:
    version = platform.mac_ver()[0]
    major = int(version.split(".")[0]) if version else 0
    return "Device Control and Data Access" if major >= 27 else "Accessibility"


PERMISSION_NAME = permission_name()


class Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class MacActions:
    def __init__(self) -> None:
        self.cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.ds = ctypes.CDLL("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")

        self.cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        self.cg.CGRequestPostEventAccess.restype = ctypes.c_bool
        self.cg.CGEventCreateScrollWheelEvent2.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_int32, ctypes.c_int32, ctypes.c_int32]
        self.cg.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
        self.cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16,
                                                       ctypes.c_bool]
        self.cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        self.cg.CGEventCreate.argtypes = [ctypes.c_void_p]
        self.cg.CGEventCreate.restype = ctypes.c_void_p
        self.cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        self.cg.CGEventGetLocation.restype = Point
        self.cg.CGEventSetLocation.argtypes = [ctypes.c_void_p, Point]
        self.cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        self.cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        self.cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        self.cf.CFArrayGetCount.restype = ctypes.c_long
        self.cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        self.cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        self.cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.cf.CFNumberGetValue.restype = ctypes.c_bool
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cg.CGMainDisplayID.restype = ctypes.c_uint32
        self.ds.DisplayServicesGetBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        self.ds.DisplayServicesGetBrightness.restype = ctypes.c_int
        self.ds.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        self.ds.DisplayServicesSetBrightness.restype = ctypes.c_int

    def can_scroll(self) -> bool:
        return bool(self.cg.CGPreflightPostEventAccess())

    def request_scroll_permission(self) -> bool:
        return bool(self.cg.CGRequestPostEventAccess())

    @staticmethod
    def frontmost() -> tuple[str, int, str]:
        # NSWorkspace's cached frontmostApplication can stay stale in an asyncio
        # process without an AppKit event loop. Query Launch Services directly.
        front = subprocess.run(["/usr/bin/lsappinfo", "front"], capture_output=True,
                               text=True, check=True, timeout=2).stdout.strip()
        info = subprocess.run(["/usr/bin/lsappinfo", "info", "-only", "PID", front],
                              capture_output=True, text=True, check=True, timeout=2).stdout
        match = re.search(r"\bpid\s*=\s*(\d+)", info)
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(match.group(1))) if match else None
        if app is None:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None or app.processIdentifier() <= 0:
            raise RuntimeError("No active Mac app found")
        return str(app.localizedName() or "Current app"), int(app.processIdentifier()), str(app.bundleIdentifier() or "")

    @staticmethod
    def running_apps() -> list[dict]:
        apps = []
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            bundle_id = app.bundleIdentifier()
            if not bundle_id or app.processIdentifier() <= 0 or not app.localizedName():
                continue
            if app.activationPolicy() != 0:
                continue
            apps.append({"name": str(app.localizedName()), "bundle_id": str(bundle_id)})
        return sorted({a["bundle_id"]: a for a in apps}.values(), key=lambda a: a["name"].lower())

    @staticmethod
    def app_for_bundle(bundle_id: str):
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == bundle_id and app.processIdentifier() > 0:
                return app
        raise RuntimeError("Selected app is not running")

    def activate_app(self, bundle_id: str) -> str:
        app = self.app_for_bundle(bundle_id)
        if not app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps |
                                        NSApplicationActivateAllWindows):
            result = subprocess.run(["/usr/bin/open", "-b", bundle_id], capture_output=True,
                                    text=True, timeout=5)
            if result.returncode != 0:
                raise RuntimeError("Could not bring the selected app forward")
        return str(app.localizedName() or "App")

    def scroll(self, delta: int, bundle_id: str | None = None) -> str:
        if not self.can_scroll():
            raise PermissionError(f"Enable {PERMISSION_NAME} to scroll Mac apps")
        if bundle_id:
            name = self.activate_app(bundle_id)
            pid = int(self.app_for_bundle(bundle_id).processIdentifier())
            time.sleep(0.08)
            point = self._window_point(pid)
        else:
            name, _, _ = self.frontmost()
            point = self._pointer_point()
        self._post_wheel(int(delta), 0, point)
        return name

    def scroll_horizontal(self, delta: int) -> str:
        if not self.can_scroll():
            raise PermissionError(f"Enable {PERMISSION_NAME} to scroll Mac apps")
        name, _, _ = self.frontmost()
        self._post_wheel(0, int(delta), self._pointer_point())
        return name

    def _pointer_point(self) -> Point:
        pointer = self.cg.CGEventCreate(None)
        if not pointer:
            raise RuntimeError("Could not locate the mouse pointer")
        try:
            return self.cg.CGEventGetLocation(pointer)
        finally:
            self.cf.CFRelease(pointer)

    def _post_wheel(self, vertical: int, horizontal: int, point: Point) -> None:
        event = self.cg.CGEventCreateScrollWheelEvent2(None, 1, 2,
                                                       vertical, horizontal, 0)
        if not event:
            raise RuntimeError("Could not create a scroll event")
        try:
            # Post through the window server; PostToPid can report success while
            # scroll-wheel events have no visible effect in the target app.
            self.cg.CGEventSetLocation(event, point)
            self.cg.CGEventPost(0, event)
        finally:
            self.cf.CFRelease(event)

    def slideshow_arrow(self, direction: int) -> str:
        if not self.can_scroll():
            raise PermissionError(f"Enable {PERMISSION_NAME} to send slideshow keys")
        name, _, _ = self.frontmost()
        keycode = 124 if direction > 0 else 123  # Right / Left arrow
        for key_down in (True, False):
            event = self.cg.CGEventCreateKeyboardEvent(None, keycode, key_down)
            if not event:
                raise RuntimeError("Could not create an arrow key event")
            try:
                self.cg.CGEventPost(0, event)
            finally:
                self.cf.CFRelease(event)
        return name

    def _window_point(self, pid: int) -> Point:
        names = ("kCGWindowOwnerPID", "kCGWindowLayer", "kCGWindowBounds",
                 "X", "Y", "Width", "Height")
        keys = {name: self.cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
                for name in names}
        windows = self.cg.CGWindowListCopyWindowInfo(1 | 16, 0)
        try:
            if not windows:
                raise RuntimeError("Could not inspect app windows")

            def number(dictionary, name):
                value = self.cf.CFDictionaryGetValue(dictionary, keys[name])
                result = ctypes.c_double()
                return result.value if value and self.cf.CFNumberGetValue(value, 13, ctypes.byref(result)) else None

            best = None
            for index in range(self.cf.CFArrayGetCount(windows)):
                window = self.cf.CFArrayGetValueAtIndex(windows, index)
                if number(window, "kCGWindowOwnerPID") != pid or number(window, "kCGWindowLayer") != 0:
                    continue
                bounds = self.cf.CFDictionaryGetValue(window, keys["kCGWindowBounds"])
                if not bounds:
                    continue
                x, y, width, height = (number(bounds, field) for field in ("X", "Y", "Width", "Height"))
                if None in (x, y, width, height) or width < 200 or height < 150:
                    continue
                if best is None or width * height > best[0]:
                    best = (width * height, Point(x + width * 0.65, y + height * 0.5))
            if best is None:
                raise RuntimeError("No visible window to scroll for this app")
            return best[1]
        finally:
            if windows:
                self.cf.CFRelease(windows)
            for key in keys.values():
                if key:
                    self.cf.CFRelease(key)

    def brightness(self) -> float:
        value = ctypes.c_float()
        result = self.ds.DisplayServicesGetBrightness(self.cg.CGMainDisplayID(), ctypes.byref(value))
        if result != 0:
            raise RuntimeError("Built-in display brightness is unavailable")
        return max(0.0, min(1.0, float(value.value)))

    def change_brightness(self, direction: int, step: float = 0.06) -> float:
        current = self.brightness()
        target = max(0.05, min(1.0, current + direction * step))
        result = self.ds.DisplayServicesSetBrightness(self.cg.CGMainDisplayID(), ctypes.c_float(target))
        if result != 0:
            raise RuntimeError("Could not change display brightness")
        return self.brightness()

    @staticmethod
    def system_volume() -> int:
        result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                capture_output=True, text=True, check=True, timeout=4)
        return int(result.stdout.strip())

    def change_system_volume(self, direction: int, step: int = 5) -> int:
        current = self.system_volume()
        target = max(0, min(100, current + direction * step))
        subprocess.run(["osascript", "-e", f"set volume output volume {target}"],
                       capture_output=True, text=True, check=True, timeout=4)
        return self.system_volume()

    @staticmethod
    def sleep_mac() -> None:
        subprocess.Popen(["/usr/bin/pmset", "sleepnow"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
