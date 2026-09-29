"""
Source Material Fetcher
------------------------
Finds and packages every .vmt/.vtf material dependency of one or
more Source Engine .mdl models into a single ZIP, preserving the
materials/... folder structure.

Pipeline: MDL -> parse materials -> resolve VMT/VTF in configured
folders -> copy with structure preserved -> ZIP

Not yet included (see README Roadmap): VPK archive scanning,
automatic Steam library / installed-game detection.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QByteArray
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.pipeline import run_pipeline
from core.settings import load_settings, save_settings
from core.updater import UpdateCheckError, UpdateInfo, apply_update_and_restart, check_for_update, download_update, is_frozen
from core.version import APP_NAME, APP_VERSION, ARTSTATION_URL, GITHUB_URL

ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"

DARK_STYLE = """
QWidget { background-color: #1e1f24; color: #e6e6e6; font-size: 13px; }
QMainWindow { background-color: #1e1f24; }
QMenuBar { background-color: #1e1f24; color: #e6e6e6; }
QMenuBar::item:selected { background-color: #363944; }
QMenu { background-color: #26272e; border: 1px solid #3a3d47; }
QMenu::item:selected { background-color: #363944; }
QPushButton {
    background-color: #2c2e36; border: 1px solid #3a3d47; border-radius: 6px;
    padding: 8px 14px;
}
QPushButton:hover { background-color: #363944; }
QPushButton:pressed { background-color: #23252c; }
QPushButton:disabled { color: #6b6d76; }
QPushButton#primary { background-color: #4a6cf7; border: none; font-weight: 600; }
QPushButton#primary:hover { background-color: #5b7bff; }
QListWidget, QTextEdit {
    background-color: #26272e; border: 1px solid #3a3d47; border-radius: 6px;
}
QLabel#dropzone {
    border: 2px dashed #4a4d59; border-radius: 10px; padding: 30px;
    color: #9a9da8; font-size: 14px;
}
QLabel#header { font-size: 18px; font-weight: 700; }
QLabel#subheader { color: #9a9da8; }
QLabel#section { color: #c7c9d1; font-weight: 600; margin-top: 6px; }
QStatusBar { background-color: #17181c; color: #9a9da8; }
QProgressBar {
    background-color: #26272e; border: 1px solid #3a3d47; border-radius: 4px;
    text-align: center; color: #e6e6e6; max-height: 14px;
}
QProgressBar::chunk { background-color: #4a6cf7; border-radius: 3px; }
"""


class Worker(QThread):
    progress = Signal(str)
    model_done = Signal(int, str, int, int)   # index, name, found_count, missing_count
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, mdl_paths: list[Path], roots: list[Path], do_package: bool, output_dir: Path | None):
        super().__init__()
        self.mdl_paths = mdl_paths
        self.roots = roots
        self.do_package = do_package
        self.output_dir = output_dir

    def run(self):
        try:
            result = run_pipeline(
                self.mdl_paths, self.roots, self.do_package, self.output_dir,
                progress_cb=self.progress.emit,
                model_done_cb=lambda i, report: self.model_done.emit(
                    i, report.path.name, report.found_count, report.missing_count
                ),
            )
            lines = _build_report_lines(result)
            self.finished_ok.emit({
                "found": result.combined_found,
                "missing": result.combined_missing,
                "lines": lines,
            })
        except Exception:
            self.failed.emit("Unexpected error:\n" + traceback.format_exc())


def _build_report_lines(result) -> list[tuple[str, str]]:
    """Turns a core.pipeline.PipelineResult into (color_kind, text) lines
    for the report box. Kept in the UI layer since the coloring/format
    is presentation, not pipeline logic.
    """
    lines: list[tuple[str, str]] = []
    for report in result.model_reports:
        if report.error:
            lines.append(("missing", f"{report.path.name}: MDL parse error: {report.error}"))
            lines.append(("plain", ""))
            continue

        lines.append(("info", f"{report.path.name}  (MDL v{report.version}, {report.material_count} materials)"))
        for w in report.warnings:
            lines.append(("warn", f"  ! {w}"))
        lines.append(("ok", f"  found: {report.found_count} files"))
        if report.missing:
            lines.append(("warn", f"  missing: {report.missing_count}"))
            for m in report.missing:
                lines.append(("missing", f"    - {m}"))
        lines.append(("plain", ""))

    if result.zip_path:
        lines.append(("ok", f"Packaged {result.written_count} files -> {result.zip_path}"))

    return lines


class UpdateCheckWorker(QThread):
    found = Signal(object)     # UpdateInfo
    none_found = Signal()
    failed = Signal(str)

    def run(self):
        try:
            info = check_for_update(APP_VERSION)
        except UpdateCheckError as e:
            self.failed.emit(str(e))
            return
        if info is None:
            self.none_found.emit()
        else:
            self.found.emit(info)


class UpdateDownloadWorker(QThread):
    progress = Signal(int, int)   # bytes_read, total_bytes
    done = Signal(Path)
    failed = Signal(str)

    def __init__(self, info: UpdateInfo):
        super().__init__()
        self.info = info

    def run(self):
        try:
            path = download_update(self.info, progress_cb=lambda r, t: self.progress.emit(r, t))
            self.done.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class DropArea(QLabel):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__("DROP .MDL FILES HERE\n\nor use the Browse Files button below")
        self.setObjectName("dropzone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()]
        self.files_dropped.emit(paths)


LINE_COLORS = {
    "info": "#c7c9d1",
    "ok": "#6bd37a",
    "warn": "#e8b64c",
    "missing": "#e8615c",
    "plain": "#9a9da8",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(760, 760)
        icon_path = ASSETS_DIR / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.settings = load_settings()
        self.model_paths: list[Path] = []
        self.output_dir: Path | None = (
            Path(self.settings["last_output_dir"]) if self.settings.get("last_output_dir") else None
        )
        self.worker: Worker | None = None

        self._build_menu_bar()
        self._build_central_widget()
        self._build_status_bar()
        self._restore_geometry()

        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.pending_update: UpdateInfo | None = None
        # Silent background check on startup -- never interrupts the user,
        # just lights up the status-bar button if something newer exists.
        self.check_for_updates(manual=False)

    # ---- menu bar ----

    def _build_menu_bar(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        add_model_action = QAction("Add Model(s)...", self)
        add_model_action.triggered.connect(self.browse_models)
        file_menu.addAction(add_model_action)

        add_folder_action = QAction("Add Search Folder...", self)
        add_folder_action.triggered.connect(self.add_search_root)
        file_menu.addAction(add_folder_action)

        clear_models_action = QAction("Clear All Models", self)
        clear_models_action.triggered.connect(self.clear_models)
        file_menu.addAction(clear_models_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        github_action = QAction("Open GitHub Repo", self)
        github_action.triggered.connect(self.open_github)
        help_menu.addAction(github_action)

        artstation_action = QAction("Open ArtStation Portfolio", self)
        artstation_action.triggered.connect(self.open_artstation)
        help_menu.addAction(artstation_action)

        check_update_action = QAction("Check for Updates...", self)
        check_update_action.triggered.connect(lambda: self.check_for_updates(manual=True))
        help_menu.addAction(check_update_action)

    def show_about(self):
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> v{APP_VERSION}<br><br>"
            "Finds and packages Source Engine .mdl material dependencies "
            "into a ZIP, preserving folder structure.<br><br>"
            "By Anas (ellemti)<br>"
            f"<a href='{GITHUB_URL}'>GitHub</a> &nbsp;&middot;&nbsp; "
            f"<a href='{ARTSTATION_URL}'>ArtStation</a>",
        )

    def open_github(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(GITHUB_URL))

    def open_artstation(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(ARTSTATION_URL))

    # ---- central widget ----

    def _build_central_widget(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        header_row = QHBoxLayout()
        icon_label = QLabel()
        icon_path = ASSETS_DIR / "icon.png"
        if icon_path.exists():
            icon_label.setPixmap(QPixmap(str(icon_path)).scaled(
                36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
        header = QLabel("SOURCE MATERIAL FETCHER")
        header.setObjectName("header")
        header_row.addWidget(icon_label)
        header_row.addWidget(header)
        header_row.addStretch()
        layout.addLayout(header_row)

        sub = QLabel("Fetch and package Source Engine model material dependencies")
        sub.setObjectName("subheader")
        layout.addWidget(sub)

        self.dropzone = DropArea()
        self.dropzone.files_dropped.connect(self.add_models)
        layout.addWidget(self.dropzone)

        browse_row = QHBoxLayout()
        browse_btn = QPushButton("Browse Files")
        browse_btn.clicked.connect(self.browse_models)
        browse_row.addWidget(browse_btn)
        browse_row.addStretch()
        layout.addLayout(browse_row)

        layout.addWidget(self._section_label("Input Models"))
        self.model_list = QListWidget()
        self.model_list.setMaximumHeight(120)
        self.model_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.model_list.customContextMenuRequested.connect(self._model_context_menu)
        layout.addWidget(self.model_list)
        remove_model_btn = QPushButton("Remove Selected Model")
        remove_model_btn.clicked.connect(self.remove_selected_model)
        layout.addWidget(remove_model_btn)

        layout.addWidget(self._section_label("Search Locations (folders containing a materials/ subfolder)"))
        self.roots_list = QListWidget()
        self.roots_list.setMaximumHeight(110)
        for r in self.settings.get("search_roots", []):
            self.roots_list.addItem(QListWidgetItem(r))
        layout.addWidget(self.roots_list)
        roots_row = QHBoxLayout()
        add_root_btn = QPushButton("Add Folder...")
        add_root_btn.clicked.connect(self.add_search_root)
        remove_root_btn = QPushButton("Remove Selected")
        remove_root_btn.clicked.connect(self.remove_selected_root)
        roots_row.addWidget(add_root_btn)
        roots_row.addWidget(remove_root_btn)
        roots_row.addStretch()
        layout.addLayout(roots_row)

        layout.addWidget(self._section_label("Output"))
        out_row = QHBoxLayout()
        self.output_label = QLabel(str(self.output_dir) if self.output_dir else "(no output folder selected)")
        out_browse_btn = QPushButton("Browse")
        out_browse_btn.clicked.connect(self.browse_output)
        out_row.addWidget(self.output_label, 1)
        out_row.addWidget(out_browse_btn)
        layout.addLayout(out_row)

        actions_row = QHBoxLayout()
        analyze_btn = QPushButton("ANALYZE")
        analyze_btn.setToolTip("Dry run: scans and reports found/missing files without writing anything to disk.")
        analyze_btn.clicked.connect(lambda: self.run_pipeline(package=False))
        fetch_btn = QPushButton("FETCH && CREATE ZIP")
        fetch_btn.setObjectName("primary")
        fetch_btn.setToolTip("Copies every resolved file to the output folder and packages it into a ZIP.")
        fetch_btn.clicked.connect(lambda: self.run_pipeline(package=True))
        self.analyze_btn = analyze_btn
        self.fetch_btn = fetch_btn
        actions_row.addWidget(analyze_btn)
        actions_row.addWidget(fetch_btn)
        layout.addLayout(actions_row)

        report_header_row = QHBoxLayout()
        report_header_row.addWidget(self._section_label("Report"))
        report_header_row.addStretch()
        self.copy_report_btn = QPushButton("Copy Report")
        self.copy_report_btn.setEnabled(False)
        self.copy_report_btn.clicked.connect(self.copy_report)
        self.open_output_btn = QPushButton("Open Output Folder")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self.open_output_folder)
        report_header_row.addWidget(self.copy_report_btn)
        report_header_row.addWidget(self.open_output_btn)
        layout.addLayout(report_header_row)

        self.report_box = QTextEdit()
        self.report_box.setReadOnly(True)
        layout.addWidget(self.report_box, 1)

        footer = QLabel(
            f'by Anas (ellemti) &nbsp;&middot;&nbsp; '
            f'<a href="{GITHUB_URL}" style="color:#9a9da8;">GitHub</a> &nbsp;&middot;&nbsp; '
            f'<a href="{ARTSTATION_URL}" style="color:#9a9da8;">ArtStation</a>'
        )
        footer.setOpenExternalLinks(True)
        footer.setStyleSheet("color: #6b6d76; font-size: 11px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(footer)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("section")
        return lbl

    # ---- status bar ----

    def _build_status_bar(self):
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_label = QLabel("Ready")
        bar.addWidget(self.status_label, 1)

        self.update_btn = QPushButton()
        self.update_btn.setObjectName("primary")
        self.update_btn.setVisible(False)
        self.update_btn.clicked.connect(self._on_update_button_clicked)
        bar.addPermanentWidget(self.update_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setVisible(False)
        bar.addPermanentWidget(self.progress_bar)
        self._update_status_summary()

    def _update_status_summary(self):
        self.status_label.setText(
            f"{len(self.model_paths)} model(s) loaded, {self.roots_list.count()} search folder(s)"
        )

    # ---- model input ----

    def add_models(self, paths: list[Path]):
        added = 0
        rejected = []
        for p in paths:
            if p.suffix.lower() != ".mdl":
                rejected.append(p.name)
                continue
            if p not in self.model_paths:
                self.model_paths.append(p)
                item = QListWidgetItem(f"\u25CB  {p.name}    ({p})")  # hollow circle = not yet analyzed
                self.model_list.addItem(item)
                added += 1
        if rejected:
            QMessageBox.warning(
                self, "Unsupported files",
                "These files were skipped (only .mdl is supported):\n" + "\n".join(rejected),
            )
        self._update_status_summary()

    def browse_models(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Select .mdl files", "", "Source Models (*.mdl)")
        if files:
            self.add_models([Path(f) for f in files])

    def remove_selected_model(self):
        for item in self.model_list.selectedItems():
            row = self.model_list.row(item)
            self.model_list.takeItem(row)
            del self.model_paths[row]
        self._update_status_summary()

    def clear_models(self):
        self.model_list.clear()
        self.model_paths.clear()
        self._update_status_summary()

    def _model_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.model_list.itemAt(pos)
        if item is None:
            return
        row = self.model_list.row(item)
        menu = QMenu(self)
        remove_action = menu.addAction("Remove")
        show_action = menu.addAction("Show in Explorer")
        chosen = menu.exec(self.model_list.mapToGlobal(pos))
        if chosen == remove_action:
            self.model_list.takeItem(row)
            del self.model_paths[row]
            self._update_status_summary()
        elif chosen == show_action:
            self._reveal_in_explorer(self.model_paths[row])

    @staticmethod
    def _reveal_in_explorer(path: Path):
        import subprocess
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(path)])

    # ---- search roots ----

    def add_search_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select a Source content folder")
        if d:
            self.roots_list.addItem(QListWidgetItem(d))
            self._persist_settings()
            self._update_status_summary()

    def remove_selected_root(self):
        for item in self.roots_list.selectedItems():
            self.roots_list.takeItem(self.roots_list.row(item))
        self._persist_settings()
        self._update_status_summary()

    def _current_roots(self) -> list[Path]:
        return [Path(self.roots_list.item(i).text()) for i in range(self.roots_list.count())]

    # ---- output ----

    def browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.output_dir = Path(d)
            self.output_label.setText(str(self.output_dir))
            self._persist_settings()

    def open_output_folder(self):
        import subprocess
        if self.output_dir and self.output_dir.exists() and sys.platform == "win32":
            subprocess.run(["explorer", str(self.output_dir)])

    def _persist_settings(self):
        self.settings["search_roots"] = [self.roots_list.item(i).text() for i in range(self.roots_list.count())]
        self.settings["last_output_dir"] = str(self.output_dir) if self.output_dir else ""
        save_settings(self.settings)

    # ---- window geometry ----

    def _restore_geometry(self):
        hex_geo = self.settings.get("window_geometry")
        if hex_geo:
            try:
                self.restoreGeometry(QByteArray.fromHex(hex_geo.encode("ascii")))
            except Exception:
                pass

    def closeEvent(self, event):
        self.settings["window_geometry"] = bytes(self.saveGeometry().toHex()).decode("ascii")
        self._persist_settings()
        super().closeEvent(event)

    # ---- pipeline ----

    def run_pipeline(self, package: bool):
        if not self.model_paths:
            QMessageBox.information(self, "No models", "Add at least one .mdl file first.")
            return
        roots = self._current_roots()
        if not roots:
            QMessageBox.information(self, "No search locations", "Add at least one search folder first.")
            return
        if package and not self.output_dir:
            QMessageBox.information(self, "No output folder", "Choose an output folder first.")
            return

        self.report_box.clear()
        self.copy_report_btn.setEnabled(False)
        self.open_output_btn.setEnabled(False)
        self._set_busy(True, "Working...")

        self.worker = Worker(list(self.model_paths), roots, package, self.output_dir)
        self.worker.progress.connect(self._on_progress)
        self.worker.model_done.connect(self._on_model_done)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _set_busy(self, busy: bool, status_text: str | None = None):
        self.analyze_btn.setEnabled(not busy)
        self.fetch_btn.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        if status_text:
            self.status_label.setText(status_text)
        elif not busy:
            self._update_status_summary()

    def _on_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_model_done(self, index: int, name: str, found_count: int, missing_count: int):
        item = self.model_list.item(index)
        if item is None:
            return
        icon = "\u2713" if missing_count == 0 else ("\u26A0" if found_count > 0 else "\u2717")
        item.setText(f"{icon}  {name}    ({found_count} found, {missing_count} missing)")

    def _on_finished(self, result: dict):
        self._append_colored_lines(result["lines"])
        self._set_busy(False)
        self.copy_report_btn.setEnabled(True)
        if self.output_dir:
            self.open_output_btn.setEnabled(True)

    def _on_failed(self, message: str):
        self.report_box.append(f'<span style="color:{LINE_COLORS["missing"]}">ERROR: {message}</span>')
        self._set_busy(False, "Failed")

    def _append_colored_lines(self, lines: list[tuple[str, str]]):
        for kind, text in lines:
            color = LINE_COLORS.get(kind, "#e6e6e6")
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.report_box.append(f'<span style="color:{color}">{safe or "&nbsp;"}</span>')

    def copy_report(self):
        QApplication.clipboard().setText(self.report_box.toPlainText())
        self.status_label.setText("Report copied to clipboard")

    # ---- updates ----

    def check_for_updates(self, manual: bool):
        self.update_check_worker = UpdateCheckWorker()
        self.update_check_worker.found.connect(lambda info: self._on_update_found(info, manual))
        self.update_check_worker.none_found.connect(lambda: self._on_no_update(manual))
        self.update_check_worker.failed.connect(lambda msg: self._on_update_check_failed(msg, manual))
        self.update_check_worker.start()
        if manual:
            self.status_label.setText("Checking for updates...")

    def _on_update_found(self, info: UpdateInfo, manual: bool):
        self.pending_update = info
        self.update_btn.setText(f"Update available: {info.tag}")
        self.update_btn.setVisible(True)
        if manual:
            QMessageBox.information(
                self, "Update available",
                f"Version {info.tag} is available (you have v{APP_VERSION}).\n\n"
                "Click the 'Update available' button in the status bar to download and install it.",
            )

    def _on_no_update(self, manual: bool):
        if manual:
            QMessageBox.information(self, "Up to date", f"You're running the latest version (v{APP_VERSION}).")

    def _on_update_check_failed(self, message: str, manual: bool):
        if manual:
            QMessageBox.warning(self, "Update check failed", message)
        # Silent on startup -- no internet / repo not published yet shouldn't nag the user.

    def _on_update_button_clicked(self):
        if not self.pending_update:
            return
        if not is_frozen():
            QMessageBox.information(
                self, "Update available",
                f"Version {self.pending_update.tag} is available, but auto-install only works "
                f"in the built .exe (you're running from source).\n\n{GITHUB_URL}/releases",
            )
            return

        reply = QMessageBox.question(
            self, "Install update?",
            f"Download and install {self.pending_update.tag} now?\n\n"
            "The app will close and reopen automatically once the update is applied.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.update_btn.setEnabled(False)
        self._set_busy(True, f"Downloading {self.pending_update.tag}...")
        self.update_download_worker = UpdateDownloadWorker(self.pending_update)
        self.update_download_worker.progress.connect(self._on_update_download_progress)
        self.update_download_worker.done.connect(self._on_update_downloaded)
        self.update_download_worker.failed.connect(self._on_update_download_failed)
        self.update_download_worker.start()

    def _on_update_download_progress(self, read: int, total: int):
        if total:
            pct = int(read * 100 / total)
            self.status_label.setText(f"Downloading update... {pct}%")

    def _on_update_downloaded(self, new_exe_path: Path):
        try:
            apply_update_and_restart(new_exe_path)
        except Exception as e:
            QMessageBox.critical(self, "Update failed", f"Could not apply the update:\n{e}")
            self._set_busy(False)
            self.update_btn.setEnabled(True)
            return
        QApplication.instance().quit()

    def _on_update_download_failed(self, message: str):
        QMessageBox.warning(self, "Download failed", message)
        self._set_busy(False)
        self.update_btn.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
