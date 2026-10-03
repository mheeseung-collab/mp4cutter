# -*- coding: utf-8 -*-
"""
MP4 구간 자르기 (MP4 Cutter)
- MP4 불러오기 / 재생하며 시작점·끝점 지정 / 여러 구간(겹침 허용) 추가
- 각 구간을 원본파일명_01.mp4, 원본파일명_02.mp4 ... 로 저장
- FFmpeg는 imageio-ffmpeg 패키지에 포함된 것을 사용 (사용자 별도 설치 불필요)
"""
import os
import sys
import subprocess
import traceback
import faulthandler

# ---------------------------------------------------------------- 오류 기록 (실행이 안 될 때 원인 확인용)
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MP4Cutter")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    _crash_file = open(os.path.join(LOG_DIR, "crash_log.txt"), "w", encoding="utf-8")
    faulthandler.enable(file=_crash_file)
except Exception:
    pass


def show_fatal(msg):
    """오류 내용을 파일로 남기고 윈도우 메시지 창으로 보여준다."""
    log_path = os.path.join(LOG_DIR, "error_log.txt")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            "프로그램 실행 중 오류가 발생했습니다.\n이 창을 캡처해서 보여주세요.\n\n"
            + msg[-1800:] + f"\n\n(기록 파일: {log_path})",
            "MP4 구간 자르기 - 오류", 0x10)
    except Exception:
        print(msg)


def _excepthook(t, v, tb):
    show_fatal("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _excepthook

try:
    from PySide6.QtCore import Qt, QUrl, QThread, Signal
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QPushButton, QLabel, QSlider,
        QHBoxLayout, QVBoxLayout, QFileDialog, QTableWidget, QTableWidgetItem,
        QHeaderView, QMessageBox, QProgressBar, QCheckBox, QAbstractItemView,
        QGroupBox,
    )
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
except Exception:
    show_fatal("[구성요소 불러오기 실패]\n" + traceback.format_exc())
    sys.exit(1)

APP_TITLE = "MP4 구간 자르기"


# ---------------------------------------------------------------- 유틸
def fmt_ms(ms):
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def find_ffmpeg():
    """프로그램에 함께 들어있는 ffmpeg.exe 경로를 찾는다."""
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.argv[0])))
    for root, _dirs, files in os.walk(base):
        for f in files:
            fl = f.lower()
            if fl.startswith("ffmpeg") and fl.endswith(".exe"):
                return os.path.join(root, f)
    return None


# ---------------------------------------------------------------- 클릭한 위치로 바로 이동하는 슬라이더
class ClickSlider(QSlider):
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > self.minimum():
            x = e.position().x()
            w = max(1, self.width())
            val = self.minimum() + int((self.maximum() - self.minimum()) * x / w)
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(e)


# ---------------------------------------------------------------- FFmpeg 작업 스레드
class CutWorker(QThread):
    progress = Signal(int, int, float)   # 현재 인덱스, 전체 개수, 현재 파일 진행률(0~1)
    file_done = Signal(int, str)
    failed = Signal(str)
    done = Signal(bool)                  # 취소 여부

    def __init__(self, ffmpeg, src, jobs, accurate):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.src = src
        self.jobs = jobs                 # [(start_ms, end_ms, out_path), ...]
        self.accurate = accurate
        self._cancel = False
        self.proc = None

    def cancel(self):
        self._cancel = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def build_cmd(self, start, end, out):
        dur = (end - start) / 1000.0
        cmd = [self.ffmpeg, "-hide_banner", "-y",
               "-ss", f"{start / 1000.0:.3f}", "-i", self.src, "-t", f"{dur:.3f}",
               "-map", "0:v:0?", "-map", "0:a:0?"]
        if self.accurate:
            # 재인코딩: 지정한 시간에 정확히 잘림 (느림)
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        else:
            # 원본 복사: 매우 빠르지만 키프레임 단위로 잘려 앞뒤가 약간 어긋날 수 있음
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", out]
        return cmd

    def run(self):
        total = len(self.jobs)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for i, (start, end, out) in enumerate(self.jobs):
            if self._cancel:
                break
            dur = (end - start) / 1000.0
            try:
                self.proc = subprocess.Popen(
                    self.build_cmd(start, end, out),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", creationflags=flags)
            except Exception as ex:
                self.failed.emit(f"FFmpeg를 실행하지 못했습니다.\n{ex}")
                return

            tail = []
            for line in self.proc.stdout:
                line = line.strip()
                if line.startswith(("out_time_us=", "out_time_ms=")):
                    try:
                        us = int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    frac = min(1.0, max(0.0, us / 1e6 / dur)) if dur > 0 else 0.0
                    self.progress.emit(i, total, frac)
                elif line and "=" not in line:
                    tail = (tail + [line])[-15:]
            rc = self.proc.wait()

            if self._cancel:
                self._remove(out)
                break
            if rc != 0:
                self._remove(out)
                self.failed.emit(
                    f"{os.path.basename(out)} 저장 중 오류가 발생했습니다.\n\n" + "\n".join(tail))
                return
            self.progress.emit(i, total, 1.0)
            self.file_done.emit(i, out)
        self.done.emit(self._cancel)

    @staticmethod
    def _remove(path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


# ---------------------------------------------------------------- 메인 창
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 800)
        self.setAcceptDrops(True)

        self.src_path = None
        self.out_dir = None
        self.duration = 0
        self.mark_start = None
        self.mark_end = None
        self.segments = []          # [[start_ms, end_ms], ...]
        self.preview_end = None
        self.worker = None
        self.ffmpeg = find_ffmpeg()

        # 플레이어
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setStyleSheet("background:black;")
        self.video.setMinimumHeight(300)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.errorOccurred.connect(self.on_player_error)

        self._build_ui()
        self._build_shortcuts()
        self._update_marks()
        self._set_loaded(False)

    # ---------- UI 구성
    def _btn(self, text, slot, tip=None):
        b = QPushButton(text)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(slot)
        if tip:
            b.setToolTip(tip)
        return b

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        # 파일 열기
        top = QHBoxLayout()
        self.btn_open = self._btn("📂 MP4 파일 열기", self.open_file, "Ctrl+O · 파일을 창에 끌어다 놓아도 됩니다")
        self.lbl_file = QLabel("파일을 열거나 이 창에 MP4 파일을 끌어다 놓으세요.")
        top.addWidget(self.btn_open)
        top.addWidget(self.lbl_file, 1)
        root.addLayout(top)

        root.addWidget(self.video, 1)

        # 탐색 바
        self.slider = ClickSlider(Qt.Horizontal)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.sliderMoved.connect(self.player.setPosition)
        root.addWidget(self.slider)

        # 재생 컨트롤
        ctl = QHBoxLayout()
        self.btn_b5 = self._btn("⏪ 5초", lambda: self.seek_rel(-5000), "Shift+←")
        self.btn_b1 = self._btn("◀ 1초", lambda: self.seek_rel(-1000), "←")
        self.btn_b01 = self._btn("◂ 0.1초", lambda: self.seek_rel(-100), "Ctrl+←")
        self.btn_play = self._btn("▶ 재생", self.toggle_play, "Space")
        self.btn_f01 = self._btn("0.1초 ▸", lambda: self.seek_rel(100), "Ctrl+→")
        self.btn_f1 = self._btn("1초 ▶", lambda: self.seek_rel(1000), "→")
        self.btn_f5 = self._btn("5초 ⏩", lambda: self.seek_rel(5000), "Shift+→")
        self.lbl_time = QLabel("00:00:00.000 / 00:00:00.000")
        self.lbl_time.setStyleSheet("font-family: Consolas, monospace; font-size: 14px;")
        for w in (self.btn_b5, self.btn_b1, self.btn_b01, self.btn_play,
                  self.btn_f01, self.btn_f1, self.btn_f5):
            ctl.addWidget(w)
        ctl.addStretch(1)
        ctl.addWidget(self.lbl_time)
        root.addLayout(ctl)

        # 구간 지정
        grp = QGroupBox("구간 지정")
        g = QHBoxLayout(grp)
        self.btn_start = self._btn("⬅ 시작점 지정 (I)", self.set_start)
        self.lbl_start = QLabel()
        self.btn_end = self._btn("끝점 지정 (O) ➡", self.set_end)
        self.lbl_end = QLabel()
        self.btn_add = self._btn("➕ 구간 추가 (Enter)", self.add_segment)
        self.btn_add.setStyleSheet("font-weight:bold;")
        for lbl in (self.lbl_start, self.lbl_end):
            lbl.setStyleSheet("font-family: Consolas, monospace; font-size: 14px; padding: 0 8px;")
        g.addWidget(self.btn_start)
        g.addWidget(self.lbl_start)
        g.addSpacing(10)
        g.addWidget(self.btn_end)
        g.addWidget(self.lbl_end)
        g.addStretch(1)
        g.addWidget(self.btn_add)
        root.addWidget(grp)

        # 구간 목록
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["번호", "시작", "끝", "길이", "저장될 파일명"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        hh = self.table.horizontalHeader()
        for c in range(4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.preview_row(r))
        root.addWidget(self.table)

        row = QHBoxLayout()
        self.btn_preview = self._btn("▶ 선택 구간 미리보기", self.preview_selected, "목록을 더블클릭해도 됩니다")
        self.btn_del = self._btn("🗑 선택 삭제 (Del)", self.delete_selected)
        self.btn_clear = self._btn("전체 삭제", self.clear_segments)
        self.btn_sort = self._btn("시작 시간순 정렬", self.sort_segments)
        for w in (self.btn_preview, self.btn_del, self.btn_clear, self.btn_sort):
            row.addWidget(w)
        row.addStretch(1)
        root.addLayout(row)

        # 저장 설정
        save = QGroupBox("저장")
        s = QVBoxLayout(save)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("저장 폴더:"))
        self.lbl_out = QLabel("-")
        r1.addWidget(self.lbl_out, 1)
        self.btn_outdir = self._btn("폴더 변경", self.choose_outdir)
        r1.addWidget(self.btn_outdir)
        s.addLayout(r1)

        r2 = QHBoxLayout()
        self.chk_accurate = QCheckBox("정확하게 자르기 (권장 · 재인코딩이라 조금 느림)")
        self.chk_accurate.setChecked(True)
        self.chk_accurate.setFocusPolicy(Qt.NoFocus)
        self.chk_accurate.setToolTip(
            "체크 해제 시: 원본을 그대로 복사해 매우 빠르지만,\n"
            "영상 구조상 시작/끝이 1~수 초 정도 어긋날 수 있습니다.")
        r2.addWidget(self.chk_accurate)
        r2.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setMinimumWidth(260)
        self.progress.setVisible(False)
        r2.addWidget(self.progress)
        self.btn_save = self._btn("💾 모든 구간 저장", self.save_all)
        self.btn_save.setStyleSheet("font-weight:bold; padding: 6px 16px;")
        r2.addWidget(self.btn_save)
        s.addLayout(r2)
        root.addWidget(save)

        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "단축키  Space: 재생/정지 · ←/→: 1초 · Shift: 5초 · Ctrl: 0.1초 · I: 시작점 · O: 끝점 · Enter: 구간 추가")

    def _build_shortcuts(self):
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(fn)
        sc("Ctrl+O", self.open_file)
        sc("Space", self.toggle_play)
        sc("Left", lambda: self.seek_rel(-1000))
        sc("Right", lambda: self.seek_rel(1000))
        sc("Shift+Left", lambda: self.seek_rel(-5000))
        sc("Shift+Right", lambda: self.seek_rel(5000))
        sc("Ctrl+Left", lambda: self.seek_rel(-100))
        sc("Ctrl+Right", lambda: self.seek_rel(100))
        sc("I", self.set_start)
        sc("O", self.set_end)
        sc("Return", self.add_segment)
        sc("Enter", self.add_segment)
        sc("Delete", self.delete_selected)

    def _set_loaded(self, loaded):
        busy = self.worker is not None
        en = loaded and not busy
        for w in (self.btn_b5, self.btn_b1, self.btn_b01, self.btn_play, self.btn_f01,
                  self.btn_f1, self.btn_f5, self.btn_start, self.btn_end, self.btn_add,
                  self.btn_preview, self.btn_del, self.btn_clear, self.btn_sort,
                  self.btn_outdir, self.chk_accurate, self.slider):
            w.setEnabled(en)
        self.btn_open.setEnabled(not busy)
        self.btn_save.setEnabled(loaded)
        self.btn_save.setText("■ 저장 취소" if busy else "💾 모든 구간 저장")

    # ---------- 파일
    def open_file(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "MP4 파일 선택", self.out_dir or "",
            "동영상 (*.mp4 *.m4v *.mov);;모든 파일 (*.*)")
        if path:
            self.load(path)

    def load(self, path):
        if self.worker:
            return
        if self.segments:
            r = QMessageBox.question(self, APP_TITLE,
                                     "새 파일을 열면 현재 구간 목록이 지워집니다. 계속할까요?")
            if r != QMessageBox.Yes:
                return
        self.src_path = os.path.abspath(path)
        self.out_dir = os.path.dirname(self.src_path)
        self.lbl_out.setText(self.out_dir)
        self.lbl_file.setText(os.path.basename(self.src_path))
        self.setWindowTitle(f"{APP_TITLE} - {os.path.basename(self.src_path)}")
        self.segments.clear()
        self.mark_start = self.mark_end = None
        self.preview_end = None
        self._update_marks()
        self._refresh_table()
        self.player.setSource(QUrl.fromLocalFile(self.src_path))
        self.player.pause()   # 첫 화면 표시
        self._set_loaded(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                self.load(p)
                break

    def choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.out_dir or "")
        if d:
            self.out_dir = d
            self.lbl_out.setText(d)

    # ---------- 재생
    def toggle_play(self):
        if not self.src_path or self.worker:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.preview_end = None
            self.player.play()

    def seek_rel(self, delta):
        if not self.src_path or self.worker:
            return
        pos = min(max(0, self.player.position() + delta), self.duration)
        self.player.setPosition(pos)

    def on_position(self, pos):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.lbl_time.setText(f"{fmt_ms(pos)} / {fmt_ms(self.duration)}")
        if self.preview_end is not None and pos >= self.preview_end:
            self.player.pause()
            self.preview_end = None

    def on_duration(self, d):
        self.duration = d
        self.slider.setRange(0, d)
        self.lbl_time.setText(f"{fmt_ms(self.player.position())} / {fmt_ms(d)}")

    def on_state(self, st):
        self.btn_play.setText("⏸ 일시정지" if st == QMediaPlayer.PlayingState else "▶ 재생")

    def on_player_error(self, _err, msg):
        if msg:
            QMessageBox.warning(self, APP_TITLE,
                                f"영상을 재생하는 중 문제가 생겼습니다.\n{msg}\n\n"
                                "재생이 안 되더라도 구간 저장은 될 수 있습니다.")

    # ---------- 구간
    def set_start(self):
        if not self.src_path or self.worker:
            return
        self.mark_start = self.player.position()
        if self.mark_end is not None and self.mark_end <= self.mark_start:
            self.mark_end = None
        self._update_marks()

    def set_end(self):
        if not self.src_path or self.worker:
            return
        pos = self.player.position()
        if self.mark_start is not None and pos <= self.mark_start:
            QMessageBox.information(self, APP_TITLE, "끝점은 시작점보다 뒤여야 합니다.")
            return
        self.mark_end = pos
        self._update_marks()

    def _update_marks(self):
        self.lbl_start.setText(fmt_ms(self.mark_start) if self.mark_start is not None else "--:--:--.---")
        self.lbl_end.setText(fmt_ms(self.mark_end) if self.mark_end is not None else "--:--:--.---")

    def add_segment(self):
        if not self.src_path or self.worker:
            return
        if self.mark_start is None or self.mark_end is None:
            QMessageBox.information(self, APP_TITLE, "시작점(I)과 끝점(O)을 먼저 지정하세요.")
            return
        if self.mark_end - self.mark_start < 100:
            QMessageBox.information(self, APP_TITLE, "구간이 너무 짧습니다 (0.1초 이상).")
            return
        self.segments.append([self.mark_start, self.mark_end])
        self.mark_start = self.mark_end = None
        self._update_marks()
        self._refresh_table()
        self.table.selectRow(len(self.segments) - 1)

    def _out_name(self, idx):
        base = os.path.splitext(os.path.basename(self.src_path))[0]
        return f"{base}_{idx + 1:02d}.mp4"

    def _refresh_table(self):
        self.table.setRowCount(len(self.segments))
        for i, (s, e) in enumerate(self.segments):
            vals = [str(i + 1), fmt_ms(s), fmt_ms(e), fmt_ms(e - s), self._out_name(i)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c < 4:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, c, it)

    def _selected_rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def delete_selected(self):
        if self.worker:
            return
        rows = self._selected_rows()
        for r in reversed(rows):
            del self.segments[r]
        self._refresh_table()

    def clear_segments(self):
        if self.segments and QMessageBox.question(
                self, APP_TITLE, "구간을 모두 지울까요?") == QMessageBox.Yes:
            self.segments.clear()
            self._refresh_table()

    def sort_segments(self):
        self.segments.sort(key=lambda x: (x[0], x[1]))
        self._refresh_table()

    def preview_selected(self):
        rows = self._selected_rows()
        if rows:
            self.preview_row(rows[0])

    def preview_row(self, r):
        if self.worker or r >= len(self.segments):
            return
        s, e = self.segments[r]
        self.player.setPosition(s)
        self.preview_end = e
        self.player.play()

    # ---------- 저장
    def save_all(self):
        if self.worker:
            self.worker.cancel()
            return
        if not self.segments:
            QMessageBox.information(self, APP_TITLE, "저장할 구간이 없습니다. 먼저 구간을 추가하세요.")
            return
        if not self.ffmpeg:
            QMessageBox.critical(self, APP_TITLE, "프로그램 안의 FFmpeg를 찾을 수 없습니다. 다시 설치해 주세요.")
            return
        if not os.path.isdir(self.out_dir):
            QMessageBox.warning(self, APP_TITLE, "저장 폴더가 존재하지 않습니다.")
            return

        jobs = []
        for i, (s, e) in enumerate(self.segments):
            out = os.path.join(self.out_dir, self._out_name(i))
            if os.path.normcase(os.path.abspath(out)) == os.path.normcase(self.src_path):
                QMessageBox.critical(self, APP_TITLE, "저장 파일명이 원본과 같습니다. 저장 폴더를 바꿔 주세요.")
                return
            jobs.append((s, e, out))

        exist = [os.path.basename(j[2]) for j in jobs if os.path.exists(j[2])]
        if exist:
            preview = "\n".join(exist[:10]) + ("\n..." if len(exist) > 10 else "")
            r = QMessageBox.question(self, APP_TITLE,
                                     f"아래 파일이 이미 있습니다. 덮어쓸까요?\n\n{preview}")
            if r != QMessageBox.Yes:
                return

        self.player.pause()
        self.preview_end = None
        self.worker = CutWorker(self.ffmpeg, self.src_path, jobs, self.chk_accurate.isChecked())
        self.worker.progress.connect(self.on_progress)
        self.worker.failed.connect(self.on_failed)
        self.worker.done.connect(self.on_done)
        self.worker.finished.connect(self.on_worker_finished)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._set_loaded(True)
        self.worker.start()

    def on_progress(self, i, total, frac):
        self.progress.setValue(int((i + frac) / total * 1000))
        self.progress.setFormat(f"{i + 1}/{total} 저장 중... %p%")

    def on_failed(self, msg):
        QMessageBox.critical(self, APP_TITLE, msg)

    def on_done(self, cancelled):
        if cancelled:
            QMessageBox.information(self, APP_TITLE, "저장을 취소했습니다.")
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setText(f"{len(self.segments)}개 파일을 저장했습니다.\n\n{self.out_dir}")
        open_btn = box.addButton("폴더 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == open_btn and os.name == "nt":
            os.startfile(self.out_dir)

    def on_worker_finished(self):
        self.worker = None
        self.progress.setVisible(False)
        self._set_loaded(self.src_path is not None)

    def closeEvent(self, e):
        if self.worker:
            if QMessageBox.question(self, APP_TITLE, "저장 중입니다. 취소하고 종료할까요?") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)
        self.player.stop()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        w.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        show_fatal(traceback.format_exc())
        sys.exit(1)
