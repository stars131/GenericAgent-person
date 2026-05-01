"""Bots tab widget — render BotManager status as a clickable table."""
from __future__ import annotations

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # graceful: launcher.qt_launcher.main() refuses to run without PySide6
    Qt = QTimer = None
    QHBoxLayout = QHeaderView = QLabel = QPushButton = None
    QTableWidget = QTableWidgetItem = QVBoxLayout = None
    QWidget = object  # so the class statement below still parses

from launcher.bot_manager import BOT_SPECS, BotManager


class BotsTab(QWidget):
    REFRESH_MS = 3000

    def __init__(self, manager: BotManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._buttons: dict[str, dict[str, QPushButton]] = {}
        self._build_ui()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.REFRESH_MS)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        title = QLabel("Bot 管理 — 启动/停止聊天平台 bot 后台进程")
        title.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        layout.addWidget(title)

        info = QLabel(
            "配置编辑：直接修改 mykey.py（fs_app_id 等字段）。状态每 3 秒刷新。"
            "🟢 = 本 launcher 启的 / 🟡 = 外部进程 / ⚪ = 未运行"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; padding: 0 4px 6px 4px;")
        layout.addWidget(info)

        self.table = QTableWidget(len(BOT_SPECS), 4, self)
        self.table.setHorizontalHeaderLabels(["Bot", "配置", "状态", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        for row, key in enumerate(BOT_SPECS):
            spec = BOT_SPECS[key]
            self.table.setItem(row, 0, QTableWidgetItem(spec.display_name))

            ok_item = QTableWidgetItem("…")
            ok_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, ok_item)

            status_item = QTableWidgetItem("…")
            self.table.setItem(row, 2, status_item)

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)
            start_btn = QPushButton("启动")
            stop_btn = QPushButton("停止")
            log_btn = QPushButton("日志")
            for btn in (start_btn, stop_btn, log_btn):
                btn.setFixedWidth(56)
                actions_layout.addWidget(btn)
            start_btn.clicked.connect(lambda _=False, k=key: self._on_start(k))
            stop_btn.clicked.connect(lambda _=False, k=key: self._on_stop(k))
            log_btn.clicked.connect(lambda _=False, k=key: self._on_log(k))
            self._buttons[key] = {"start": start_btn, "stop": stop_btn, "log": log_btn}
            self.table.setCellWidget(row, 3, actions)

        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        refresh_btn = QPushButton("立即刷新")
        refresh_btn.clicked.connect(self.refresh)
        bottom.addWidget(refresh_btn)
        bottom.addStretch(1)
        self.summary = QLabel("…")
        self.summary.setStyleSheet("color: #444;")
        bottom.addWidget(self.summary)
        layout.addLayout(bottom)

    # ── refresh ──

    def refresh(self):
        statuses = self.manager.status_all()
        running = 0
        for row, key in enumerate(BOT_SPECS):
            st = statuses[key]

            if not st.configured:
                cfg_text, tip = "❌", "缺字段: " + ", ".join(st.missing_fields)
            elif not st.sdk_installed:
                cfg_text, tip = "⚠️", "缺 SDK: " + ", ".join(st.missing_modules)
            else:
                cfg_text, tip = "✅", "已配置"
            cfg_item = self.table.item(row, 1)
            cfg_item.setText(cfg_text)
            cfg_item.setToolTip(tip)
            cfg_item.setTextAlignment(Qt.AlignCenter)

            if st.running_self:
                state_text = "🟢 运行中（本 launcher）"
            elif st.running_external:
                state_text = "🟡 外部进程占端口"
            else:
                state_text = "⚪ 已停"
            self.table.item(row, 2).setText(state_text)

            btns = self._buttons[key]
            startable = st.configured and st.sdk_installed and not st.running
            btns["start"].setEnabled(startable)
            btns["stop"].setEnabled(st.running_self)
            btns["log"].setEnabled(True)
            if st.running:
                running += 1

        self.summary.setText(f"运行中 {running}/{len(BOT_SPECS)} 个 bot")

    # ── handlers ──

    def _on_start(self, key: str):
        ok, msg = self.manager.start(key)
        self.summary.setText(f"[{BOT_SPECS[key].display_name}] {msg}")
        self.refresh()

    def _on_stop(self, key: str):
        ok, msg = self.manager.stop(key)
        self.summary.setText(f"[{BOT_SPECS[key].display_name}] {msg}")
        self.refresh()

    def _on_log(self, key: str):
        if not self.manager.open_log(key):
            self.summary.setText(f"[{BOT_SPECS[key].display_name}] 日志暂无")
