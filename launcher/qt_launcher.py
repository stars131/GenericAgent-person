"""Qt launcher MVP for GenericAgent sessions and API cards."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from launcher.api_config import (
    apply_active_profile,
    delete_profile,
    load_api_configs,
    load_profiles,
    rename_profile,
    save_api_configs,
    set_active_profile,
    upsert_profile,
)
from launcher.launch_config import load_options, project_options, save_options
from launcher.project_manager import ProjectManager

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSplitter,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    Qt = QTimer = None
    QApplication = None
    QCheckBox = QComboBox = QDialog = QDialogButtonBox = QFormLayout = QHBoxLayout = QInputDialog = None
    QLabel = QLineEdit = QListWidget = QListWidgetItem = QMessageBox = None
    QPushButton = QSplitter = QTextEdit = QVBoxLayout = QWidget = None
    QMainWindow = object


class QtLauncher(QMainWindow):
    def __init__(self, base_dir=BASE_DIR):
        super().__init__()
        self.base_dir = base_dir
        self.pm = ProjectManager(base_dir)
        self.projects = []
        self.current_project_id = None
        self.launch_options = load_options(base_dir)
        self.api_configs = load_api_configs(base_dir)
        self.current_api_index = None
        self.scheduler_proc = None
        self.setWindowTitle("GenericAgent Qt Launcher")
        self.resize(1180, 760)
        self._build_ui()
        self.refresh_projects()
        self.refresh_api_list()
        self.start_scheduler_if_enabled()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_projects)
        self.timer.start(3000)

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sessions_panel())
        splitter.addWidget(self._project_panel())
        splitter.addWidget(self._api_panel())
        splitter.setSizes([320, 380, 480])
        self.setCentralWidget(splitter)

    def _sessions_panel(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel("会话"))
        self.project_list = QListWidget()
        self.project_list.currentItemChanged.connect(self.on_project_selected)
        layout.addWidget(self.project_list, 1)
        row1 = QHBoxLayout()
        for text, fn in (("新建", self.create_project), ("启动", self.start_project), ("停止", self.stop_project), ("打开", self.open_project)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            row1.addWidget(btn)
        layout.addLayout(row1)
        row2 = QHBoxLayout()
        for text, fn in (("激活", self.activate_project), ("重命名", self.rename_project), ("置顶", self.toggle_pin), ("删除", self.delete_project)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            row2.addWidget(btn)
        layout.addLayout(row2)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_projects)
        layout.addWidget(refresh)
        return root

    def _project_panel(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel("项目入口"))
        self.project_title = QLabel("未选择")
        self.project_title.setWordWrap(True)
        layout.addWidget(self.project_title)
        self.project_url = QLineEdit()
        self.project_url.setReadOnly(True)
        layout.addWidget(self.project_url)
        self.project_status = QTextEdit()
        self.project_status.setReadOnly(True)
        layout.addWidget(self.project_status, 1)
        row = QHBoxLayout()
        open_btn = QPushButton("打开 Streamlit")
        open_btn.clicked.connect(self.open_project)
        log_btn = QPushButton("刷新日志")
        log_btn.clicked.connect(self.show_project_log)
        row.addWidget(open_btn)
        row.addWidget(log_btn)
        layout.addLayout(row)
        layout.addWidget(QLabel("启动选项"))
        opts = QFormLayout()
        self.launch_llm_no = QLineEdit()
        self.launch_permission = QComboBox()
        self.launch_permission.addItems(["auto", "ask", "read-only", "dangerous"])
        self.launch_project_root = QLineEdit()
        self.launch_context = QCheckBox("use_project_context")
        self.launch_autonomous = QCheckBox("autonomous_enabled")
        self.launch_scheduler = QCheckBox("L4 scheduler")
        opts.addRow("llm_no", self.launch_llm_no)
        opts.addRow("permission", self.launch_permission)
        opts.addRow("project_root", self.launch_project_root)
        opts.addRow("context", self.launch_context)
        opts.addRow("autonomous", self.launch_autonomous)
        opts.addRow("L4", self.launch_scheduler)
        layout.addLayout(opts)
        save_opts = QPushButton("保存启动选项")
        save_opts.clicked.connect(self.save_launch_options)
        layout.addWidget(save_opts)
        self.load_launch_options_form()
        return root

    def _api_panel(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel("API 配置"))

        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Profile"))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        prof_row.addWidget(self.profile_combo, 1)
        for text, fn in (("新建", self.new_profile), ("改名", self.rename_profile_ui),
                         ("删除", self.delete_profile_ui), ("成员", self.edit_profile_members)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            prof_row.addWidget(btn)
        layout.addLayout(prof_row)

        self.api_list = QListWidget()
        self.api_list.currentRowChanged.connect(self.on_api_selected)
        layout.addWidget(self.api_list, 1)
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItems(["native_oai", "native_claude", "mixin"])
        self.name = QLineEdit()
        self.apikey = QLineEdit()
        self.apikey.setEchoMode(QLineEdit.Password)
        self.apibase = QLineEdit()
        self.model = QLineEdit()
        self.api_mode = QLineEdit()
        self.stream = QCheckBox("stream")
        self.max_tokens = QLineEdit()
        self.timeout = QLineEdit()
        self.llm_nos = QLineEdit()
        form.addRow("类型", self.kind)
        form.addRow("名称", self.name)
        form.addRow("API Key", self.apikey)
        form.addRow("API Base", self.apibase)
        form.addRow("Model", self.model)
        form.addRow("api_mode", self.api_mode)
        form.addRow("stream", self.stream)
        form.addRow("max_tokens", self.max_tokens)
        form.addRow("timeout", self.timeout)
        form.addRow("mixin llm_nos", self.llm_nos)
        layout.addLayout(form)
        row = QHBoxLayout()
        for text, fn in (("新增", self.new_api), ("保存", self.save_api), ("删除", self.delete_api), ("刷新模型", self.refresh_llms)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            row.addWidget(btn)
        layout.addLayout(row)
        self.llm_status = QTextEdit()
        self.llm_status.setReadOnly(True)
        layout.addWidget(self.llm_status, 1)
        return root

    def selected_project(self):
        if not self.current_project_id:
            return None
        return self.pm.get(self.current_project_id)

    def refresh_projects(self):
        selected = self.current_project_id
        data = self.pm.list()
        self.projects = data["projects"]
        self.project_list.blockSignals(True)
        self.project_list.clear()
        for project in self.projects:
            marker = "★" if project.get("pinned") else " "
            status = "运行" if project.get("running") else "停止"
            item = QListWidgetItem(f"{marker} {project['name']}  [{status}] :{project.get('port')}")
            item.setData(Qt.UserRole, project["id"])
            self.project_list.addItem(item)
            if project["id"] == selected:
                self.project_list.setCurrentItem(item)
        self.project_list.blockSignals(False)
        if selected and any(p["id"] == selected for p in self.projects):
            self.current_project_id = selected
        elif self.projects:
            self.current_project_id = self.projects[0]["id"]
            self.project_list.setCurrentRow(0)
        self.update_project_details()

    def on_project_selected(self, current, _previous):
        self.current_project_id = current.data(Qt.UserRole) if current else None
        self.update_project_details()

    def update_project_details(self):
        project = self.selected_project()
        if not project:
            self.project_title.setText("未选择")
            self.project_url.clear()
            self.project_status.clear()
            return
        url = f"http://127.0.0.1:{project['port']}/"
        self.project_title.setText(f"{project['name']}\nID: {project['id']}")
        self.project_url.setText(url if project.get("running") else "未运行")
        lines = [
            f"状态: {'运行中' if project.get('running') else '已停止'}",
            f"端口: {project.get('port')}",
            f"PID: {project.get('pid') or '-'}",
            f"置顶: {'是' if project.get('pinned') else '否'}",
            f"最近活跃: {project.get('last_active')}",
            f"日志: {project.get('log_path') or '-'}",
        ]
        if project.get("last_error"):
            lines.append(f"错误: {project['last_error']}")
        self.project_status.setPlainText("\n".join(lines))

    def create_project(self):
        name, ok = QInputDialog.getText(self, "新建会话", "名称:")
        if ok:
            self.pm.create(name, auto_start=False, options=project_options(self.launch_options))
            self.refresh_projects()

    def load_launch_options_form(self):
        self.launch_llm_no.setText(str(self.launch_options.get("llm_no", 0)))
        self.launch_permission.setCurrentText(str(self.launch_options.get("permission_mode") or "auto"))
        self.launch_project_root.setText(str(self.launch_options.get("project_root") or ""))
        self.launch_context.setChecked(bool(self.launch_options.get("use_project_context", True)))
        self.launch_autonomous.setChecked(bool(self.launch_options.get("autonomous_enabled", False)))
        self.launch_scheduler.setChecked(bool(self.launch_options.get("scheduler", True)))

    def save_launch_options(self):
        opts = dict(self.launch_options)
        opts.update({
            "llm_no": self.launch_llm_no.text().strip(),
            "permission_mode": self.launch_permission.currentText(),
            "project_root": self.launch_project_root.text().strip(),
            "use_project_context": self.launch_context.isChecked(),
            "autonomous_enabled": self.launch_autonomous.isChecked(),
            "scheduler": self.launch_scheduler.isChecked(),
        })
        self.launch_options = save_options(self.base_dir, opts)
        project = self.selected_project()
        if project and not project.get("running"):
            self.pm.update_options(project["id"], project_options(self.launch_options))
            self.refresh_projects()
        self.start_scheduler_if_enabled()
        QMessageBox.information(self, "已保存", "启动选项已保存；已运行会话需重启后生效")

    def start_scheduler_if_enabled(self):
        if not self.launch_options.get("scheduler", True):
            if self.scheduler_proc and self.scheduler_proc.poll() is None:
                self.scheduler_proc.kill()
            self.scheduler_proc = None
            return
        if self.scheduler_proc and self.scheduler_proc.poll() is None:
            return
        self.scheduler_proc = subprocess.Popen(
            [
                sys.executable,
                os.path.join(self.base_dir, "agentmain.py"),
                "--reflect",
                os.path.join(self.base_dir, "reflect", "scheduler.py"),
                "--llm_no",
                str(self.launch_options.get("llm_no", 0)),
            ],
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def start_project(self):
        project = self.selected_project()
        if not project:
            return
        try:
            self.pm.start(project["id"])
        except Exception as exc:
            QMessageBox.warning(self, "启动失败", str(exc))
        self.refresh_projects()

    def stop_project(self):
        project = self.selected_project()
        if project:
            self.pm.stop(project["id"])
            self.refresh_projects()

    def open_project(self):
        project = self.selected_project()
        if project and project.get("running"):
            self.pm.touch(project["id"])
            webbrowser.open(f"http://127.0.0.1:{project['port']}/")
            self.refresh_projects()

    def activate_project(self):
        project = self.selected_project()
        if project:
            self.pm.set_active(project["id"])
            self.refresh_projects()

    def rename_project(self):
        project = self.selected_project()
        if not project:
            return
        name, ok = QInputDialog.getText(self, "重命名", "名称:", text=project["name"])
        if ok:
            self.pm.rename(project["id"], name)
            self.refresh_projects()

    def toggle_pin(self):
        project = self.selected_project()
        if project:
            self.pm.pin(project["id"], not bool(project.get("pinned")))
            self.refresh_projects()

    def delete_project(self):
        project = self.selected_project()
        if not project:
            return
        if QMessageBox.question(self, "删除会话", f"删除 {project['name']}？") == QMessageBox.Yes:
            self.pm.delete(project["id"])
            self.current_project_id = None
            self.refresh_projects()

    def show_project_log(self):
        project = self.selected_project()
        if not project:
            return
        path = project.get("log_path")
        if not path or not os.path.isfile(path):
            self.project_status.append("\n暂无日志")
            return
        text = Path(path).read_text(encoding="utf-8", errors="replace")[-4000:]
        self.project_status.setPlainText(text)

    def refresh_api_list(self):
        self.api_configs = load_api_configs(self.base_dir)
        profiles = load_profiles(self.base_dir)
        active = profiles.get("active")
        members = set(profiles.get("profiles", {}).get(active or "", []))
        self.api_list.blockSignals(True)
        self.api_list.clear()
        for config in self.api_configs:
            tag = "★ " if active and config.get("name") in members else "   "
            self.api_list.addItem(f"{tag}{config.get('kind')} · {config.get('name')} · {config.get('model', '')}")
        self.api_list.blockSignals(False)
        if self.api_configs:
            self.api_list.setCurrentRow(0)
        else:
            self.current_api_index = None
            self.new_api()
        self.refresh_profile_list()

    def refresh_profile_list(self):
        if not hasattr(self, "profile_combo"):
            return
        state = load_profiles(self.base_dir)
        names = sorted(state.get("profiles", {}).keys())
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(无 profile, 全部启用)", userData=None)
        for name in names:
            self.profile_combo.addItem(name, userData=name)
        active = state.get("active")
        if active and active in names:
            self.profile_combo.setCurrentIndex(names.index(active) + 1)
        else:
            self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)

    def on_profile_changed(self, _index):
        if not hasattr(self, "profile_combo"):
            return
        name = self.profile_combo.currentData()
        try:
            set_active_profile(self.base_dir, name)
        except ValueError as exc:
            QMessageBox.warning(self, "切换失败", str(exc))
            return
        # refresh tags but do not recurse into profile dropdown rebuild
        self.api_configs = load_api_configs(self.base_dir)
        self.api_list.blockSignals(True)
        self.api_list.clear()
        members = set(load_profiles(self.base_dir).get("profiles", {}).get(name or "", []))
        for config in self.api_configs:
            tag = "★ " if name and config.get("name") in members else "   "
            self.api_list.addItem(f"{tag}{config.get('kind')} · {config.get('name')} · {config.get('model', '')}")
        self.api_list.blockSignals(False)

    def new_profile(self):
        name, ok = QInputDialog.getText(self, "新建 profile", "名称:")
        name = (name or "").strip()
        if not ok or not name:
            return
        state = load_profiles(self.base_dir)
        if name in state.get("profiles", {}):
            QMessageBox.warning(self, "新建失败", f"profile 已存在: {name}")
            return
        try:
            upsert_profile(self.base_dir, name, [])
            set_active_profile(self.base_dir, name)
        except ValueError as exc:
            QMessageBox.warning(self, "新建失败", str(exc))
            return
        self.refresh_api_list()
        self.edit_profile_members()

    def rename_profile_ui(self):
        active = self.profile_combo.currentData() if hasattr(self, "profile_combo") else None
        if not active:
            QMessageBox.information(self, "改名", "请先选中一个 profile")
            return
        new_name, ok = QInputDialog.getText(self, "改名 profile", "新名称:", text=active)
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == active:
            return
        try:
            rename_profile(self.base_dir, active, new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "改名失败", str(exc))
            return
        self.refresh_api_list()

    def delete_profile_ui(self):
        active = self.profile_combo.currentData() if hasattr(self, "profile_combo") else None
        if not active:
            QMessageBox.information(self, "删除", "请先选中一个 profile")
            return
        if QMessageBox.question(self, "删除 profile", f"确定删除 {active}？\n（仅删除分组定义，不影响其下 configs）") != QMessageBox.Yes:
            return
        delete_profile(self.base_dir, active)
        self.refresh_api_list()

    def edit_profile_members(self):
        active = self.profile_combo.currentData() if hasattr(self, "profile_combo") else None
        if not active:
            QMessageBox.information(self, "编辑成员", "请先选中（或新建）一个 profile")
            return
        configs = load_api_configs(self.base_dir)
        if not configs:
            QMessageBox.information(self, "编辑成员", "暂无 API 配置可加入")
            return
        state = load_profiles(self.base_dir)
        current = set(state.get("profiles", {}).get(active, []))

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑 profile 成员: {active}")
        dlg.resize(360, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"勾选属于 profile [{active}] 的 configs:"))
        boxes = []
        for c in configs:
            cb = QCheckBox(f"{c.get('kind')} · {c.get('name')} · {c.get('model', '')}")
            cb.setChecked(c.get("name") in current)
            cb._config_name = c.get("name")
            boxes.append(cb)
            v.addWidget(cb)
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        members = [cb._config_name for cb in boxes if cb.isChecked()]
        try:
            upsert_profile(self.base_dir, active, members)
        except ValueError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.refresh_api_list()

    def on_api_selected(self, row):
        self.current_api_index = row if 0 <= row < len(self.api_configs) else None
        if self.current_api_index is None:
            return
        self.load_api_form(self.api_configs[self.current_api_index])

    def load_api_form(self, config):
        self.kind.setCurrentText(str(config.get("kind") or "native_oai"))
        self.name.setText(str(config.get("name") or ""))
        self.apikey.setText(str(config.get("apikey") or ""))
        self.apibase.setText(str(config.get("apibase") or ""))
        self.model.setText(str(config.get("model") or ""))
        self.api_mode.setText(str(config.get("api_mode") or ""))
        self.stream.setChecked(bool(config.get("stream", True)))
        self.max_tokens.setText(str(config.get("max_tokens") or ""))
        self.timeout.setText(str(config.get("connect_timeout") or ""))
        self.llm_nos.setText(",".join(map(str, config.get("llm_nos") or [])))

    def form_config(self):
        config = {
            "kind": self.kind.currentText(),
            "name": self.name.text().strip(),
            "apikey": self.apikey.text().strip(),
            "apibase": self.apibase.text().strip(),
            "model": self.model.text().strip(),
            "api_mode": self.api_mode.text().strip(),
            "stream": self.stream.isChecked(),
            "max_tokens": self.max_tokens.text().strip(),
            "connect_timeout": self.timeout.text().strip(),
            "read_timeout": self.timeout.text().strip(),
            "llm_nos": self.llm_nos.text().strip(),
        }
        return {k: v for k, v in config.items() if v not in ("", None)}

    def new_api(self):
        self.current_api_index = None
        self.load_api_form({"kind": "native_oai", "stream": True})

    def save_api(self):
        config = self.form_config()
        configs = list(self.api_configs)
        if self.current_api_index is None:
            configs.append(config)
        else:
            configs[self.current_api_index] = config
        try:
            save_api_configs(self.base_dir, configs)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.refresh_api_list()
        self.refresh_llms()
        QMessageBox.information(self, "已保存", "API 配置已保存到 mykey_local_override.py")

    def delete_api(self):
        if self.current_api_index is None:
            return
        configs = list(self.api_configs)
        configs.pop(self.current_api_index)
        save_api_configs(self.base_dir, configs)
        self.refresh_api_list()

    def refresh_llms(self):
        try:
            from agentmain import GeneraticAgent
            agent = GeneraticAgent()
            lines = [f"{i}. {name}" for i, name, _cur in agent.list_llms()]
            self.llm_status.setPlainText("可用模型:\n" + ("\n".join(lines) if lines else "无"))
        except Exception as exc:
            self.llm_status.setPlainText(f"模型加载失败: {exc}")

    def closeEvent(self, event):
        self.pm.detach_all()
        if self.scheduler_proc and self.scheduler_proc.poll() is None:
            self.scheduler_proc.kill()
        event.accept()


def main():
    if QApplication is None:
        raise SystemExit("PySide6 is required. Install with: pip install PySide6")
    app = QApplication(sys.argv)
    win = QtLauncher()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
