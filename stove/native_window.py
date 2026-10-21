"""Native macOS window for Stove's local dashboard."""

from __future__ import annotations

from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSMakeRect, NSMakeSize, NSTimer, NSURL, NSURLRequest
from PyObjCTools import AppHelper
from WebKit import WKWebView, WKWebViewConfiguration
import objc


class StoveWindowDelegate(NSObject):
    @objc.python_method
    def configure(self, state, port: int, worker) -> None:
        self.state = state
        self.port = port
        self.worker = worker
        self.window = None
        self.webview = None

    @objc.python_method
    def build(self) -> None:
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                 NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        rect = NSMakeRect(0, 0, 1160, 800)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        self.window.setTitle_("Stove")
        self.window.setMinSize_(NSMakeSize(760, 560))
        self.window.center()
        self.window.setDelegate_(self)

        config = WKWebViewConfiguration.alloc().init()
        self.webview = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        self.window.setContentView_(self.webview)
        url = NSURL.URLWithString_(f"http://127.0.0.1:{self.port}/")
        self.webview.loadRequest_(NSURLRequest.requestWithURL_(url))
        self.showWindow_(None)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.25, self, "checkWorker:", None, True)

    def showWindow_(self, _sender) -> None:
        if self.window is not None:
            self.window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def focus(self) -> None:
        AppHelper.callAfter(self.showWindow_, None)

    def checkWorker_(self, _timer) -> None:
        if not self.worker.is_alive():
            NSApp.terminate_(None)

    def applicationShouldTerminateAfterLastWindowClosed_(self, _app) -> bool:
        return True


def run_native(state, port: int, worker) -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = StoveWindowDelegate.alloc().init()
    delegate.configure(state, port, worker)
    app.setDelegate_(delegate)
    state.show_window = delegate.focus
    delegate.build()
    app.run()
    state.show_window = None
