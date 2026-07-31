#!/usr/bin/env python3
"""Midnight Commander-inspired terminal interface for Cellar-pi."""

from __future__ import annotations

import curses
import json
import os
import subprocess
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PYTHON = "/opt/cellar-pi/venv/bin/python"
CORE_TOOL = "/opt/cellar-pi/cellar_core.py"
CONFIG_TOOL = "/opt/cellar-pi/cellar_config.py"
LOGGER_TOOL = "/opt/cellar-pi/cellar_logger.py"
REPORT_TOOL = "/opt/cellar-pi/daily_report.py"
SETUP_TOOL = "/opt/cellar-pi/setup.sh"
UPDATE_TOOL = "/usr/local/bin/cellar-update"
REQUIREMENTS = "/opt/cellar-pi/requirements.txt"
SUDO = "/usr/bin/sudo"


@dataclass
class MenuItem:
    label: str
    description: str
    action: Callable[[], None] | None = None
    submenu: Callable[[], list["MenuItem"]] | None = None


class CommandError(RuntimeError):
    pass


def run_command(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.strip()
    if check and result.returncode != 0:
        raise CommandError(output or f"Command failed with code {result.returncode}")
    return output


def sudo_python(tool: str, *arguments: str) -> list[str]:
    return [SUDO, PYTHON, tool, *arguments]


class CellarUI:
    def __init__(self, screen) -> None:
        self.screen = screen
        self.selected = 0
        self.stack: list[tuple[str, list[MenuItem], int]] = []
        self.title = "User Control"
        self.items = self.main_menu()
        self.footer_message = "Ready"
        self.summary: dict[str, object] = {}
        self.refresh_summary()

    def main_menu(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Sensor",
                "View readings or safely change the connected SHT sensor.",
                submenu=self.sensor_menu,
            ),
            MenuItem(
                "Notifications",
                "Configure Discord and scheduled environmental reports.",
                submenu=self.notifications_menu,
            ),
            MenuItem(
                "System Status",
                "One-page health summary for logging, sensing, and reports.",
                action=self.show_system_status,
            ),
            MenuItem(
                "Advanced / Troubleshooting",
                "Recovery, diagnostics, updates, and uncommon settings.",
                submenu=self.advanced_menu,
            ),
            MenuItem("Exit", "Close User Control.", action=self.exit_ui),
        ]

    def sensor_menu(self) -> list[MenuItem]:
        return [
            MenuItem("Current Reading", "Show the newest saved reading.", action=self.current_reading),
            MenuItem("Recent Readings", "Show the newest 30 CSV readings.", action=self.recent_readings),
            MenuItem(
                "Sensor Settings",
                "Change sensor type and address with validation and rollback.",
                action=self.sensor_settings,
            ),
            MenuItem("Back", "Return to User Control.", action=self.go_back),
        ]

    def notifications_menu(self) -> list[MenuItem]:
        return [
            MenuItem(
                "Discord Settings",
                "Add, replace, remove, or inspect the webhook.",
                submenu=self.discord_menu,
            ),
            MenuItem(
                "Schedule Settings",
                "Enable reports, choose timing, or send a test report.",
                submenu=self.schedule_menu,
            ),
            MenuItem(
                "Test Notification",
                "Send a simple Discord connection test without touching logging.",
                action=self.test_notification,
            ),
            MenuItem(
                "View Notification Status",
                "Show webhook, schedule, and report-timer status.",
                action=self.show_notification_status,
            ),
            MenuItem("Back", "Return to User Control.", action=self.go_back),
        ]

    def discord_menu(self) -> list[MenuItem]:
        return [
            MenuItem("Add / Replace Webhook", "Save a validated Discord webhook.", action=self.set_webhook),
            MenuItem("Remove Webhook", "Remove Discord and disable reports.", action=self.remove_webhook),
            MenuItem("View Discord Status", "Show whether Discord is configured.", action=self.show_discord_status),
            MenuItem("Back", "Return to Notifications.", action=self.go_back),
        ]

    def schedule_menu(self) -> list[MenuItem]:
        return [
            MenuItem("Enable Reports", "Enable the saved Discord report schedule.", action=lambda: self.set_reports(True)),
            MenuItem("Disable Reports", "Disable reports without erasing timing.", action=lambda: self.set_reports(False)),
            MenuItem("Change Report Time", "Set the first report time in 24-hour format.", action=self.set_report_time),
            MenuItem("Frequency / Graph Range", "Choose 12-hour or 24-hour reports.", action=self.set_report_frequency),
            MenuItem("View Schedule Status", "Show the saved schedule and timer state.", action=self.show_notification_status),
            MenuItem("Send Graph Now", "Build and send the graph now without changing the schedule.", action=self.test_report),
            MenuItem("Back", "Return to Notifications.", action=self.go_back),
        ]

    def advanced_menu(self) -> list[MenuItem]:
        return [
            MenuItem("Temperature Units", "Choose Fahrenheit or Celsius display.", action=self.temperature_units),
            MenuItem("View Configuration", "Show sanitized settings; secrets stay hidden.", action=self.view_config),
            MenuItem("View Logger Status", "Show detailed systemd logger status.", action=lambda: self.service_action("status")),
            MenuItem("View Logger Logs", "Show the newest logger journal entries.", action=self.view_logs),
            MenuItem("Scan Connected Sensors", "Read-only scan of the Raspberry Pi I2C bus.", action=self.sensor_scan),
            MenuItem("Restart Logger", "Restart only the core logger service.", action=lambda: self.confirm_service("restart")),
            MenuItem("Stop Logger", "Stop environmental logging.", action=lambda: self.confirm_service("stop")),
            MenuItem("Start Logger", "Start environmental logging.", action=lambda: self.confirm_service("start")),
            MenuItem("Repair Python Packages", "Reinstall only Cellar-pi dependencies.", action=self.repair_packages),
            MenuItem("Update Cellar-pi", "Confirmed, rollback-safe project update.", action=self.update_cellar),
            MenuItem("Run Full Setup Wizard", "Rare recovery path for complete reconfiguration.", action=self.full_setup),
            MenuItem("Back", "Return to User Control.", action=self.go_back),
        ]

    def refresh_summary(self) -> None:
        try:
            raw = run_command(sudo_python(CORE_TOOL, "summary"))
            self.summary = json.loads(raw)
        except (CommandError, json.JSONDecodeError):
            self.summary = {"logger": "unknown", "sensor_state": "unknown"}

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 22 or width < 76:
            message = "Terminal too small. Resize to at least 76 x 22."
            self.screen.addstr(0, 0, message[: max(1, width - 1)])
            self.screen.refresh()
            return

        header = " Cellar-pi User Control "
        self.screen.attron(curses.color_pair(1) | curses.A_BOLD)
        self.screen.addstr(0, 0, " " * (width - 1))
        self.screen.addstr(0, max(1, (width - len(header)) // 2), header)
        self.screen.attroff(curses.color_pair(1) | curses.A_BOLD)

        panel_top = 2
        panel_height = height - 4
        left_width = min(36, max(28, width // 3))
        self.draw_box(panel_top, 0, panel_height, left_width, self.title)
        self.draw_box(
            panel_top,
            left_width + 1,
            panel_height,
            width - left_width - 2,
            "Status / Details",
        )

        usable = panel_height - 2
        first = max(0, min(self.selected - usable + 1, len(self.items) - usable))
        for row, item in enumerate(self.items[first : first + usable]):
            actual = first + row
            y = panel_top + 1 + row
            label = f" {item.label}"
            if actual == self.selected:
                self.screen.attron(curses.color_pair(2) | curses.A_BOLD)
                self.screen.addnstr(y, 1, label.ljust(left_width - 2), left_width - 2)
                self.screen.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                self.screen.addnstr(y, 1, label, left_width - 2)

        self.draw_details(panel_top + 1, left_width + 3, width - left_width - 6)
        self.screen.attron(curses.color_pair(1))
        footer = " ↑↓ Move   →/Enter Open   ←/Esc Back   R Refresh   Q Quit "
        self.screen.addnstr(height - 2, 0, footer.ljust(width - 1), width - 1)
        self.screen.attroff(curses.color_pair(1))
        self.screen.addnstr(
            height - 1,
            0,
            f" {self.footer_message}".ljust(width - 1),
            width - 1,
        )
        self.screen.refresh()

    def draw_box(self, y: int, x: int, height: int, width: int, title: str) -> None:
        bottom = y + height - 1
        right = x + width - 1
        self.screen.addch(y, x, curses.ACS_ULCORNER)
        self.screen.hline(y, x + 1, curses.ACS_HLINE, width - 2)
        self.screen.addch(y, right, curses.ACS_URCORNER)
        self.screen.vline(y + 1, x, curses.ACS_VLINE, height - 2)
        self.screen.vline(y + 1, right, curses.ACS_VLINE, height - 2)
        self.screen.addch(bottom, x, curses.ACS_LLCORNER)
        self.screen.hline(bottom, x + 1, curses.ACS_HLINE, width - 2)
        self.screen.addch(bottom, right, curses.ACS_LRCORNER)
        title_text = f" {title} "
        self.screen.addnstr(y, x + 2, title_text, max(1, width - 4), curses.A_BOLD)

    def draw_details(self, y: int, x: int, width: int) -> None:
        item = self.items[self.selected]
        lines = textwrap.wrap(item.description, max(20, width))
        lines.extend(
            [
                "",
                f"Logger: {self.summary.get('logger', 'unknown')}",
                f"Sensor: {self.summary.get('sensor', 'unknown')}",
                f"Sensor health: {self.summary.get('sensor_state', 'unknown')}",
                f"Discord: {self.summary.get('discord', 'unknown')}",
                f"Reports: {'enabled' if self.summary.get('reports_enabled') else 'disabled'}",
                f"Report timer: {self.summary.get('report_timer', 'unknown')}",
            ]
        )
        latest = self.summary.get("latest")
        if isinstance(latest, dict) and latest.get("timestamp"):
            unit = self.summary.get("temperature_unit", "fahrenheit")
            temperature = latest.get("temperature_f", "")
            if temperature:
                value = float(temperature)
                suffix = "°F"
                if unit == "celsius":
                    value = (value - 32) * 5 / 9
                    suffix = "°C"
                lines.extend(
                    [
                        "",
                        "Latest reading",
                        f"  {value:.1f}{suffix}",
                        f"  {latest.get('humidity_percent', '?')}% RH",
                        f"  {latest.get('timestamp', '')}",
                    ]
                )
        for offset, line in enumerate(lines):
            self.screen.addnstr(y + offset, x, line, width)

    def run(self) -> None:
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                self.selected = (self.selected - 1) % len(self.items)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = (self.selected + 1) % len(self.items)
            elif key in (10, 13, curses.KEY_RIGHT):
                item = self.items[self.selected]
                if item.submenu is not None:
                    self.stack.append((self.title, self.items, self.selected))
                    self.title = item.label
                    self.items = item.submenu()
                    self.selected = 0
                elif item.action is not None:
                    item.action()
            elif key in (
                27,
                curses.KEY_LEFT,
                curses.KEY_BACKSPACE,
            ):
                self.go_back()
            elif key in (ord("r"), ord("R")):
                self.footer_message = "Refreshing status..."
                self.refresh_summary()
                self.footer_message = "Status refreshed"
            elif key in (ord("q"), ord("Q")):
                return

    def go_back(self) -> None:
        if not self.stack:
            return
        self.title, self.items, self.selected = self.stack.pop()

    def exit_ui(self) -> None:
        raise SystemExit(0)

    def modal(self, title: str, text: str) -> None:
        lines = text.splitlines() or [""]
        offset = 0
        while True:
            height, width = self.screen.getmaxyx()
            box_height = min(height - 4, max(10, len(lines) + 4))
            box_width = min(width - 4, max(58, min(100, max(len(line) for line in lines) + 4)))
            top = (height - box_height) // 2
            left = (width - box_width) // 2
            self.screen.erase()
            self.draw_box(top, left, box_height, box_width, title)
            visible = box_height - 3
            for row, line in enumerate(lines[offset : offset + visible]):
                self.screen.addnstr(top + 1 + row, left + 2, line, box_width - 4)
            self.screen.addnstr(
                top + box_height - 2,
                left + 2,
                "↑↓ Scroll   Enter/Esc Close",
                box_width - 4,
                curses.A_DIM,
            )
            self.screen.refresh()
            key = self.screen.getch()
            if key in (
                10,
                13,
                27,
                curses.KEY_LEFT,
                curses.KEY_RIGHT,
                ord("q"),
                ord("Q"),
            ):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                offset = min(max(0, len(lines) - visible), offset + 1)
            elif key in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            elif key == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - visible), offset + visible)
            elif key == curses.KEY_PPAGE:
                offset = max(0, offset - visible)

    def confirm(self, title: str, prompt: str) -> bool:
        while True:
            self.modal_like_prompt(title, prompt + "\n\nPress Y to continue or N to cancel.")
            key = self.screen.getch()
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N"), 27):
                return False

    def modal_like_prompt(self, title: str, prompt: str) -> None:
        height, width = self.screen.getmaxyx()
        lines = []
        for paragraph in prompt.splitlines():
            lines.extend(textwrap.wrap(paragraph, min(68, width - 10)) or [""])
        box_height = min(height - 4, max(9, len(lines) + 4))
        box_width = min(width - 4, 74)
        top = (height - box_height) // 2
        left = (width - box_width) // 2
        self.screen.erase()
        self.draw_box(top, left, box_height, box_width, title)
        for row, line in enumerate(lines[: box_height - 3]):
            self.screen.addnstr(top + 1 + row, left + 2, line, box_width - 4)
        self.screen.refresh()

    def choose(self, title: str, choices: list[tuple[str, str]], current: str = "") -> str | None:
        index = next((i for i, choice in enumerate(choices) if choice[0] == current), 0)
        while True:
            height, width = self.screen.getmaxyx()
            box_height = min(height - 4, len(choices) + 6)
            box_width = min(width - 4, 72)
            top = (height - box_height) // 2
            left = (width - box_width) // 2
            self.screen.erase()
            self.draw_box(top, left, box_height, box_width, title)
            for row, (value, description) in enumerate(choices):
                label = f" {value:<12} {description}"
                attribute = curses.color_pair(2) | curses.A_BOLD if row == index else 0
                self.screen.addnstr(top + 1 + row, left + 1, label.ljust(box_width - 2), box_width - 2, attribute)
            self.screen.addnstr(top + box_height - 2, left + 2, "↑↓ Move   Enter Select   Esc Cancel", box_width - 4)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                index = (index - 1) % len(choices)
            elif key in (curses.KEY_DOWN, ord("j")):
                index = (index + 1) % len(choices)
            elif key in (10, 13, curses.KEY_RIGHT):
                return choices[index][0]
            elif key in (27, curses.KEY_LEFT):
                return None

    def prompt(self, title: str, label: str, initial: str = "", secret: bool = False) -> str | None:
        value = list(initial)
        curses.curs_set(1)
        try:
            while True:
                height, width = self.screen.getmaxyx()
                box_width = min(width - 4, 78)
                box_height = 9
                top = (height - box_height) // 2
                left = (width - box_width) // 2
                self.screen.erase()
                self.draw_box(top, left, box_height, box_width, title)
                self.screen.addnstr(top + 2, left + 2, label, box_width - 4)
                shown = "*" * len(value) if secret else "".join(value)
                shown = shown[-(box_width - 6) :]
                self.screen.addnstr(top + 4, left + 2, shown.ljust(box_width - 4), box_width - 4, curses.A_REVERSE)
                self.screen.addnstr(top + 6, left + 2, "Enter Save   Esc Cancel", box_width - 4)
                self.screen.move(top + 4, left + 2 + min(len(shown), box_width - 5))
                self.screen.refresh()
                key = self.screen.getch()
                if key in (10, 13):
                    return "".join(value)
                if key == 27:
                    return None
                if key in (curses.KEY_BACKSPACE, 127, 8):
                    if value:
                        value.pop()
                elif 32 <= key <= 126:
                    value.append(chr(key))
        finally:
            curses.curs_set(0)

    def run_busy(self, title: str, detail: str, function: Callable[[], str]) -> str:
        result: dict[str, object] = {}

        def worker() -> None:
            try:
                result["output"] = function()
            except Exception as error:
                result["error"] = error

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        spinner = "|/-\\"
        started = time.monotonic()
        frame = 0
        while thread.is_alive():
            elapsed = int(time.monotonic() - started)
            self.modal_like_prompt(
                title,
                f"{spinner[frame % len(spinner)]} {detail}\n\nElapsed: {elapsed} seconds",
            )
            self.screen.timeout(200)
            self.screen.getch()
            self.screen.timeout(-1)
            frame += 1
        thread.join()
        if "error" in result:
            raise result["error"]  # type: ignore[misc]
        return str(result.get("output", ""))

    def core(self, *args: str) -> str:
        return run_command(sudo_python(CORE_TOOL, *args))

    def config(self, *args: str) -> str:
        return run_command(sudo_python(CONFIG_TOOL, *args))

    def current_reading(self) -> None:
        raw = self.run_busy("Current Reading", "Reading the latest saved data", lambda: self.core("current"))
        reading = json.loads(raw or "{}")
        if not reading:
            self.modal("Current Reading", "No readings have been recorded yet.")
            return
        unit = self.summary.get("temperature_unit", "fahrenheit")
        temperature = float(reading.get("temperature_f") or 0)
        suffix = "°F"
        if unit == "celsius":
            temperature = (temperature - 32) * 5 / 9
            suffix = "°C"
        self.modal(
            "Current Reading",
            "\n".join(
                [
                    f"Time: {reading.get('timestamp', 'unknown')}",
                    f"Temperature: {temperature:.1f}{suffix}",
                    f"Humidity: {reading.get('humidity_percent', '?')}%",
                    f"Sensor: {reading.get('temperature_humidity_sensor', 'unknown')}",
                ]
            ),
        )

    def recent_readings(self) -> None:
        output = self.run_busy("Recent Readings", "Loading recent readings", lambda: self.core("recent", "--limit", "30"))
        self.modal("Recent Readings", output)

    def sensor_settings(self) -> None:
        current = self.summary.get("sensor", "SHT31")
        sensor = self.choose(
            "Sensor Settings",
            [
                ("SHT31", "SHT31 and SHT31-D"),
                ("SHT35", "Higher-accuracy SHT3x"),
                ("SHT41", "Higher-accuracy SHT4x"),
                ("SHT45", "Highest-accuracy SHT4x"),
            ],
            str(current),
        )
        if sensor is None:
            return
        address = "0x44"
        if sensor in {"SHT31", "SHT35"}:
            address = self.choose(
                f"{sensor} Address",
                [("0x44", "Default"), ("0x45", "Alternate")],
                "0x44",
            ) or ""
            if not address:
                return
        if not self.confirm(
            "Confirm Sensor Change",
            f"Use {sensor} at {address}?\n\nDiscord and report settings will not change.",
        ):
            return
        backup = self.config("set-sensor", sensor, "--i2c", address)
        started = str(int(time.time()))
        try:
            self.run_busy(
                "Sensor Settings",
                f"Restarting and waiting for a valid {sensor} reading",
                lambda: self.restart_and_wait(sensor, started),
            )
        except Exception as error:
            if backup:
                run_command(sudo_python(CONFIG_TOOL, "restore", backup), check=False)
                run_command(sudo_python(CORE_TOOL, "service", "restart"), check=False)
            self.modal("Sensor Change Rolled Back", str(error))
            return
        self.refresh_summary()
        self.modal("Sensor Updated", f"{sensor} produced a valid reading.\n\nNotification settings were not changed.")

    def restart_and_wait(self, sensor: str, started: str) -> str:
        self.core("service", "restart")
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            result = subprocess.run(
                sudo_python(
                    LOGGER_TOOL,
                    "--check-health-since",
                    started,
                    "--expected-sensor",
                    sensor,
                ),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                return "Sensor is healthy."
            time.sleep(1)
        raise CommandError("The new sensor did not produce a valid reading within 35 seconds.")

    def set_webhook(self) -> None:
        webhook = self.prompt("Discord Webhook", "Paste the Discord webhook URL:", secret=True)
        if webhook is None:
            return
        try:
            self.config("set-discord", webhook)
        except CommandError as error:
            self.modal("Invalid Discord Configuration", str(error))
            return
        self.refresh_summary()
        self.modal("Discord Settings", "Webhook saved.\n\nThe logger was not restarted.")

    def remove_webhook(self) -> None:
        if not self.confirm("Remove Webhook", "Remove Discord and disable scheduled reports?"):
            return
        self.config("remove-discord")
        self.refresh_summary()
        self.modal("Discord Settings", "Webhook removed. Logging was not interrupted.")

    def show_discord_status(self) -> None:
        self.refresh_summary()
        self.modal("Discord Status", f"Discord webhook: {self.summary.get('discord', 'unknown')}")

    def set_reports(self, enabled: bool) -> None:
        try:
            self.config("set-report-enabled", "true" if enabled else "false")
        except CommandError as error:
            self.modal("Schedule Settings", str(error))
            return
        self.refresh_summary()
        self.modal("Schedule Settings", f"Scheduled reports {'enabled' if enabled else 'disabled'}.")

    def set_report_time(self) -> None:
        value = self.prompt("Report Time", "Enter a 24-hour time (HH:MM):", str(self.summary.get("report_time", "19:00")))
        if value is None:
            return
        try:
            self.config("set-report-time", value)
        except CommandError as error:
            self.modal("Invalid Report Time", str(error))
            return
        self.refresh_summary()
        self.modal("Schedule Settings", f"First report time changed to {value}.")

    def set_report_frequency(self) -> None:
        current = str(self.summary.get("report_frequency_hours", 24))
        value = self.choose(
            "Frequency / Graph Range",
            [("24", "Every 24 hours"), ("12", "Every 12 hours")],
            current,
        )
        if value is None:
            return
        self.config("set-report-frequency", value)
        self.refresh_summary()
        self.modal("Schedule Settings", f"Reports and graphs now use {value}-hour windows.")

    def test_notification(self) -> None:
        self.run_report_action("--test-notification", "Sending Discord test notification")

    def test_report(self) -> None:
        self.run_report_action("--test-report", "Building and sending report graph")

    def run_report_action(self, flag: str, detail: str) -> None:
        try:
            output = self.run_busy(
                "Notifications",
                detail,
                lambda: run_command(sudo_python(REPORT_TOOL, flag)),
            )
        except CommandError as error:
            self.modal("Notification Failed - Logger Unaffected", str(error))
            return
        self.modal("Notifications", output or "Discord accepted the notification.")

    def show_notification_status(self) -> None:
        self.refresh_summary()
        self.modal(
            "Notification Status",
            "\n".join(
                [
                    f"Discord: {self.summary.get('discord', 'unknown')}",
                    f"Reports enabled: {self.summary.get('reports_enabled', False)}",
                    f"Frequency / graph: {self.summary.get('report_frequency_hours', 24)} hours",
                    f"First report time: {self.summary.get('report_time', '19:00')}",
                    f"Report timer: {self.summary.get('report_timer', 'unknown')}",
                ]
            ),
        )

    def show_system_status(self) -> None:
        self.refresh_summary()
        latest = self.summary.get("latest") or {}
        lines = [
            f"Logger: {self.summary.get('logger', 'unknown')}",
            f"Sensor: {self.summary.get('sensor', 'unknown')}",
            f"Sensor health: {self.summary.get('sensor_state', 'unknown')}",
            f"Sensor detail: {self.summary.get('sensor_message', '')}",
            f"Last success: {self.summary.get('last_success') or 'Never'}",
            f"Consecutive failures: {self.summary.get('consecutive_failures', 0)}",
            f"Discord: {self.summary.get('discord', 'unknown')}",
            f"Reports enabled: {self.summary.get('reports_enabled', False)}",
            f"Report timer: {self.summary.get('report_timer', 'unknown')}",
        ]
        if isinstance(latest, dict) and latest.get("timestamp"):
            lines.extend(["", "Latest saved reading:", json.dumps(latest, indent=2)])
        self.modal("System Status", "\n".join(lines))

    def temperature_units(self) -> None:
        current = str(self.summary.get("temperature_unit", "fahrenheit"))
        value = self.choose(
            "Temperature Units",
            [("fahrenheit", "Fahrenheit (°F)"), ("celsius", "Celsius (°C)")],
            current,
        )
        if value is None:
            return
        self.config("set-temperature-unit", value)
        self.refresh_summary()
        self.modal("Temperature Units", f"Display unit changed to {value}.")

    def view_config(self) -> None:
        output = self.run_busy("Configuration", "Loading sanitized configuration", lambda: self.core("config"))
        self.modal("Configuration", output)

    def service_action(self, action: str) -> None:
        try:
            output = self.run_busy(
                "Logger Service",
                f"Running logger {action}",
                lambda: self.core("service", action),
            )
        except CommandError as error:
            self.modal("Logger Service Failed", str(error))
            return
        self.refresh_summary()
        self.modal("Logger Service", output)

    def confirm_service(self, action: str) -> None:
        if self.confirm("Logger Service", f"{action.title()} the logger now?"):
            self.service_action(action)

    def view_logs(self) -> None:
        output = self.run_busy("Logger Logs", "Loading logger journal", lambda: self.core("logs", "--lines", "100"))
        self.modal("Logger Logs", output)

    def sensor_scan(self) -> None:
        try:
            output = self.run_busy("Sensor Scan", "Scanning the I2C bus", lambda: self.core("sensor-scan"))
        except CommandError as error:
            output = str(error)
        self.modal("Sensor Scan", output)

    def repair_packages(self) -> None:
        if not self.confirm("Repair Python Packages", "Reinstall the exact Cellar-pi dependencies?"):
            return
        try:
            output = self.run_busy(
                "Repair Python Packages",
                "Reinstalling Cellar-pi dependencies",
                lambda: run_command(
                    [
                        SUDO,
                        PYTHON,
                        "-m",
                        "pip",
                        "install",
                        "--requirement",
                        REQUIREMENTS,
                    ]
                ),
            )
        except CommandError as error:
            self.modal("Package Repair Failed", str(error))
            return
        self.modal("Package Repair Complete", output or "Packages reinstalled.")

    def update_cellar(self) -> None:
        if not self.confirm(
            "Update Cellar-pi",
            "Download and install the newest version?\n\nConfiguration and readings are preserved. A failed update rolls back.",
        ):
            return
        try:
            output = self.run_busy(
                "Update Cellar-pi",
                "Downloading, validating, and installing",
                lambda: run_command([SUDO, UPDATE_TOOL]),
            )
        except CommandError as error:
            self.modal("Update Failed - Previous Version Restored", str(error))
            return
        self.modal("Update Complete", output + "\n\nClose and reopen /uc.")
        raise SystemExit(0)

    def full_setup(self) -> None:
        if not self.confirm(
            "Full Setup Wizard",
            "Run complete setup?\n\nUse Sensor Settings for normal sensor changes.",
        ):
            return
        curses.endwin()
        subprocess.run([SUDO, SETUP_TOOL], check=False)
        curses.reset_prog_mode()
        curses.curs_set(0)
        self.screen.refresh()
        self.refresh_summary()


def configure_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)


def main(screen) -> None:
    curses.curs_set(0)
    screen.keypad(True)
    configure_colors()
    CellarUI(screen).run()


if __name__ == "__main__":
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)

