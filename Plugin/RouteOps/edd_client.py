"""Minimal EDDiscovery ZMQ panel client for API version 1."""

from __future__ import annotations

import json
import time
from typing import Any

import zmq


class EDDClient:
    DEFAULT_TIMEOUT_MS = 10_000

    def __init__(self, port: int | str) -> None:
        self.context = zmq.Context.instance()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(f"tcp://127.0.0.1:{int(port)}")
        self.messages: list[dict[str, Any]] = []
        self.config: dict[str, Any] = {}
        self.commander: str | None = None
        self.history_length = 0
        self.edd_version = ""
        self.api_version = 0

    def _send(self, payload: dict[str, Any]) -> None:
        self.socket.send_string(json.dumps(payload, ensure_ascii=False))

    def send_start(self, version: str, timeout_ms: int = 30_000) -> bool:
        self._send({"requesttype": "start", "version": version, "apiversion": 1})
        response = self.poll_for("start", timeout_ms)
        if not response:
            return False
        self.edd_version = str(response.get("eddversion", ""))
        self.api_version = int(response.get("apiversion", 0))
        self.history_length = int(response.get("historylength", 0))
        self.commander = response.get("commander")
        raw_config = response.get("config", "")
        if raw_config:
            try:
                self.config = json.loads(raw_config)
            except (TypeError, json.JSONDecodeError):
                self.config = {}
        return self.api_version >= 1

    def send_exit(self, reason: str = "", close: bool = False) -> None:
        self._send(
            {
                "requesttype": "exit",
                "reason": reason,
                "config": json.dumps(self.config, ensure_ascii=False),
                "close": close,
            }
        )

    def fill_queue(self, timeout_ms: int = 25) -> None:
        if self.socket.poll(timeout_ms) > 0:
            raw = self.socket.recv_string()
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                self.messages.append(decoded)

    def get_next(self) -> dict[str, Any] | None:
        if not self.messages:
            return None
        message = self.messages.pop(0)
        response_type = message.get("responsetype")
        if response_type == "historyload":
            self.commander = message.get("commander")
            self.history_length = int(message.get("historylength", 0))
        elif response_type == "historypush":
            self.history_length = int(message.get("firstrow", -1)) + 1
        return message

    def poll_for(self, response_type: str, timeout_ms: int) -> dict[str, Any] | None:
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            for index, message in enumerate(self.messages):
                if message.get("responsetype") == response_type:
                    return self.messages.pop(index)
            self.fill_queue(25)
        return None

    def poll_for_field(
        self,
        response_type: str,
        field: str,
        value: Any,
        timeout_ms: int,
    ) -> dict[str, Any] | None:
        deadline = time.perf_counter() + timeout_ms / 1000.0
        while time.perf_counter() < deadline:
            for index, message in enumerate(self.messages):
                if message.get("responsetype") == response_type and message.get(field) == value:
                    return self.messages.pop(index)
            self.fill_queue(25)
        return None

    def ui_set(self, control: str, value: Any) -> None:
        self._send({"requesttype": "uiset", "control": control, "value": value})

    def ui_set_escape(self, control: str, value: str) -> None:
        self._send({"requesttype": "uisetescape", "control": control, "value": value})

    def ui_clear(self, control: str) -> None:
        self._send({"requesttype": "uiclear", "control": control})

    def ui_add_set_rows(self, control: str, changes: list[dict[str, Any]]) -> None:
        self._send(
            {
                "requesttype": "uiaddsetrows",
                "control": control,
                "changelist": changes,
            }
        )

    def ui_suspend(self, control: str) -> None:
        self._send({"requesttype": "uisuspend", "control": control})

    def ui_resume(self, control: str) -> None:
        self._send({"requesttype": "uiresume", "control": control})

    def ui_enable(self, control: str, state: bool) -> None:
        self._send({"requesttype": "uienable", "control": control, "state": state})


    def ui_set_dgv_setting(
        self,
        control: str,
        column_reorder: bool = True,
        per_column_word_wrap: bool = False,
        allow_header_visibility: bool = True,
        single_row_select: bool = True,
    ) -> None:
        self._send(
            {
                "requesttype": "uisetdgvsetting",
                "control": control,
                "columnreorder": column_reorder,
                "percolumnwordwrap": per_column_word_wrap,
                "allowheadervisibility": allow_header_visibility,
                "singlerowselect": single_row_select,
            }
        )

    def ui_set_word_wrap(self, control: str, word_wrap: bool) -> None:
        self._send(
            {
                "requesttype": "uisetwordwrap",
                "control": control,
                "wordwrap": word_wrap,
            }
        )

    def ui_visible(self, control: str, state: bool) -> None:
        self._send({"requesttype": "uivisible", "control": control, "state": state})

    def message_box(
        self,
        message: str,
        caption: str = "RouteOps",
        buttons: str = "OK",
        icon: str = "Information",
        timeout_ms: int = 120_000,
    ) -> dict[str, Any] | None:
        self._send(
            {
                "requesttype": "uimessagebox",
                "message": message,
                "caption": caption,
                "buttons": buttons,
                "icon": icon,
            }
        )
        return self.poll_for_field("uimessagebox", "message", message, timeout_ms)

    def run_action(self, name: str, variables: dict[str, Any]) -> None:
        self._send(
            {
                "requesttype": "runactionprogram",
                "name": name,
                "variables": variables,
            }
        )

    def open_file_dialog(
        self,
        folder: str,
        file_filter: str,
        default_extension: str = "*.json",
        timeout_ms: int = 120_000,
    ) -> dict[str, Any] | None:
        self.run_action(
            "OpenFileDialog",
            {
                "Folder": folder,
                "Filter": file_filter,
                "DefaultExtension": default_extension,
                "Check": True,
            },
        )
        return self.poll_for_field("runactionprogram", "name", "OpenFileDialog", timeout_ms)

    def close(self) -> None:
        self.socket.close(linger=0)
