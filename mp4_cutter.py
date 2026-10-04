# -*- coding: utf-8 -*-
"""
QuickSplit - 원하는 구간만 쉽게 추출하는 영상 구간 추출기
- 영상 불러오기 / 재생하며 시작점·끝점 지정 / 여러 구간(겹침 허용) 추가
- 각 구간을 원본파일명_01.mp4, 원본파일명_02.mp4 ... 로 저장
- FFmpeg는 imageio-ffmpeg 패키지에 포함된 것을 사용 (사용자 별도 설치 불필요)
"""
import os
import sys
import shutil
import tempfile
import subprocess
import traceback
import faulthandler

# ================================================================ 오류 기록
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "MP4Cutter")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    _crash_file = open(os.path.join(LOG_DIR, "crash_log.txt"), "w", encoding="utf-8")
    faulthandler.enable(file=_crash_file)
except Exception:
    pass


def show_fatal(msg):
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
            "QuickSplit - 오류", 0x10)
    except Exception:
        print(msg)


def _excepthook(t, v, tb):
    show_fatal("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _excepthook

try:
    from PySide6.QtCore import (Qt, QUrl, QThread, Signal, QSize, QSizeF, QRectF,
                                QPointF, QEvent)
    from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QIcon, QPixmap, QImage,
                               QPainterPath, QPolygonF, QRegion, QPalette, QFontMetrics)
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QPushButton, QLabel, QSlider,
        QHBoxLayout, QVBoxLayout, QGridLayout, QFileDialog, QMessageBox, QCheckBox,
        QFrame, QGraphicsView, QGraphicsScene, QToolTip, QScrollArea, QLineEdit,
        QComboBox, QDialog, QDialogButtonBox, QSizePolicy,
    )
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
except Exception:
    show_fatal("[구성요소 불러오기 실패]\n" + traceback.format_exc())
    sys.exit(1)

APP_NAME = "QuickSplit"
ACCENT = "#1D6CF2"
RED = "#E5486B"
SEG_COLORS = ["#2F7BF6", "#EC4D78", "#20AE78", "#F29D0B",
              "#8B5CF6", "#08B2CF", "#EF6C35", "#64748B"]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# ================================================================ 시간 표시
def fmt_ms(ms):
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def fmt_hms(ms):
    s = max(0, int(ms)) // 1000
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fmt_t1(ms):
    ms = max(0, int(ms))
    return f"{fmt_hms(ms)}.{ms % 1000 // 100}"


def fmt_len(ms):
    sec = max(0, int(ms)) / 1000
    if sec < 60:
        return f"{sec:.1f}초"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{int(m)}분 {s:.1f}초"
    h, m = divmod(int(m), 60)
    return f"{h}시간 {m}분 {s:.0f}초"


def parse_time(text):
    """'1:02:03.5', '02:03', '75.2' 같은 입력을 ms로 바꾼다. 실패 시 None"""
    t = text.strip().replace(",", ".")
    if not t:
        return None
    try:
        parts = [float(p) for p in t.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(p < 0 for p in parts):
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return int(round(sec * 1000))


def find_ffmpeg():
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


# ================================================================ 아이콘 (직접 그림)
def make_icon(name, color="#1F2937", size=20):
    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size * scale / 24.0, size * scale / 24.0)
    c = QColor(color)
    pen = QPen(c, 2.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def poly(pts, close=False, fill=False):
        path = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(QPointF(*pt))
        if close:
            path.closeSubpath()
        if fill:
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawPath(path)
            p.restore()
        else:
            p.drawPath(path)

    if name == "play":
        poly([(7, 4.5), (19.5, 12), (7, 19.5)], close=True, fill=True)
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 5, 4, 14), 1, 1)
        p.drawRoundedRect(QRectF(14, 5, 4, 14), 1, 1)
    elif name in ("volume", "mute"):
        poly([(3.5, 9), (7.5, 9), (12.5, 4.5), (12.5, 19.5), (7.5, 15), (3.5, 15)], close=True, fill=True)
        if name == "volume":
            p.drawArc(QRectF(9, 8, 7, 8), -55 * 16, 110 * 16)
            p.drawArc(QRectF(8, 4.5, 12.5, 15), -55 * 16, 110 * 16)
        else:
            p.drawLine(QPointF(16, 9), QPointF(21, 15))
            p.drawLine(QPointF(21, 9), QPointF(16, 15))
    elif name == "fullscreen":
        for pts in ([(4, 9), (4, 4), (9, 4)], [(15, 4), (20, 4), (20, 9)],
                    [(20, 15), (20, 20), (15, 20)], [(9, 20), (4, 20), (4, 15)]):
            poly(pts)
    elif name == "exitfull":
        for pts in ([(9, 4), (9, 9), (4, 9)], [(15, 4), (15, 9), (20, 9)],
                    [(20, 15), (15, 15), (15, 20)], [(4, 15), (9, 15), (9, 20)]):
            poly(pts)
    elif name == "pencil":
        poly([(4, 20), (5, 15.5), (15.5, 5), (19, 8.5), (8.5, 19)], close=True)
        p.drawLine(QPointF(13, 7.5), QPointF(16.5, 11))
    elif name == "trash":
        p.drawLine(QPointF(4, 7), QPointF(20, 7))
        poly([(9, 7), (9, 4), (15, 4), (15, 7)])
        poly([(6, 7), (7, 20), (17, 20), (18, 7)])
        p.drawLine(QPointF(10, 11), QPointF(10, 16))
        p.drawLine(QPointF(14, 11), QPointF(14, 16))
    elif name == "folder":
        poly([(3, 7), (3, 19), (21, 19), (21, 9), (11.5, 9), (9.5, 6), (3, 6)], close=True)
    elif name == "gear":
        for k in range(8):
            p.save()
            p.translate(12, 12)
            p.rotate(k * 45)
            p.setPen(QPen(c, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(0, -7), QPointF(0, -9))
            p.restore()
        p.drawEllipse(QPointF(12, 12), 6.5, 6.5)
        p.drawEllipse(QPointF(12, 12), 2.5, 2.5)
    elif name == "plus":
        p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "download":
        p.setPen(QPen(c, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(12, 3.5), QPointF(12, 15))
        poly([(7, 10), (12, 15), (17, 10)])
        poly([(4, 15), (4, 20), (20, 20), (20, 15)])
    elif name == "clock":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        poly([(12, 7.5), (12, 12), (15, 14)])
    elif name == "info":
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(12, 12), 10, 10)
        p.setPen(QPen(QColor("white"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(12, 11), QPointF(12, 17))
        p.drawPoint(QPointF(12, 7.3))
    elif name == "scissors":
        p.setPen(QPen(c, 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(9, 14.5), QPointF(18.5, 3))
        p.drawLine(QPointF(15, 14.5), QPointF(5.5, 3))
        p.setPen(QPen(c, 2.4))
        p.drawEllipse(QPointF(7, 17.5), 3.2, 3.2)
        p.drawEllipse(QPointF(17, 17.5), 3.2, 3.2)
    elif name == "film":
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 2, 2)
        poly([(10, 9), (15, 12), (10, 15)], close=True, fill=True)
    p.end()
    pm.setDevicePixelRatio(scale)
    return QIcon(pm)


def rounded_pixmap(img, w, h, radius=8, bg="#E3E7EE"):
    scale = 2
    pm = QPixmap(w * scale, h * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w * scale, h * scale), radius * scale, radius * scale)
    p.setClipPath(path)
    p.fillRect(QRectF(0, 0, w * scale, h * scale), QColor(bg))
    if img is not None and not img.isNull():
        draw_cover(p, img, QRectF(0, 0, w * scale, h * scale))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def draw_cover(p, img, target):
    """이미지를 비율 유지하며 target을 꽉 채우도록(가운데 잘라서) 그린다."""
    iw, ih = img.width(), img.height()
    if iw <= 0 or ih <= 0 or target.height() <= 0:
        return
    tr = target.width() / target.height()
    ir = iw / ih
    if ir > tr:
        sw, sh = ih * tr, ih
    else:
        sw, sh = iw, iw / tr
    src = QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh)
    p.drawImage(target, img, src)


# ================================================================ 작업 스레드
class CutWorker(QThread):
    progress = Signal(int, int, float)
    file_done = Signal(int, str)
    failed = Signal(str)
    done = Signal(bool)

    def __init__(self, ffmpeg, src, jobs, accurate):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.src = src
        self.jobs = jobs
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
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        cmd += ["-movflags", "+faststart", "-progress", "pipe:1", "-nostats", out]
        return cmd

    def run(self):
        total = len(self.jobs)
        for i, (start, end, out) in enumerate(self.jobs):
            if self._cancel:
                break
            dur = (end - start) / 1000.0
            try:
                self.proc = subprocess.Popen(
                    self.build_cmd(start, end, out),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", creationflags=NO_WINDOW)
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
                self.failed.emit(f"{os.path.basename(out)} 저장 중 오류가 발생했습니다.\n\n" + "\n".join(tail))
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


class ThumbWorker(QThread):
    """지정한 시간들의 장면을 작은 이미지로 뽑아온다."""
    ready = Signal(object, QImage)

    def __init__(self, ffmpeg, src, jobs, height=120):
        super().__init__()
        self.ffmpeg = ffmpeg
        self.src = src
        self.jobs = jobs          # [(key, ms), ...]
        self.height = height
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        tmp = tempfile.mkdtemp(prefix="quicksplit_")
        try:
            for n, (key, ms) in enumerate(self.jobs):
                if self._stop:
                    break
                out = os.path.join(tmp, f"{n}.jpg")
                cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                       "-ss", f"{max(0, ms) / 1000.0:.3f}", "-i", self.src,
                       "-frames:v", "1", "-vf", f"scale=-2:{self.height}", "-q:v", "4", out]
                try:
                    subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=30)
                except Exception:
                    continue
                img = QImage(out)
                if not img.isNull() and not self._stop:
                    self.ready.emit(key, img)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ================================================================ 위젯들
class RoundedFrame(QFrame):
    """모서리가 둥글게 잘리는 영역 (영상 화면용)"""
    def __init__(self, radius=14):
        super().__init__()
        self.radius = radius

    def resizeEvent(self, e):
        super().resizeEvent(e)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class VideoView(QGraphicsView):
    fileDropped = Signal(str)
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.item = QGraphicsVideoItem()
        self._scene.addItem(self.item)
        self.hint = self._scene.addText("영상을 여기에 끌어다 놓거나\n'영상 열기'를 눌러 주세요")
        f = QFont()
        f.setPointSize(16)
        self.hint.setFont(f)
        self.hint.setDefaultTextColor(QColor("#8B95A7"))
        self.setBackgroundBrush(QColor("#0E131C"))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumHeight(160)

    def show_hint(self, on):
        self.hint.setVisible(on)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.viewport().width(), self.viewport().height()
        self._scene.setSceneRect(0, 0, w, h)
        self.item.setPos(0, 0)
        self.item.setSize(QSizeF(w, h))
        br = self.hint.boundingRect()
        self.hint.setPos((w - br.width()) / 2, (h - br.height()) / 2)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                e.acceptProposedAction()
                self.fileDropped.emit(p)
                return


class ClickSlider(QSlider):
    """클릭한 위치로 바로 이동하는 슬라이더"""
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > self.minimum():
            x = e.position().x()
            w = max(1, self.width())
            val = self.minimum() + int((self.maximum() - self.minimum()) * x / w)
            self.setValue(val)
            self.sliderMoved.emit(val)
        super().mousePressEvent(e)


class Timeline(QWidget):
    """썸네일 필름 + 구간 막대 + 시간 눈금"""
    seekRequested = Signal(int)
    segmentClicked = Signal(int)
    segmentSelected = Signal(int)
    segmentEdited = Signal(int, int, int, bool)

    M = 16
    STRIP_Y = 36
    STRIP_H = 56
    LANE_TOP = 10
    LANE_H = 22
    LANE_SP = 8
    RULER_H = 28
    HANDLE_R = 10
    MIN_LEN = 100
    N_THUMBS = 12
    TICK_STEPS = [1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000,
                  600000, 900000, 1800000, 3600000, 7200000]

    def __init__(self):
        super().__init__()
        self.duration = 0
        self.position = 0
        self.segments = []
        self.lanes = []
        self.n_lanes = 0
        self.mark_start = None
        self.mark_end = None
        self.selected = -1
        self.dragging = False
        self.edit = None
        self.thumbs = [None] * self.N_THUMBS
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._update_height()

    # ---- 배치
    def _lanes_bottom(self):
        return self.STRIP_Y + self.STRIP_H + self.LANE_TOP + max(1, self.n_lanes) * (self.LANE_H + self.LANE_SP)

    def _update_height(self):
        self.setFixedHeight(self._lanes_bottom() + self.RULER_H)

    def reset_thumbs(self):
        self.thumbs = [None] * self.N_THUMBS
        self.update()

    def set_thumb(self, i, img):
        if 0 <= i < self.N_THUMBS:
            self.thumbs[i] = img
            self.update()

    def set_segments(self, segs):
        self.segments = [tuple(x) for x in segs]
        self.lanes = [0] * len(segs)
        lane_end = []
        for i in sorted(range(len(segs)), key=lambda k: (segs[k][0], segs[k][1])):
            st, en = segs[i]
            for li, le in enumerate(lane_end):
                if st >= le:
                    lane_end[li] = en
                    self.lanes[i] = li
                    break
            else:
                lane_end.append(en)
                self.lanes[i] = len(lane_end) - 1
        self.n_lanes = len(lane_end)
        if self.selected >= len(segs):
            self.selected = -1
        self._update_height()
        self.update()

    def _x(self, ms):
        w = self.width() - 2 * self.M
        return self.M + (ms / self.duration * w if self.duration > 0 else 0)

    def _ms(self, x):
        w = max(1, self.width() - 2 * self.M)
        return int(min(max(0.0, (x - self.M) / w), 1.0) * self.duration)

    def _lane_cy(self, lane):
        return self.STRIP_Y + self.STRIP_H + self.LANE_TOP + lane * (self.LANE_H + self.LANE_SP) + self.LANE_H / 2

    def _bar_rect(self, i):
        st, en = self.segments[i]
        x1 = self._x(st)
        x2 = max(self._x(en), x1 + 2)
        cy = self._lane_cy(self.lanes[i])
        return QRectF(x1, cy - self.LANE_H / 2, x2 - x1, self.LANE_H)

    # ---- 그리기
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w = self.width()
        strip = QRectF(self.M, self.STRIP_Y, w - 2 * self.M, self.STRIP_H)
        strip_path = QPainterPath()
        strip_path.addRoundedRect(strip, 8, 8)

        # 썸네일 필름
        p.save()
        p.setClipPath(strip_path)
        p.fillRect(strip, QColor("#DCE1E9"))
        if self.duration > 0:
            sw = strip.width() / self.N_THUMBS
            for k, img in enumerate(self.thumbs):
                slot = QRectF(strip.left() + k * sw, strip.top(), sw + 0.5, strip.height())
                if img is not None:
                    draw_cover(p, img, slot)
                if k > 0:
                    p.setPen(QPen(QColor(255, 255, 255, 140), 1))
                    p.drawLine(QPointF(slot.left(), slot.top()), QPointF(slot.left(), slot.bottom()))
            # 구간 영역 색 덮기
            for i, (st, en) in enumerate(self.segments):
                c = QColor(SEG_COLORS[i % len(SEG_COLORS)])
                c.setAlpha(90 if i == self.selected else 45)
                p.fillRect(QRectF(self._x(st), strip.top(), max(2.0, self._x(en) - self._x(st)), strip.height()), c)
            # 지정 중인 구간
            if self.mark_start is not None:
                end = self.mark_end if self.mark_end is not None else max(self.position, self.mark_start)
                x1 = self._x(self.mark_start)
                r = QRectF(x1, strip.top() + 1, max(2.0, self._x(end) - x1), strip.height() - 2)
                p.fillRect(r, QColor(250, 204, 21, 80))
                pen = QPen(QColor("#E0A100"), 2, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
        else:
            p.setPen(QColor("#8B95A7"))
            p.drawText(strip, Qt.AlignCenter, "영상을 불러오면 장면 미리보기가 표시됩니다")
        p.restore()
        p.setPen(QPen(QColor("#D3D9E3"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(strip_path)

        # 필름 위 구간 번호 배지
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(10.5)
        if self.duration > 0:
            for i, (st, _en) in enumerate(self.segments):
                c = QColor(SEG_COLORS[i % len(SEG_COLORS)])
                bx = self._x(st) + 4
                badge = QRectF(bx, strip.top() + 4, 24, 22)
                p.setPen(QPen(QColor("white"), 1.5))
                p.setBrush(c)
                p.drawRoundedRect(badge, 6, 6)
                p.setFont(f)
                p.setPen(QColor("white"))
                p.drawText(badge, Qt.AlignCenter, str(i + 1))

        # 구간 막대
        for i in range(len(self.segments)):
            c = QColor(SEG_COLORS[i % len(SEG_COLORS)])
            sel = i == self.selected
            r = self._bar_rect(i)
            cy = r.center().y()
            if sel:
                guide = QColor(c)
                guide.setAlpha(150)
                p.setPen(QPen(guide, 1.5))
                p.drawLine(QPointF(r.left(), strip.bottom()), QPointF(r.left(), cy))
                p.drawLine(QPointF(r.right(), strip.bottom()), QPointF(r.right(), cy))
            bar = QColor(c)
            bar.setAlpha(235 if sel else 150)
            p.setPen(Qt.NoPen)
            p.setBrush(bar)
            p.drawRoundedRect(r, self.LANE_H / 2, self.LANE_H / 2)
            p.setFont(f)
            if r.width() > 2 * self.HANDLE_R + 22:
                p.setPen(QColor("white"))
                p.drawText(r, Qt.AlignCenter, str(i + 1))
            else:
                # 막대가 짧으면 번호를 오른쪽 바깥에 표시
                p.setPen(c.darker(120))
                p.drawText(QRectF(r.right() + self.HANDLE_R + 3, r.top() - 2, 30, r.height() + 4),
                           Qt.AlignVCenter | Qt.AlignLeft, str(i + 1))
            for hx in (r.left(), r.right()):
                p.setBrush(QColor("white"))
                p.setPen(QPen(c, 3 if sel else 2.5))
                p.drawEllipse(QPointF(hx, cy), self.HANDLE_R - 1.5, self.HANDLE_R - 1.5)

        # 시간 눈금
        self._draw_ruler(p)

        # 현재 위치
        if self.duration > 0:
            x = self._x(self.position)
            p.setPen(QPen(QColor("#111827"), 2))
            p.drawLine(QPointF(x, self.STRIP_Y - 4), QPointF(x, self._lanes_bottom() - 2))
            text = fmt_t1(self.position)
            bf = QFont(self.font())
            bf.setPointSizeF(10.5)
            bf.setBold(True)
            p.setFont(bf)
            fm = QFontMetrics(bf)
            bw = fm.horizontalAdvance(text) + 18
            bx = min(max(0.0, x - bw / 2), w - bw)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#1F2937"))
            p.drawRoundedRect(QRectF(bx, 2, bw, 25), 6, 6)
            tri = QPolygonF([QPointF(x - 6, 26), QPointF(x + 6, 26), QPointF(x, 33)])
            p.drawPolygon(tri)
            p.setPen(QColor("white"))
            p.drawText(QRectF(bx, 2, bw, 25), Qt.AlignCenter, text)

    def _draw_ruler(self, p):
        w = self.width() - 2 * self.M
        y = self._lanes_bottom()
        if self.duration <= 0 or w <= 0:
            return
        ppm = w / self.duration
        step = next((s for s in self.TICK_STEPS if s * ppm >= 110), self.TICK_STEPS[-1])
        minor = step / 5
        p.setPen(QPen(QColor("#C3CAD5"), 1))
        t = 0.0
        while t <= self.duration + 1:
            x = self._x(t)
            p.drawLine(QPointF(x, y), QPointF(x, y + 3))
            t += minor
        f = QFont(self.font())
        f.setPointSizeF(10)
        p.setFont(f)
        t = 0
        while t <= self.duration:
            x = self._x(t)
            p.setPen(QPen(QColor("#9AA3B2"), 1))
            p.drawLine(QPointF(x, y), QPointF(x, y + 6))
            lw = 84
            lx = min(max(0.0, x - lw / 2), self.width() - lw)
            p.setPen(QColor("#4B5563"))
            p.drawText(QRectF(lx, y + 7, lw, 20), Qt.AlignCenter, fmt_hms(t))
            t += step

    # ---- 마우스
    def _hit_handle(self, pos):
        best = None
        for i in reversed(range(len(self.segments))):
            r = self._bar_rect(i)
            cy = r.center().y()
            for side, hx in (("start", r.left()), ("end", r.right())):
                d = ((pos.x() - hx) ** 2 + (pos.y() - cy) ** 2) ** 0.5
                if d <= self.HANDLE_R + 4 and (best is None or d < best[2]):
                    best = (i, side, d)
        return (best[0], best[1]) if best else None

    def _hit_bar(self, pos):
        for i in reversed(range(len(self.segments))):
            if self._bar_rect(i).adjusted(0, -3, 0, 3).contains(pos):
                return i
        return -1

    def _seek(self, x):
        ms = self._ms(x)
        self.position = ms
        self.update()
        self.seekRequested.emit(ms)

    def _drag_edge(self, x, final):
        i, side = self.edit
        st, en = self.segments[i]
        ms = self._ms(x)
        if side == "start":
            st = max(0, min(ms, en - self.MIN_LEN))
            edge = st
        else:
            en = min(self.duration, max(ms, st + self.MIN_LEN))
            edge = en
        self.segments[i] = (st, en)
        self.position = edge
        self.update()
        self.seekRequested.emit(edge)
        self.segmentEdited.emit(i, st, en, final)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or self.duration <= 0:
            return
        pos = e.position()
        h = self._hit_handle(pos)
        if h:
            self.edit = h
            self.segmentSelected.emit(h[0])
            self._drag_edge(pos.x(), False)
            return
        i = self._hit_bar(pos)
        if i >= 0:
            self.segmentClicked.emit(i)
            return
        self.dragging = True
        self._seek(pos.x())

    def mouseMoveEvent(self, e):
        pos = e.position()
        gp = e.globalPosition().toPoint()
        if self.edit:
            self._drag_edge(pos.x(), False)
            i, _side = self.edit
            st, en = self.segments[i]
            QToolTip.showText(gp, f"구간 {i + 1}   {fmt_t1(st)} ~ {fmt_t1(en)}\n길이 {fmt_len(en - st)}", self)
            return
        if self.dragging:
            self._seek(pos.x())
        if self.duration > 0:
            h = self._hit_handle(pos)
            self.setCursor(Qt.SizeHorCursor if h else Qt.PointingHandCursor)
            if h:
                tip = f"구간 {h[0] + 1}의 {'시작' if h[1] == 'start' else '끝'} — 좌우로 끌어서 조절"
            else:
                i = self._hit_bar(pos)
                if i >= 0:
                    st, en = self.segments[i]
                    tip = f"구간 {i + 1}   {fmt_t1(st)} ~ {fmt_t1(en)}"
                else:
                    tip = fmt_t1(self._ms(pos.x()))
            QToolTip.showText(gp, tip, self)

    def mouseReleaseEvent(self, e):
        if self.edit:
            self._drag_edge(e.position().x(), True)
            self.edit = None
            return
        if self.dragging:
            self.dragging = False
            self._seek(e.position().x())

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)


class SegmentCard(QFrame):
    clicked = Signal(int)
    playClicked = Signal(int)
    editClicked = Signal(int)
    deleteClicked = Signal(int)

    TW, TH = 96, 66

    def __init__(self, idx):
        super().__init__()
        self.idx = idx
        self.color = QColor(SEG_COLORS[idx % len(SEG_COLORS)])
        self.img = None
        self.setObjectName("segCard")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 6, 10)
        lay.setSpacing(10)

        self.thumb = QLabel()
        self.thumb.setFixedSize(self.TW, self.TH)
        lay.addWidget(self.thumb)

        info = QGridLayout()
        info.setHorizontalSpacing(8)
        info.setVerticalSpacing(1)
        self.l_start = QLabel()
        self.l_start.setObjectName("segRange")
        self.l_end = QLabel()
        self.l_end.setObjectName("segRange")
        self.length = QLabel()
        self.length.setObjectName("segLen")
        info.setRowStretch(0, 1)
        info.addWidget(label("시작", "segLen"), 1, 0)
        info.addWidget(self.l_start, 1, 1)
        info.addWidget(label("끝", "segLen"), 2, 0)
        info.addWidget(self.l_end, 2, 1)
        info.addWidget(self.length, 3, 0, 1, 2)
        info.setRowStretch(4, 1)
        info.setColumnStretch(1, 1)
        lay.addLayout(info, 1)

        for icon, sig, tip in (("play", self.playClicked, "이 구간 미리보기"),
                               ("pencil", self.editClicked, "시간 직접 수정"),
                               ("trash", self.deleteClicked, "삭제")):
            b = QPushButton()
            b.setObjectName("iconBtn")
            b.setIcon(make_icon(icon, "#1F2937", 22))
            b.setIconSize(QSize(22, 22))
            b.setFixedSize(38, 38)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, s=sig: s.emit(self.idx))
            lay.addWidget(b)
        self.selected = False
        self._draw_thumb()
        self._apply_style()

    def _draw_thumb(self):
        pm = rounded_pixmap(self.img, self.TW, self.TH)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        badge = QRectF(4, 4, 30, 28)
        p.setPen(QPen(QColor("white"), 1.5))
        p.setBrush(self.color)
        p.drawRoundedRect(badge, 7, 7)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(13)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(badge, Qt.AlignCenter, str(self.idx + 1))
        p.end()
        self.thumb.setPixmap(pm)

    def set_times(self, st, en):
        self.l_start.setText(fmt_t1(st))
        self.l_end.setText(fmt_t1(en))
        self.length.setText(f"길이 {fmt_len(en - st)}")

    def set_thumb(self, img):
        self.img = img
        self._draw_thumb()

    def set_selected(self, sel):
        if sel != self.selected:
            self.selected = sel
            self._apply_style()

    def _apply_style(self):
        c = self.color
        r, g, b = c.red(), c.green(), c.blue()
        if self.selected:
            self.setStyleSheet(
                f"#segCard{{background:rgba({r},{g},{b},28);border:2px solid rgba({r},{g},{b},170);border-radius:12px;}}")
            col = f"color:{c.darker(130).name()};"
        else:
            self.setStyleSheet(
                "#segCard{background:#F8F9FB;border:1px solid #E6E9EF;border-radius:12px;}"
                "#segCard:hover{background:#F1F3F7;}")
            col = ""
        self.l_start.setStyleSheet(col)
        self.l_end.setStyleSheet(col)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.idx)


class SegmentDialog(QDialog):
    def __init__(self, parent, idx, st, en, duration):
        super().__init__(parent)
        self.setWindowTitle(f"구간 {idx + 1} 시간 수정")
        self.duration = duration
        self.result_times = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        hint = QLabel("시:분:초 형식으로 입력하세요. (예: 00:01:23.5)")
        hint.setObjectName("segLen")
        lay.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.ed_s = QLineEdit(fmt_ms(st))
        self.ed_e = QLineEdit(fmt_ms(en))
        for row, (txt, ed) in enumerate((("시작", self.ed_s), ("끝", self.ed_e))):
            lb = QLabel(txt)
            lb.setObjectName("fieldLabel")
            ed.addAction(make_icon("clock", "#6B7280", 18), QLineEdit.ActionPosition.LeadingPosition)
            ed.setMinimumWidth(220)
            grid.addWidget(lb, row, 0)
            grid.addWidget(ed, row, 1)
        lay.addLayout(grid)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color:{RED};")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        st = parse_time(self.ed_s.text())
        en = parse_time(self.ed_e.text())
        if st is None or en is None:
            self.err.setText("시간 형식이 올바르지 않습니다.")
            return
        if self.duration > 0:
            st = min(st, self.duration)
            en = min(en, self.duration)
        if en - st < 100:
            self.err.setText("끝은 시작보다 0.1초 이상 뒤여야 합니다.")
            return
        self.result_times = (st, en)
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, parent, accurate):
        super().__init__(parent)
        self.setWindowTitle("설정")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        self.chk = QCheckBox("정확하게 자르기 (권장)")
        self.chk.setChecked(accurate)
        lay.addWidget(self.chk)
        d = QLabel("켜짐: 지정한 시간에 정확히 잘립니다. 다시 압축하므로 조금 느립니다.\n"
                   "꺼짐: 원본을 그대로 복사해 매우 빠르지만, 시작·끝이 1~수 초 어긋날 수 있습니다.")
        d.setObjectName("segLen")
        lay.addWidget(d)
        lay.addSpacing(8)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ================================================================ 스타일
QSS = f"""
#root {{ background:#F3F5F9; }}
#header {{ background:#FFFFFF; border-bottom:1px solid #E6E9EF; }}
#appTitle {{ font-size:27px; font-weight:bold; color:#111827; }}
#appSub {{ color:#6B7280; font-size:16px; }}
QFrame#card {{ background:#FFFFFF; border:1px solid #E6E9EF; border-radius:14px; }}
#cardTitle {{ font-size:17px; font-weight:bold; color:#374151; }}
#panelTitle {{ font-size:21px; font-weight:bold; color:#111827; }}
QPushButton {{ background:#FFFFFF; border:1px solid #D7DCE5; border-radius:10px;
              padding:9px 16px; color:#1F2937; font-size:16px; }}
QPushButton:hover {{ background:#F4F6FA; }}
QPushButton:pressed {{ background:#E9EDF4; }}
QPushButton:disabled {{ color:#A3AAB7; background:#F7F8FA; }}
QPushButton#primary {{ background:{ACCENT}; border:none; color:white; font-size:21px;
                      font-weight:bold; border-radius:12px; padding:8px 22px; }}
QPushButton#primary:hover {{ background:#1A60D8; }}
QPushButton#primary:disabled {{ background:#A9C4F5; }}
QPushButton#startBtn {{ background:#EAF1FE; border:1px solid #C7D9FC; color:{ACCENT}; font-size:17px; font-weight:bold; }}
QPushButton#startBtn:hover {{ background:#DDE9FD; }}
QPushButton#endBtn {{ background:#FDEDF1; border:1px solid #F8CAD5; color:{RED}; font-size:17px; font-weight:bold; }}
QPushButton#endBtn:hover {{ background:#FBE0E7; }}
QPushButton#navBtn {{ font-size:17px; font-weight:bold; padding:8px 14px; min-height:28px; }}
QPushButton#playBtn {{ font-size:18px; font-weight:bold; padding:8px 24px; min-height:28px;
                      background:#1F2937; color:white; border:none; }}
QPushButton#playBtn:hover {{ background:#374151; }}
QPushButton#playBtn:disabled {{ background:#C5CAD3; }}
QPushButton#iconBtn {{ background:transparent; border:none; padding:6px; border-radius:8px; }}
QPushButton#iconBtn:hover {{ background:rgba(17,24,39,0.08); }}
QPushButton#saveBtn {{ background:{ACCENT}; border:none; border-radius:14px; }}
QPushButton#saveBtn:hover {{ background:#1A60D8; }}
QPushButton#saveBtn[busy="true"] {{ background:#0E4DBA; }}
#saveTitle {{ color:white; font-size:24px; font-weight:bold; }}
#saveSub {{ color:#DCE8FF; font-size:15px; }}
QLineEdit, QComboBox {{ background:#FFFFFF; border:1px solid #D7DCE5; border-radius:10px;
                       padding:8px 10px; font-size:17px; color:#1F2937; }}
QLineEdit:focus, QComboBox:focus {{ border:1px solid {ACCENT}; }}
QLineEdit[readOnly="true"] {{ background:#F7F8FA; }}
QComboBox::drop-down {{ border:none; width:32px; }}
QComboBox QAbstractItemView {{ background:white; selection-background-color:#EAF1FE;
                              selection-color:#111827; border:1px solid #D7DCE5; font-size:16px; }}
#fieldLabel {{ color:#374151; font-size:17px; font-weight:bold; }}
#videoFrame {{ background:#0E131C; }}
#ctrlBar {{ background:#151B26; }}
#ctrlBar QLabel {{ color:#FFFFFF; font-size:16px; }}
#ctrlBar QPushButton {{ background:transparent; border:none; border-radius:8px; padding:6px; }}
#ctrlBar QPushButton:hover {{ background:rgba(255,255,255,0.12); }}
#ctrlBar QSlider::groove:horizontal {{ height:6px; background:#3A4354; border-radius:3px; }}
#ctrlBar QSlider::sub-page:horizontal {{ background:#3B82F6; border-radius:3px; }}
#ctrlBar QSlider::handle:horizontal {{ background:#FFFFFF; width:18px; height:18px;
                                      margin:-6px 0; border-radius:9px; }}
#infoBox {{ background:#F2F5FA; border-radius:12px; }}
#infoTitle {{ color:#1E3A6E; font-size:17px; font-weight:bold; }}
#infoText {{ color:#4B5563; font-size:15px; }}
#segNum {{ font-size:26px; font-weight:bold; }}
#segRange {{ font-size:17px; font-weight:bold; color:#111827; }}
#segLen {{ font-size:15px; color:#4B5563; }}
#emptyText {{ color:#9CA3AF; font-size:17px; }}
#segViewport, #segContainer {{ background:transparent; }}
QToolTip {{ background:#1F2937; color:#FFFFFF; border:none; padding:7px 9px; font-size:15px; }}
QScrollBar:vertical {{ width:10px; background:transparent; margin:2px; }}
QScrollBar::handle:vertical {{ background:#D5DAE3; border-radius:5px; min-height:30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
QCheckBox {{ font-size:17px; }}
QDialog {{ background:#FFFFFF; }}
QDialog QLabel {{ font-size:16px; }}
QMessageBox QLabel {{ font-size:16px; }}
"""


def label(text, obj=None):
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    return lb


# ================================================================ 메인 창
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - 영상 구간 추출기")
        self.setWindowIcon(make_icon("scissors", ACCENT, 64))
        self.resize(1480, 980)
        self.setMinimumSize(1100, 700)
        self.setAcceptDrops(True)

        self.src_path = None
        self.out_dir = None
        self.duration = 0
        self.mark_start = None
        self.mark_end = None
        self.segments = []
        self.sel = -1
        self.preview_end = None
        self.worker = None
        self.accurate = True
        self.ffmpeg = find_ffmpeg()
        self.gen = 0
        self.strip_gen = -1
        self.thumb_workers = []
        self.seg_thumbs = {}
        self.seg_pending = set()
        self.cards = []
        self._err_shown = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.errorOccurred.connect(self.on_player_error)
        self.player.mediaStatusChanged.connect(self.on_media_status)

        self._build_ui()
        self._update_marks()
        self._refresh_segments()
        self._set_enabled()

    # ---------------------------------------------------------- UI
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root.setFocusPolicy(Qt.ClickFocus)
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_header())

        body = QGridLayout()
        body.setContentsMargins(16, 14, 16, 14)
        body.setHorizontalSpacing(16)
        body.setVerticalSpacing(12)
        body.addWidget(self._build_left(), 0, 0)
        right = self._build_right()
        body.addWidget(right, 0, 1)
        body.addWidget(self._build_bottom(), 1, 0)
        body.addWidget(self._build_save_button(), 1, 1)
        body.setColumnStretch(0, 1)
        body.setRowStretch(0, 1)
        rl.addLayout(body, 1)
        self.setCentralWidget(root)

    def _build_header(self):
        h = QFrame()
        h.setObjectName("header")
        h.setFixedHeight(66)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(22, 0, 18, 0)
        lay.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(make_icon("scissors", ACCENT, 38).pixmap(38, 38))
        lay.addWidget(logo)
        lay.addWidget(label(APP_NAME, "appTitle"))
        lay.addSpacing(8)
        lay.addWidget(label("원하는 구간만 쉽게 추출하는 영상 구간 추출기", "appSub"))
        lay.addStretch(1)
        self.btn_open = self._btn("영상 열기", self.open_file, "folder", tip="Ctrl+O · 영상을 화면에 끌어다 놓아도 됩니다")
        self.btn_settings = self._btn("설정", self.open_settings, "gear")
        lay.addWidget(self.btn_open)
        lay.addWidget(self.btn_settings)
        return h

    def _btn(self, text, slot, icon=None, obj=None, tip=None, icon_color="#1F2937", icon_size=18):
        b = QPushButton(text)
        if obj:
            b.setObjectName(obj)
        if icon:
            b.setIcon(make_icon(icon, icon_color, icon_size))
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        if tip:
            b.setToolTip(tip)
        return b

    def _icon_btn(self, icon, slot, color="#FFFFFF", size=22, tip=None):
        b = QPushButton()
        b.setIcon(make_icon(icon, color, size))
        b.setIconSize(QSize(size, size))
        b.setFocusPolicy(Qt.NoFocus)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        if tip:
            b.setToolTip(tip)
        return b

    def _build_left(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # 영상 + 조작 바
        vf = RoundedFrame(14)
        vf.setObjectName("videoFrame")
        vl = QVBoxLayout(vf)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        self.view = VideoView()
        self.view.fileDropped.connect(self.load)
        self.view.clicked.connect(self.toggle_play)
        self.player.setVideoOutput(self.view.item)
        vl.addWidget(self.view, 1)

        bar = QFrame()
        bar.setObjectName("ctrlBar")
        bar.setFixedHeight(56)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 0, 14, 0)
        bl.setSpacing(10)
        self.btn_play = self._icon_btn("play", self.toggle_play, tip="재생 / 일시정지 (Space)")
        bl.addWidget(self.btn_play)
        self.lbl_time = QLabel("00:00:00 / 00:00:00")
        self.lbl_time.setMinimumWidth(180)
        bl.addWidget(self.lbl_time)
        self.seek = ClickSlider(Qt.Horizontal)
        self.seek.setFocusPolicy(Qt.NoFocus)
        self.seek.sliderMoved.connect(self.player.setPosition)
        bl.addWidget(self.seek, 1)
        bl.addSpacing(10)
        self.btn_mute = self._icon_btn("volume", self.toggle_mute, tip="소리 켜기 / 끄기")
        bl.addWidget(self.btn_mute)
        self.vol = ClickSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(120)
        self.vol.setFocusPolicy(Qt.NoFocus)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        bl.addWidget(self.vol)
        self.btn_full = self._icon_btn("fullscreen", self.toggle_fullscreen, tip="전체 화면 (Esc로 나가기)")
        bl.addWidget(self.btn_full)
        vl.addWidget(bar)
        lay.addWidget(vf, 1)

        # 큰 재생 버튼 줄
        nav = QHBoxLayout()
        nav.setSpacing(10)
        nav.addStretch(1)
        self.btn_b5 = self._btn("◀◀  5초 뒤로", lambda: self.seek_rel(-5000), obj="navBtn", tip="Shift + ←")
        self.btn_b1 = self._btn("◀  1초 뒤로", lambda: self.seek_rel(-1000), obj="navBtn", tip="←")
        self.btn_play2 = self._btn("  재생", self.toggle_play, "play", "playBtn",
                                   tip="Space", icon_color="#FFFFFF", icon_size=22)
        self.btn_play2.setMinimumWidth(150)
        self.btn_f1 = self._btn("1초 앞으로  ▶", lambda: self.seek_rel(1000), obj="navBtn", tip="→")
        self.btn_f5 = self._btn("5초 앞으로  ▶▶", lambda: self.seek_rel(5000), obj="navBtn", tip="Shift + →")
        for b in (self.btn_b5, self.btn_b1, self.btn_play2, self.btn_f1, self.btn_f5):
            nav.addWidget(b)
        nav.addStretch(1)
        lay.addLayout(nav)

        # 타임라인
        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.player.setPosition)
        self.timeline.segmentClicked.connect(self.on_timeline_segment)
        self.timeline.segmentSelected.connect(self.select_segment)
        self.timeline.segmentEdited.connect(self.on_segment_edited)
        lay.addWidget(self.timeline)

        # 시작점 / 끝점 / 추가
        row = QHBoxLayout()
        row.setSpacing(12)
        self.ed_start, self.btn_start, c1 = self._mark_card("구간 시작점", "현재 위치를 시작점으로", "startBtn", self.set_start, True)
        self.ed_end, self.btn_end, c2 = self._mark_card("구간 끝점", "현재 위치를 끝점으로", "endBtn", self.set_end, False)
        row.addWidget(c1, 1)
        row.addWidget(c2, 1)
        self.btn_add = self._btn("  이 구간 추가", self.add_segment, "plus", "primary",
                                 tip="Enter", icon_color="#FFFFFF", icon_size=22)
        self.btn_add.setMinimumWidth(170)
        self.btn_add.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        row.addWidget(self.btn_add)
        lay.addLayout(row)
        return w

    def _mark_card(self, title, btn_text, obj, slot, is_start):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 12)
        cl.setSpacing(8)
        r = QHBoxLayout()
        r.setSpacing(10)
        r.addWidget(label(title, "cardTitle"))
        r.addStretch(1)
        ed = QLineEdit()
        ed.setPlaceholderText("--:--:--.---")
        ed.addAction(make_icon("clock", "#4B5563", 20), QLineEdit.ActionPosition.LeadingPosition)
        ed.setFixedWidth(178)
        ed.setToolTip("직접 입력도 가능합니다 (예: 00:01:23.5)")
        ed.editingFinished.connect(lambda e=ed, s=is_start: self.on_time_typed(e, s))
        ed.returnPressed.connect(ed.clearFocus)
        r.addWidget(ed)
        cl.addLayout(r)
        b = self._btn(btn_text, slot, obj=obj, tip="단축키 I" if is_start else "단축키 O")
        b.setMinimumHeight(44)
        cl.addWidget(b)
        return ed, b, card

    def _build_right(self):
        panel = QFrame()
        panel.setObjectName("card")
        panel.setFixedWidth(480)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)
        top = QHBoxLayout()
        self.lbl_list = label("추출할 구간 목록 (총 0개)", "panelTitle")
        top.addWidget(self.lbl_list)
        top.addStretch(1)
        self.btn_clear = self._btn("전체 삭제", self.clear_segments, "trash")
        top.addWidget(self.btn_clear)
        lay.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.viewport().setObjectName("segViewport")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cont = QWidget()
        cont.setObjectName("segContainer")
        self.seg_layout = QVBoxLayout(cont)
        self.seg_layout.setContentsMargins(0, 0, 4, 0)
        self.seg_layout.setSpacing(10)
        self.empty_lbl = label("아직 추가한 구간이 없습니다.\n\n시작점과 끝점을 지정한 뒤\n'이 구간 추가'를 눌러 주세요.", "emptyText")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.seg_layout.addWidget(self.empty_lbl)
        self.seg_layout.addStretch(1)
        self.scroll.setWidget(cont)
        lay.addWidget(self.scroll, 1)

        info = QFrame()
        info.setObjectName("infoBox")
        il = QHBoxLayout(info)
        il.setContentsMargins(16, 14, 16, 14)
        il.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(make_icon("info", ACCENT, 22).pixmap(22, 22))
        ic.setAlignment(Qt.AlignTop)
        il.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(6)
        tv.addWidget(label("구간이 서로 겹쳐도 각각 저장됩니다.", "infoTitle"))
        t2 = label("원하는 구간을 자유롭게 지정하여 여러 개의 영상으로 추출할 수 있습니다.\n"
                   "단축키: Space 재생 · I 시작점 · O 끝점 · Enter 추가\n← → 1초 이동 (Shift 5초, Ctrl 0.1초)",
                   "infoText")
        t2.setWordWrap(True)
        tv.addWidget(t2)
        il.addLayout(tv, 1)
        lay.addWidget(info)
        return panel

    def _build_bottom(self):
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(20, 14, 20, 14)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.addWidget(label("저장 폴더", "fieldLabel"), 0, 0)
        self.ed_out = QLineEdit()
        self.ed_out.setReadOnly(True)
        self.ed_out.setFocusPolicy(Qt.NoFocus)
        self.ed_out.setPlaceholderText("영상을 열면 원본과 같은 폴더로 지정됩니다")
        g.addWidget(self.ed_out, 0, 1)
        self.btn_outdir = self._btn("폴더 선택", self.choose_outdir, "folder")
        g.addWidget(self.btn_outdir, 0, 2)
        g.addWidget(label("파일 이름 형식", "fieldLabel"), 1, 0)
        self.cmb_name = QComboBox()
        self.cmb_name.addItems(["원본파일명_구간번호    (예: 여행영상_01.mp4)",
                                "원본파일명_구간번호_시작시간    (예: 여행영상_01_0h00m09s.mp4)"])
        self.cmb_name.setFocusPolicy(Qt.NoFocus)
        self.cmb_name.setCursor(Qt.PointingHandCursor)
        g.addWidget(self.cmb_name, 1, 1)
        g.setColumnStretch(1, 1)
        return card

    def _build_save_button(self):
        b = QPushButton()
        b.setObjectName("saveBtn")
        b.setFixedWidth(480)
        b.setMinimumHeight(96)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(self.save_all)
        lay = QHBoxLayout(b)
        lay.setContentsMargins(24, 10, 24, 10)
        lay.setSpacing(18)
        lay.addStretch(1)
        ic = QLabel()
        ic.setPixmap(make_icon("download", "#FFFFFF", 44).pixmap(44, 44))
        lay.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(4)
        self.save_title = label("모든 구간 각각 저장", "saveTitle")
        self.save_sub = label("(추가한 구간을 개별 MP4 파일로 저장)", "saveSub")
        tv.addWidget(self.save_title)
        tv.addWidget(self.save_sub)
        lay.addLayout(tv)
        lay.addStretch(1)
        for wdg in (ic, self.save_title, self.save_sub):
            wdg.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.btn_save = b
        return b

    # ---------------------------------------------------------- 상태
    def _set_enabled(self):
        loaded = self.src_path is not None
        busy = self.worker is not None
        en = loaded and not busy
        for w in (self.btn_play, self.btn_play2, self.btn_b5, self.btn_b1, self.btn_f1, self.btn_f5,
                  self.seek, self.timeline, self.ed_start, self.ed_end,
                  self.btn_start, self.btn_end, self.btn_add, self.btn_clear,
                  self.btn_outdir, self.cmb_name):
            w.setEnabled(en)
        self.btn_settings.setEnabled(not busy)
        for c in self.cards:
            c.setEnabled(not busy)
        self.btn_open.setEnabled(not busy)
        self.btn_save.setProperty("busy", "true" if busy else "false")
        self.btn_save.style().unpolish(self.btn_save)
        self.btn_save.style().polish(self.btn_save)
        if not busy:
            self.save_title.setText("모든 구간 각각 저장")
            self.save_sub.setText("(추가한 구간을 개별 MP4 파일로 저장)")

    # ---------------------------------------------------------- 키보드
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and QApplication.activeWindow() is self:
            fw = QApplication.focusWidget()
            if not isinstance(fw, (QLineEdit, QComboBox)) and self.handle_key(ev):
                return True
        return super().eventFilter(obj, ev)

    def handle_key(self, ev):
        k = ev.key()
        mods = ev.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if ctrl and k == Qt.Key_O:
            self.open_file()
        elif k == Qt.Key_Space:
            self.toggle_play()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            d = 5000 if shift else (100 if ctrl else 1000)
            self.seek_rel(-d if k == Qt.Key_Left else d)
        elif k == Qt.Key_I and not ctrl:
            self.set_start()
        elif k == Qt.Key_O and not ctrl:
            self.set_end()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.add_segment()
        elif k == Qt.Key_Delete:
            if self.sel >= 0:
                self.delete_segment(self.sel)
        elif k == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        else:
            return False
        return True

    # ---------------------------------------------------------- 파일
    def open_file(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "영상 파일 선택", self.out_dir or "",
            "동영상 (*.mp4 *.m4v *.mov);;모든 파일 (*.*)")
        if path:
            self.load(path)

    def load(self, path):
        if self.worker:
            return
        if self.segments and QMessageBox.question(
                self, APP_NAME, "새 영상을 열면 현재 구간 목록이 지워집니다. 계속할까요?") != QMessageBox.Yes:
            return
        self._stop_thumbs()
        self.gen += 1
        self.seg_thumbs.clear()
        self.seg_pending.clear()
        self.src_path = os.path.abspath(path)
        self.out_dir = os.path.dirname(self.src_path)
        self.ed_out.setText(self.out_dir)
        base = os.path.splitext(os.path.basename(self.src_path))[0]
        self.cmb_name.setItemText(0, f"원본파일명_구간번호    (예: {base}_01.mp4)")
        self.cmb_name.setItemText(1, f"원본파일명_구간번호_시작시간    (예: {base}_01_0h00m09s.mp4)")
        self.setWindowTitle(f"{APP_NAME} - {os.path.basename(self.src_path)}")
        self.segments.clear()
        self.sel = -1
        self.mark_start = self.mark_end = None
        self.preview_end = None
        self._err_shown = False
        self.timeline.reset_thumbs()
        self.timeline.selected = -1
        self._update_marks()
        self._refresh_segments()
        self.view.show_hint(False)
        self.duration = 0
        self.timeline.duration = 0
        self.player.setSource(QUrl.fromLocalFile(self.src_path))
        self.player.pause()
        self._set_enabled()

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
            self.ed_out.setText(d)

    def open_settings(self):
        dlg = SettingsDialog(self, self.accurate)
        if dlg.exec() == QDialog.Accepted:
            self.accurate = dlg.chk.isChecked()

    # ---------------------------------------------------------- 썸네일
    def _start_thumbs(self, jobs, height):
        if not self.ffmpeg or not self.src_path or not jobs:
            return
        wk = ThumbWorker(self.ffmpeg, self.src_path, jobs, height)
        wk.ready.connect(self.on_thumb)
        wk.finished.connect(lambda w=wk: self.thumb_workers.remove(w) if w in self.thumb_workers else None)
        self.thumb_workers.append(wk)
        wk.start()

    def _stop_thumbs(self):
        for wk in self.thumb_workers:
            wk.stop()

    def _request_strip(self):
        if self.strip_gen == self.gen or self.duration <= 0:
            return
        self.strip_gen = self.gen
        n = Timeline.N_THUMBS
        jobs = [(("strip", self.gen, i), int((i + 0.5) * self.duration / n)) for i in range(n)]
        self._start_thumbs(jobs, 120)

    def _request_seg_thumb(self, ms):
        if ms in self.seg_thumbs or ms in self.seg_pending:
            return
        self.seg_pending.add(ms)
        self._start_thumbs([(("seg", self.gen, ms), ms)], 120)

    def on_thumb(self, key, img):
        kind, gen, val = key
        if gen != self.gen:
            return
        if kind == "strip":
            self.timeline.set_thumb(val, img)
        else:
            self.seg_pending.discard(val)
            self.seg_thumbs[val] = img
            for i, (st, _en) in enumerate(self.segments):
                if st == val and i < len(self.cards):
                    self.cards[i].set_thumb(img)

    # ---------------------------------------------------------- 재생
    def toggle_play(self):
        if not self.src_path or self.worker:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.preview_end = None
            self.player.play()

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self.btn_mute.setIcon(make_icon("mute" if self.audio.isMuted() else "volume", "#FFFFFF", 22))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_full.setIcon(make_icon("fullscreen", "#FFFFFF", 22))
        else:
            self.showFullScreen()
            self.btn_full.setIcon(make_icon("exitfull", "#FFFFFF", 22))

    def seek_rel(self, delta):
        if not self.src_path or self.worker:
            return
        self.player.setPosition(min(max(0, self.player.position() + delta), self.duration))

    def on_position(self, pos):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.lbl_time.setText(f"{fmt_hms(pos)} / {fmt_hms(self.duration)}")
        if not self.timeline.dragging and not self.timeline.edit:
            self.timeline.position = pos
            self.timeline.update()
        if self.preview_end is not None and pos >= self.preview_end:
            self.player.pause()
            self.preview_end = None

    def on_duration(self, d):
        self.duration = d
        self.seek.setRange(0, d)
        self.timeline.duration = d
        self.timeline.update()
        self.lbl_time.setText(f"{fmt_hms(self.player.position())} / {fmt_hms(d)}")
        if d > 0:
            self._request_strip()

    def on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            d = self.player.duration()
            if d > 0 and (d != self.duration or self.strip_gen != self.gen):
                self.on_duration(d)

    def on_state(self, st):
        playing = st == QMediaPlayer.PlayingState
        self.btn_play.setIcon(make_icon("pause" if playing else "play", "#FFFFFF", 22))
        self.btn_play2.setIcon(make_icon("pause" if playing else "play", "#FFFFFF", 22))
        self.btn_play2.setText("  일시정지" if playing else "  재생")

    def on_player_error(self, _err, msg):
        if msg and not self._err_shown:
            self._err_shown = True
            QMessageBox.warning(self, APP_NAME, f"영상을 재생하는 중 문제가 생겼습니다.\n{msg}\n\n"
                                "재생이 안 되더라도 구간 저장은 될 수 있습니다.")

    # ---------------------------------------------------------- 시작점 / 끝점
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
            QMessageBox.information(self, APP_NAME, "끝점은 시작점보다 뒤여야 합니다.")
            return
        self.mark_end = pos
        self._update_marks()

    def on_time_typed(self, ed, is_start):
        text = ed.text().strip()
        if not text:
            if is_start:
                self.mark_start = None
            else:
                self.mark_end = None
            self._update_marks()
            return
        ms = parse_time(text)
        if ms is None:
            QMessageBox.information(self, APP_NAME, "시간 형식이 올바르지 않습니다.\n예: 00:01:23.5")
            self._update_marks()
            return
        if self.duration > 0:
            ms = min(ms, self.duration)
        if is_start:
            self.mark_start = ms
            if self.mark_end is not None and self.mark_end <= ms:
                self.mark_end = None
        else:
            if self.mark_start is not None and ms <= self.mark_start:
                QMessageBox.information(self, APP_NAME, "끝점은 시작점보다 뒤여야 합니다.")
                self._update_marks()
                return
            self.mark_end = ms
        self.player.setPosition(ms)
        self._update_marks()

    def _update_marks(self):
        self.ed_start.setText(fmt_ms(self.mark_start) if self.mark_start is not None else "")
        self.ed_end.setText(fmt_ms(self.mark_end) if self.mark_end is not None else "")
        self.timeline.mark_start = self.mark_start
        self.timeline.mark_end = self.mark_end
        self.timeline.update()

    # ---------------------------------------------------------- 구간
    def add_segment(self):
        if not self.src_path or self.worker:
            return
        if self.mark_start is None or self.mark_end is None:
            QMessageBox.information(self, APP_NAME, "구간 시작점과 끝점을 먼저 지정해 주세요.")
            return
        if self.mark_end - self.mark_start < 100:
            QMessageBox.information(self, APP_NAME, "구간이 너무 짧습니다 (0.1초 이상).")
            return
        self.segments.append([self.mark_start, self.mark_end])
        self.mark_start = self.mark_end = None
        self._update_marks()
        self._refresh_segments()
        self.select_segment(len(self.segments) - 1)
        self.scroll.ensureWidgetVisible(self.cards[-1])

    def _refresh_segments(self):
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        for i, (st, en) in enumerate(self.segments):
            card = SegmentCard(i)
            card.set_times(st, en)
            if st in self.seg_thumbs:
                card.set_thumb(self.seg_thumbs[st])
            else:
                self._request_seg_thumb(st)
            card.set_selected(i == self.sel)
            card.clicked.connect(self.on_card_clicked)
            card.playClicked.connect(self.preview_segment)
            card.editClicked.connect(self.edit_segment)
            card.deleteClicked.connect(self.delete_segment)
            self.seg_layout.insertWidget(self.seg_layout.count() - 1, card)
            self.cards.append(card)
        self.empty_lbl.setVisible(not self.segments)
        self.lbl_list.setText(f"추출할 구간 목록 (총 {len(self.segments)}개)")
        if self.sel >= len(self.segments):
            self.sel = -1
        self.timeline.selected = self.sel
        self.timeline.set_segments(self.segments)

    def select_segment(self, i):
        self.sel = i
        for k, c in enumerate(self.cards):
            c.set_selected(k == i)
        self.timeline.selected = i
        self.timeline.update()
        if 0 <= i < len(self.cards):
            self.scroll.ensureWidgetVisible(self.cards[i])

    def on_card_clicked(self, i):
        if self.worker or i >= len(self.segments):
            return
        self.select_segment(i)
        self.player.setPosition(self.segments[i][0])

    def on_timeline_segment(self, i):
        self.on_card_clicked(i)

    def on_segment_edited(self, i, st, en, final):
        if self.worker or i >= len(self.segments):
            return
        self.segments[i] = [st, en]
        if final:
            self._refresh_segments()
            self.select_segment(i)
        elif i < len(self.cards):
            self.cards[i].set_times(st, en)

    def preview_segment(self, i):
        if self.worker or i >= len(self.segments):
            return
        self.select_segment(i)
        st, en = self.segments[i]
        self.player.setPosition(st)
        self.preview_end = en
        self.player.play()

    def edit_segment(self, i):
        if self.worker or i >= len(self.segments):
            return
        self.select_segment(i)
        st, en = self.segments[i]
        dlg = SegmentDialog(self, i, st, en, self.duration)
        if dlg.exec() == QDialog.Accepted and dlg.result_times:
            self.segments[i] = list(dlg.result_times)
            self._refresh_segments()
            self.select_segment(i)

    def delete_segment(self, i):
        if self.worker or i >= len(self.segments):
            return
        del self.segments[i]
        if self.sel == i:
            self.sel = -1
        elif self.sel > i:
            self.sel -= 1
        self._refresh_segments()

    def clear_segments(self):
        if self.segments and QMessageBox.question(self, APP_NAME, "구간을 모두 지울까요?") == QMessageBox.Yes:
            self.segments.clear()
            self.sel = -1
            self._refresh_segments()

    # ---------------------------------------------------------- 저장
    def _out_name(self, i):
        base = os.path.splitext(os.path.basename(self.src_path))[0]
        if self.cmb_name.currentIndex() == 1:
            s = self.segments[i][0] // 1000
            return f"{base}_{i + 1:02d}_{s // 3600}h{s % 3600 // 60:02d}m{s % 60:02d}s.mp4"
        return f"{base}_{i + 1:02d}.mp4"

    def save_all(self):
        if self.worker:
            self.worker.cancel()
            return
        if not self.src_path:
            QMessageBox.information(self, APP_NAME, "먼저 영상을 열어 주세요.")
            return
        if not self.segments:
            QMessageBox.information(self, APP_NAME, "저장할 구간이 없습니다. 먼저 구간을 추가해 주세요.")
            return
        if not self.ffmpeg:
            QMessageBox.critical(self, APP_NAME, "프로그램 안의 FFmpeg를 찾을 수 없습니다. 다시 설치해 주세요.")
            return
        if not os.path.isdir(self.out_dir):
            QMessageBox.warning(self, APP_NAME, "저장 폴더가 존재하지 않습니다.")
            return
        jobs = []
        for i, (s, e) in enumerate(self.segments):
            out = os.path.join(self.out_dir, self._out_name(i))
            if os.path.normcase(os.path.abspath(out)) == os.path.normcase(self.src_path):
                QMessageBox.critical(self, APP_NAME, "저장 파일명이 원본과 같습니다. 저장 폴더를 바꿔 주세요.")
                return
            jobs.append((s, e, out))
        exist = [os.path.basename(j[2]) for j in jobs if os.path.exists(j[2])]
        if exist:
            preview = "\n".join(exist[:10]) + ("\n..." if len(exist) > 10 else "")
            if QMessageBox.question(self, APP_NAME, f"아래 파일이 이미 있습니다. 덮어쓸까요?\n\n{preview}") != QMessageBox.Yes:
                return
        self.player.pause()
        self.preview_end = None
        self.worker = CutWorker(self.ffmpeg, self.src_path, jobs, self.accurate)
        self.worker.progress.connect(self.on_progress)
        self.worker.failed.connect(lambda m: QMessageBox.critical(self, APP_NAME, m))
        self.worker.done.connect(self.on_done)
        self.worker.finished.connect(self.on_worker_finished)
        self._set_enabled()
        self.save_title.setText("저장 중...")
        self.save_sub.setText("준비 중 · 클릭하면 취소")
        self.worker.start()

    def on_progress(self, i, total, frac):
        pct = int((i + frac) / total * 100)
        self.save_title.setText(f"저장 중... {pct}%")
        self.save_sub.setText(f"{i + 1} / {total} 번째 파일 · 클릭하면 취소")

    def on_done(self, cancelled):
        if cancelled:
            QMessageBox.information(self, APP_NAME, "저장을 취소했습니다.")
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"{len(self.segments)}개 파일을 저장했습니다.\n\n{self.out_dir}")
        open_btn = box.addButton("폴더 열기", QMessageBox.AcceptRole)
        box.addButton("닫기", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == open_btn and os.name == "nt":
            os.startfile(self.out_dir)

    def on_worker_finished(self):
        self.worker = None
        self._set_enabled()

    def closeEvent(self, e):
        if self.worker:
            if QMessageBox.question(self, APP_NAME, "저장 중입니다. 취소하고 종료할까요?") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.worker.wait(5000)
        self._stop_thumbs()
        for wk in list(self.thumb_workers):
            wk.wait(3000)
        self.player.stop()
        super().closeEvent(e)


def apply_light_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in ((QPalette.Window, "#F3F5F9"), (QPalette.WindowText, "#1F2937"),
                      (QPalette.Base, "#FFFFFF"), (QPalette.AlternateBase, "#F7F8FA"),
                      (QPalette.Text, "#1F2937"), (QPalette.Button, "#FFFFFF"),
                      (QPalette.ButtonText, "#1F2937"), (QPalette.Highlight, ACCENT),
                      (QPalette.HighlightedText, "#FFFFFF"), (QPalette.ToolTipBase, "#1F2937"),
                      (QPalette.ToolTipText, "#FFFFFF"), (QPalette.PlaceholderText, "#9CA3AF")):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    f = QFont("Malgun Gothic")
    f.setPointSize(12)
    app.setFont(f)
    app.setStyleSheet(QSS)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_light_theme(app)
    w = MainWindow()
    app.installEventFilter(w)
    scr = app.primaryScreen()
    if scr is not None and (scr.availableGeometry().height() < 1040 or scr.availableGeometry().width() < 1500):
        w.showMaximized()
    else:
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
