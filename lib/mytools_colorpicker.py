# -*- coding: utf-8 -*-
"""
mytools_colorpicker.py — Піпетка кольору для системного діалогу "Цвет" ("Color").

НОВИЙ, повністю ізольований модуль. Нічого в інших файлах MyTools.extension
не змінюється і не імпортується звідси (окрім читання, якщо знадобиться).

────────────────────────────────────────────────────────────────────────────
Що робить:
  1. Фоновий STA-потік крутить СПРАВЖНІЙ Windows message loop
     (WinForms.Application.Run() + WinForms.Timer з інтервалом ~250 мс),
     а не ручний цикл на DoEvents()+sleep(). Timer лише періодично
     перевіряє, чи не відкрито в поточному процесі (Revit.exe) системний
     Windows-діалог вибору кольору (ChooseColor, comdlg32.dll — той самий
     диалог "Цвет"/"Color", що й у Paint, Word тощо); усі інтерактивні
     події (рух миші, клік, Esc) в кнопці й оверлеї обробляються напряму
     повідомленнями Windows у реальному часі, без затримки до 250 мс.
     Діалог завжди має клас "#32770" і, якщо це саме він, у ньому завжди
     є 3 конкретних елементи керування з фіксованими, задокументованими
     у Windows (dlgs.h) ідентифікаторами:
         Red   = 0x2C2 (706)
         Green = 0x2C3 (707)
         Blue  = 0x2C4 (708)
     Ці ID однакові в будь-якій версії Windows і будь-якій мові інтерфейсу,
     тому визначення діалогу не залежить від локалізації Revit.

  2. Коли діалог знайдено — біля його правого верхнього кута з'являється
     маленька кругла плаваюча кнопка-піпетка (WinForms, TopMost, без рамки).
     Кнопка "їде" за діалогом, якщо його перетягнути.

  3. Клік по кнопці відкриває прозорий (Form.Opacity) оверлей на весь
     віртуальний робочий стіл (усі монітори), який:
       - показує лупу (збільшені пікселі) під курсором в реальному часі,
         з підписом поточного RGB / HEX під курсором;
       - по кліку лівою кнопкою миші БУДЬ-ДЕ на екрані (навіть у іншій
         програмі, поза вікном Revit) миттєво зчитує колір цього пікселя
         і закриває оверлей;
       - Esc скасовує вибір без змін.

  4. Зчитаний колір вписується у поля Red/Green/Blue діалогу "Цвет" через
     SendMessage (WM_SETTEXT + синтетичний WM_COMMAND/EN_KILLFOCUS, який
     Windows-діалог сприймає так само, як якщо б користувач сам ввів
     значення і перевів фокус на інше поле). Це безпечно виконувати з
     іншого потоку (на відміну від SetFocus, що вимагав би AttachThreadInput).
     Поля Hue/Sat/Lum і прев'ю кольору Windows перерахує сам.
     Кнопки "ОК" / "Добавить" НЕ натискаються автоматично — це користувач
     робить сам, як і було запитано.

⚠ Обмеження, чесно попереджаю:
  - Це працює лише на Windows (Revit і так лише на Windows).
  - ID полів Red/Green/Blue (0x2C2/0x2C3/0x2C4) — це загальновідомі,
    задокументовані константи стандартного діалогу Windows, що
    десятиліттями не змінювались. Але я не мав змоги протестувати це
    наживо в Revit/pyRevit (я працюю в Linux-пісочниці без Windows), тому
    перший запуск варто перевірити. Якщо RGB не заповнюється — напишіть,
    я миттєво підправлю константи чи логіку.
  - Якщо натиснути pyRevit → Reload, поки піпетка увімкнена, старий
    фоновий потік може ще трохи "жити" у пам'яті (не заважає, не видно).
    Простіше вимкнути піпетку перед Reload.

──────────────────────────────────────────────────────────────────────────
Виправлення (v2): раніше фоновий потік вручну гнав повідомлення Windows
через Application.DoEvents() всередині циклу з time.sleep(0.25). Це
означало, що між викликами DoEvents() усі події (рух миші, клік, Esc)
накопичувались у черзі на чверть секунди й оброблялись одним ривком —
звідси й лаг, і "відв'язана" від курсора лупа, і клік/Esc, які ніби не
спрацьовували (насправді спрацьовували з затримкою, а якщо цикл саме
був у sleep() у момент закриття вікна — подія просто губилась).
Додатково: растрові зображення лупи не звільнялись (Dispose) при
кожному русі миші — витік GDI-ресурсів, що з часом підсилював гальма.

Тепер: справжній Windows message loop (Application.Run() + WinForms.Timer
для періодичної перевірки діалогу), лупа кругла й менша, а Bitmap/
Graphics/Font/Pen/Brush для лупи й кнопки створюються один раз і
переви­користовуються замість перестворення щокадру.
"""

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Threading")

import System.Windows.Forms as WinForms
from System.Windows.Forms import (
    Form, FormBorderStyle, FormStartPosition, Cursors, Keys, DialogResult,
    MouseButtons
)
from System.Drawing import (
    Color, Point, Size, Rectangle, Graphics, Bitmap, Font, FontStyle,
    Pen, SolidBrush, Region, ContentAlignment
)
import System.Drawing.Drawing2D as Drawing2D
from System.Threading import Thread, ThreadStart, ApartmentState
import System.Diagnostics as SysDiag

try:
    import ctypes
    from ctypes import wintypes
    _CTYPES_OK = True
except Exception:
    _CTYPES_OK = False


ACCENT_COLOR = Color.FromArgb(0, 112, 200)
BG_COLOR     = Color.FromArgb(250, 250, 252)


# ────────────────────────────────────────────────────────────────────────────
#  WinAPI (ctypes) — низькорівневий доступ до системного діалогу ChooseColor
# ────────────────────────────────────────────────────────────────────────────

WM_SETTEXT   = 0x000C
WM_COMMAND   = 0x0111
EN_KILLFOCUS = 0x0200
BM_CLICK     = 0x00F5

# Control ID стандартного Windows-діалогу ChooseColor (dlgs.h, comdlg32.dll).
# Однакові для будь-якої програми на Windows (Paint, Word, Revit...).
ID_RED   = 0x2C2
ID_GREEN = 0x2C3
ID_BLUE  = 0x2C4

DIALOG_CLASS = u"#32770"

_user32 = None
_WNDENUMPROC = None
_SendMessageText = None
_SendMessageParam = None
_OUR_PID = None

if _CTYPES_OK:
    try:
        _user32 = ctypes.windll.user32
        _OUR_PID = SysDiag.Process.GetCurrentProcess().Id

        _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        _user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.GetDlgItem.restype  = wintypes.HWND

        _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.GetClassNameW.restype  = ctypes.c_int

        _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        _user32.GetWindowThreadProcessId.restype  = wintypes.DWORD

        _user32.IsWindowVisible.argtypes = [wintypes.HWND]
        _user32.IsWindowVisible.restype  = wintypes.BOOL

        _user32.IsWindow.argtypes = [wintypes.HWND]
        _user32.IsWindow.restype  = wintypes.BOOL

        _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        _user32.GetWindowRect.restype  = wintypes.BOOL

        _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
        _user32.EnumWindows.restype  = wintypes.BOOL

        _user32.EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]
        _user32.EnumChildWindows.restype  = wintypes.BOOL

        _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        _user32.GetWindowTextW.restype  = ctypes.c_int

        # SendMessageW потрібен у ДВОХ варіантах типізації lParam
        # (текст для WM_SETTEXT, і hwnd/ціле для WM_COMMAND) —
        # тому окремо реєструємо той самий експорт двічі з різними argtypes.
        _SendMessageText = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_wchar_p
        )(("SendMessageW", ctypes.windll.user32))

        _SendMessageParam = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_void_p
        )(("SendMessageW", ctypes.windll.user32))
    except Exception:
        _CTYPES_OK = False


def _find_color_dialog():
    """Повертає hwnd системного діалогу 'Цвет', якщо він зараз відкритий
    у поточному процесі, інакше None."""
    if not _CTYPES_OK:
        return None
    result = {u"hwnd": None}

    def _enum_proc(hwnd, lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(64)
            _user32.GetClassNameW(hwnd, buf, 64)
            if buf.value != DIALOG_CLASS:
                return True
            pid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != _OUR_PID:
                return True
            h_red   = _user32.GetDlgItem(hwnd, ID_RED)
            h_green = _user32.GetDlgItem(hwnd, ID_GREEN)
            h_blue  = _user32.GetDlgItem(hwnd, ID_BLUE)
            if h_red and h_green and h_blue:
                result[u"hwnd"] = hwnd
                return False  # знайшли — зупинити перебір
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_WNDENUMPROC(_enum_proc), 0)
    except Exception:
        pass
    return result[u"hwnd"]


def _get_rect(hwnd):
    try:
        rect = wintypes.RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return None


def _set_field(hwnd_dialog, ctrl_id, value, label):
    """Вписує число у поле діалогу (Red/Green/Blue) і імітує втрату фокуса,
    щоб Windows сам перерахував Hue/Sat/Lum і прев'ю кольору.
    Повертає (ok, опис) — опис показуємо користувачу для діагностики,
    доки ми розбираємось, чому запис не спрацьовує."""
    try:
        hwnd_edit = _user32.GetDlgItem(hwnd_dialog, ctrl_id)
        if not hwnd_edit:
            return False, u"{0}: поле НЕ знайдено (GetDlgItem повернув 0)".format(label)
        try:
            visible = bool(_user32.IsWindowVisible(hwnd_edit))
        except Exception:
            visible = None
        text = u"{0}".format(int(value))
        _SendMessageText(hwnd_edit, WM_SETTEXT, 0, text)
        wparam = (EN_KILLFOCUS << 16) | (ctrl_id & 0xFFFF)
        _SendMessageParam(hwnd_dialog, WM_COMMAND, wparam, hwnd_edit)
        return True, u"{0}: записав '{1}' (поле видиме: {2})".format(label, text, visible)
    except Exception as ex:
        return False, u"{0}: виняток — {1}".format(label, ex)


def _ensure_custom_colors_expanded(hwnd_dialog):
    """Стандартний діалог 'Цвет' відкривається ЗГОРНУТИМ — поля Red/Green/
    Blue існують у вікні, але приховані, доки не натиснути "Определить
    цвет »" ("Define Custom Colors »"). Якщо просто писати в приховані
    поля, користувач не побачить змін (і сам діалог їх не завжди приймає).
    Тому спершу перевіряємо, чи поле Red вже видиме — якщо ні, шукаємо серед
    дочірніх кнопок ту, що містить "»"/">>' (цей символ є в підписі кнопки
    розгортання практично в усіх локалізаціях Windows) і натискаємо її.
    Повертає рядок-опис того, що сталося (для діагностики)."""
    try:
        h_red = _user32.GetDlgItem(hwnd_dialog, ID_RED)
        if h_red and _user32.IsWindowVisible(h_red):
            return u"панель Custom Colors: вже розгорнута"
    except Exception as ex:
        return u"панель Custom Colors: перевірка видимості впала — {0}".format(ex)

    result = {u"btn": None}

    def _enum_child(hwnd, lparam):
        try:
            cls = ctypes.create_unicode_buffer(64)
            _user32.GetClassNameW(hwnd, cls, 64)
            if cls.value != u"Button":
                return True
            text = ctypes.create_unicode_buffer(128)
            _user32.GetWindowTextW(hwnd, text, 128)
            if u"\u00bb" in text.value or u">>" in text.value:
                result[u"btn"] = hwnd
                return False
        except Exception:
            pass
        return True

    try:
        _user32.EnumChildWindows(hwnd_dialog, _WNDENUMPROC(_enum_child), 0)
    except Exception as ex:
        return u"панель Custom Colors: EnumChildWindows впав — {0}".format(ex)

    if result[u"btn"]:
        try:
            _SendMessageParam(result[u"btn"], BM_CLICK, 0, 0)
            return u"панель Custom Colors: була згорнута, натиснув кнопку розгортання"
        except Exception as ex:
            return u"панель Custom Colors: знайшов кнопку '»', але клік впав — {0}".format(ex)
    return u"панель Custom Colors: була згорнута, кнопку '»' НЕ знайшов серед дочірніх"


def apply_color_to_dialog(hwnd_dialog, color):
    """color — System.Drawing.Color. Повертає (ok, деталі-рядок для показу
    користувачу — доки налагоджуємо, чому запис у поля не спрацьовує)."""
    if hwnd_dialog is None:
        return False, u"hwnd діалогу порожній (None) — я не знаю, куди вписувати"
    try:
        alive = _user32.IsWindow(hwnd_dialog)
    except Exception as ex:
        return False, u"IsWindow(hwnd) впав — {0}".format(ex)
    if not alive:
        return False, u"вікно діалогу вже не існує (hwnd невалідний)"

    lines = [_ensure_custom_colors_expanded(hwnd_dialog)]
    ok_r, info_r = _set_field(hwnd_dialog, ID_RED,   color.R, u"R")
    ok_g, info_g = _set_field(hwnd_dialog, ID_GREEN, color.G, u"G")
    ok_b, info_b = _set_field(hwnd_dialog, ID_BLUE,  color.B, u"B")
    lines.extend([info_r, info_g, info_b])
    return (ok_r and ok_g and ok_b), u"\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  Плаваюча кнопка-піпетка
# ────────────────────────────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────────────
#  Плаваюча кнопка-піпетка
# ────────────────────────────────────────────────────────────────────────────

class _FloatingButton(Form):
    def __init__(self, on_click):
        super(_FloatingButton, self).__init__()
        self._on_click = on_click

        self.FormBorderStyle = getattr(FormBorderStyle, u"None")
        self.StartPosition   = FormStartPosition.Manual
        self.ShowInTaskbar   = False
        self.TopMost         = True
        self.Width           = 34
        self.Height          = 34
        self.BackColor       = BG_COLOR
        self.Cursor          = Cursors.Hand

        try:
            path = Drawing2D.GraphicsPath()
            path.AddEllipse(0, 0, self.Width, self.Height)
            self.Region = Region(path)
            path.Dispose()
        except Exception:
            pass

        # Кешовані GDI-об'єкти — створюються один раз, а не щокадру в Paint
        # (раніше Pen/SolidBrush створювались заново на кожен виклик _on_paint).
        self._pen_ring  = Pen(ACCENT_COLOR, 2.5)
        self._brush_dot = SolidBrush(ACCENT_COLOR)

        self.MouseClick += self._on_mouse_click
        self.Paint       += self._on_paint
        self.FormClosed  += self._on_closed

        tip = WinForms.ToolTip()
        try:
            tip.SetToolTip(self, u"Піпетка кольору: обрати колір з екрана")
        except Exception:
            pass

    def _on_paint(self, sender, e):
        g = e.Graphics
        g.SmoothingMode = Drawing2D.SmoothingMode.AntiAlias
        g.Clear(BG_COLOR)
        g.DrawEllipse(self._pen_ring, 4, 4, self.Width - 9, self.Height - 9)
        cx = self.Width  / 2
        cy = self.Height / 2
        g.FillEllipse(self._brush_dot, cx - 3, cy - 3, 6, 6)

    def _on_mouse_click(self, sender, e):
        if e.Button == MouseButtons.Left:
            try:
                self._on_click()
            except Exception as ex:
                # Тимчасово показуємо будь-яку помилку — раніше вона тут
                # мовчки ковталась, і клік виглядав як "взагалі нічого не
                # відбувається" без жодної зачіпки, що саме зламалось.
                try:
                    WinForms.MessageBox.Show(
                        u"Клік по кнопці впав з помилкою:\n\n{0}".format(ex),
                        u"Піпетка — діагностика")
                except Exception:
                    pass

    def _on_closed(self, sender, e):
        for obj in (self._pen_ring, self._brush_dot):
            try:
                obj.Dispose()
            except Exception:
                pass

    def reposition(self, x, y):
        try:
            self.Location = Point(int(x), int(y))
        except Exception:
            pass


# ────────────────────────────────────────────────────────────────────────────
#  Повноекранний прозорий оверлей з круглою лупою
# ────────────────────────────────────────────────────────────────────────────

# Розміри лупи — легко підправити тут, якщо треба ще менше/більше.
_MAG_SRC    = 7   # скільки пікселів екрана навколо курсора беремо (непарне)
_MAG_ZOOM   = 8   # у скільки разів кожен піксель малюємо збільшеним
_MAG_IMG    = _MAG_SRC * _MAG_ZOOM         # розмір зображення лупи, px
_MAG_PAD    = 4                            # відступ картинки від країв вікна
_MAG_TEXT_H = 16                           # висота смужки з HEX-кодом знизу
_MAG_W      = _MAG_IMG + _MAG_PAD * 2
_MAG_H      = _MAG_IMG + _MAG_PAD * 2 + _MAG_TEXT_H
_MAG_GAP    = 14  # відступ лупи від самого курсора


class _MagnifierForm(Form):
    """Невеличка лупа біля курсора: збільшені пікселі навколо курсора під
    час вибору кольору, рамка навколо того пікселя, який буде взято по
    кліку, і його HEX-код знизу."""

    def __init__(self):
        super(_MagnifierForm, self).__init__()
        # AutoScaleMode за замовчуванням масштабує розмір форми під
        # системний шрифт/DPI, АЛЕ саме зображення в _on_paint малюється
        # "сирими" пікселями (Rectangle без урахування DPI) — тому вікно
        # роздувалось, а картинка лишалась тих самих 56×56 px. Вимикаємо
        # автомасштабування, щоб форма була рівно того розміру, який ми
        # задаємо (_MAG_W x _MAG_H), без розбіжності з вмістом.
        self.AutoScaleMode   = getattr(WinForms.AutoScaleMode, u"None")
        self.FormBorderStyle = getattr(FormBorderStyle, u"None")
        self.StartPosition   = FormStartPosition.Manual
        self.TopMost         = True
        self.ShowInTaskbar   = False
        self.Size            = Size(_MAG_W, _MAG_H)
        self.BackColor       = Color.FromArgb(30, 30, 30)

        self._src_bmp = Bitmap(_MAG_SRC, _MAG_SRC)
        self._src_gfx = Graphics.FromImage(self._src_bmp)
        self._center_color = Color.Black
        self._font = Font(u"Consolas", 8.5, FontStyle.Regular)

        self.Paint += self._on_paint

    def update_at(self, cursor, active_bounds):
        """Оновлює вміст лупи під поточну позицію курсора (screen coords)
        і переміщує саме вікно лупи так, щоб воно не затуляло піксель, що
        зчитується, і не вилазило за межі поточного монітора."""
        half = _MAG_SRC // 2
        try:
            self._src_gfx.CopyFromScreen(
                cursor.X - half, cursor.Y - half, 0, 0, Size(_MAG_SRC, _MAG_SRC)
            )
            self._center_color = self._src_bmp.GetPixel(half, half)
        except Exception:
            pass

        x = cursor.X + _MAG_GAP
        y = cursor.Y + _MAG_GAP
        if x + _MAG_W > active_bounds.Right:
            x = cursor.X - _MAG_GAP - _MAG_W
        if y + _MAG_H > active_bounds.Bottom:
            y = cursor.Y - _MAG_GAP - _MAG_H
        self.Location = Point(x, y)

        self.Invalidate()

    def _on_paint(self, sender, e):
        g = e.Graphics
        g.InterpolationMode = Drawing2D.InterpolationMode.NearestNeighbor

        img_rect = Rectangle(_MAG_PAD, _MAG_PAD, _MAG_IMG, _MAG_IMG)
        g.DrawImage(self._src_bmp, img_rect)

        # рамка навколо всієї картинки
        border_pen = Pen(Color.FromArgb(90, 90, 90), 1)
        try:
            g.DrawRectangle(border_pen, img_rect)
        finally:
            border_pen.Dispose()

        # біла рамка навколо центрального пікселя (саме він буде взятий)
        half = _MAG_SRC // 2
        cell = Rectangle(
            _MAG_PAD + half * _MAG_ZOOM, _MAG_PAD + half * _MAG_ZOOM,
            _MAG_ZOOM, _MAG_ZOOM
        )
        center_pen = Pen(Color.White, 2)
        try:
            g.DrawRectangle(center_pen, cell)
        finally:
            center_pen.Dispose()

        # HEX-код кольору знизу
        hex_text = u"#{0:02X}{1:02X}{2:02X}".format(
            self._center_color.R, self._center_color.G, self._center_color.B
        )
        text_rect = Rectangle(0, _MAG_PAD * 2 + _MAG_IMG, _MAG_W, _MAG_TEXT_H)
        WinForms.TextRenderer.DrawText(
            g, hex_text, self._font, text_rect, Color.White,
            WinForms.TextFormatFlags.HorizontalCenter | WinForms.TextFormatFlags.VerticalCenter
        )

    def cleanup(self):
        for obj in (self._src_gfx, self._src_bmp, self._font):
            try:
                obj.Dispose()
            except Exception:
                pass


class _HintForm(Form):
    """Окреме НЕпрозоре маленьке віконце-підказка.

    Раніше текст підказки був звичайним Label, доданим у Controls самого
    прозорого оверлею. Це саме собою не було проблемою — проблема була в
    тому, ЯК оверлей ставав прозорим (TransparencyKey, див. коментар у
    _PickerOverlay нижче). Але коли прозорість оверлею виправили на
    Opacity, підказку довелось винести в окрему форму: Form.Opacity діє
    відразу на ВСЕ вікно разом з дочірніми контролами, тобто якщо лишити
    Label дочірнім елементом прозорого оверлею — текст підказки теж став
    би майже невидимим."""

    def __init__(self, text, bounds):
        super(_HintForm, self).__init__()
        self.AutoScaleMode   = getattr(WinForms.AutoScaleMode, u"None")
        self.FormBorderStyle = getattr(FormBorderStyle, u"None")
        self.StartPosition   = FormStartPosition.Manual
        self.Bounds          = bounds
        self.TopMost         = True
        self.ShowInTaskbar   = False
        self.BackColor       = Color.FromArgb(20, 20, 20)

        lbl = WinForms.Label()
        lbl.Dock       = WinForms.DockStyle.Fill
        lbl.TextAlign  = ContentAlignment.MiddleCenter
        lbl.ForeColor  = Color.White
        lbl.Font       = Font(u"Segoe UI", 11, FontStyle.Bold)
        lbl.Text       = text
        self.Controls.Add(lbl)


class _PickerOverlay(Form):
    """Тимчасово БЕЗ лупи — щоб спершу перевірити саму механіку піпетки
    (клік → зчитати колір екрана → записати в R/G/B) окремо від будь-якої
    візуалізації, яка могла додавати власні глюки.

    ВАЖЛИВО (виправлення №1): раніше "прозорість" робилась через
    TransparencyKey — область, прозора через TransparencyKey, ОДНОЧАСНО
    стає наскрізною для кліків миші. Замінено на Form.Opacity.

    ВАЖЛИВО (виправлення №2, ВІДКОЧЕНО): проміжна версія ловила клік через
    глобальний low-level хук миші (WH_MOUSE_LL, ctypes SetWindowsHookExW).
    Це технічно правильний підхід (саме так зроблено в еталонному Cyotek
    ScreenColorPickerHooks.cs), АЛЕ викликало краш самого Revit — нативний
    зворотний виклик (callback) з ОС у наш Python-код через ctypes у
    цьому оточенні виявився нестабільним і завалював увесь процес, а не
    просто кидав виняток, який можна було б перехопити.

    Тому замість ctypes-хука тепер використовується штатний, повністю
    керований (managed) механізм WinForms — Control.Capture (обгортка
    над Win32 SetCapture). Після Capture = True ВСІ подальші події миші
    (включно з першим кліком будь-де на екрані, навіть поза межами цього
    вікна) напряму спрямовуються у форму — без жодного нативного
    колбека з боку ОС і без ризику для стабільності хосту (Revit)."""

    def __init__(self):
        super(_PickerOverlay, self).__init__()

        vs = WinForms.SystemInformation.VirtualScreen
        self.AutoScaleMode   = getattr(WinForms.AutoScaleMode, u"None")
        self.FormBorderStyle = getattr(FormBorderStyle, u"None")
        self.StartPosition   = FormStartPosition.Manual
        self.Bounds          = Rectangle(vs.X, vs.Y, vs.Width, vs.Height)
        self.TopMost         = True
        self.ShowInTaskbar   = False
        self.KeyPreview      = True
        self.Cursor          = Cursors.Cross

        self.BackColor = Color.Black
        self.Opacity   = 0.03  # майже невидимий; клік ловить Control.Capture, не прозорість

        self.picked_color = None

        self._pick_bmp = Bitmap(1, 1)
        self._pick_gfx = Graphics.FromImage(self._pick_bmp)

        # Підказку показуємо на тому моніторі, де зараз курсор (а не в куті
        # ВСЬОГО віртуального робочого столу — на мультимоніторній системі
        # той кут міг опинитись на екрані, куди користувач навіть не
        # дивиться, і підказка просто губилась з поля зору).
        try:
            active_bounds = WinForms.Screen.FromPoint(WinForms.Cursor.Position).Bounds
        except Exception:
            active_bounds = Rectangle(vs.X, vs.Y, vs.Width, vs.Height)

        hint_w, hint_h = 420, 46
        hint_x = (active_bounds.X - vs.X) + (active_bounds.Width - hint_w) // 2
        hint_y = (active_bounds.Y - vs.Y) + 24

        self._hint = _HintForm(
            u"Клік — узяти колір.   Esc — скасувати.",
            Rectangle(vs.X + hint_x, vs.Y + hint_y, hint_w, hint_h)
        )

        self._magnifier = _MagnifierForm()

        self.MouseDown  += self._on_mouse_down
        self.MouseMove  += self._on_mouse_move
        self.KeyDown    += self._on_key_down
        self.Shown      += self._on_shown
        self.FormClosed += self._on_closed

    def _on_shown(self, sender, e):
        try:
            self._hint.Show()
        except Exception:
            pass
        try:
            self.Capture = True
        except Exception:
            pass
        try:
            self._magnifier.Show()
            self._update_magnifier(WinForms.Cursor.Position)
        except Exception:
            pass

    def _update_magnifier(self, cursor):
        try:
            active_bounds = WinForms.Screen.FromPoint(cursor).Bounds
        except Exception:
            active_bounds = self.Bounds
        try:
            self._magnifier.update_at(cursor, active_bounds)
        except Exception:
            pass

    def _on_mouse_move(self, sender, e):
        self._update_magnifier(WinForms.Cursor.Position)

    def _on_mouse_down(self, sender, e):
        if e.Button == MouseButtons.Left:
            # Реальні екранні координати курсора — а НЕ self.Left + e.X,
            # бо при Control.Capture=True клік міг статись і поза межами
            # (чи "уявними" межами) цього вікна.
            pt = WinForms.Cursor.Position
            try:
                self._pick_gfx.CopyFromScreen(pt.X, pt.Y, 0, 0, Size(1, 1))
                self.picked_color = self._pick_bmp.GetPixel(0, 0)
            except Exception:
                self.picked_color = None
            try:
                self.Capture = False
            except Exception:
                pass
            self.DialogResult = DialogResult.OK
            self.Close()

    def _on_key_down(self, sender, e):
        if e.KeyCode == Keys.Escape:
            self.picked_color = None
            try:
                self.Capture = False
            except Exception:
                pass
            self.DialogResult = DialogResult.Cancel
            self.Close()

    def _on_closed(self, sender, e):
        try:
            self._hint.Close()
            self._hint.Dispose()
        except Exception:
            pass
        try:
            self._magnifier.cleanup()
            self._magnifier.Close()
            self._magnifier.Dispose()
        except Exception:
            pass
        for obj in (self._pick_gfx, self._pick_bmp):
            try:
                obj.Dispose()
            except Exception:
                pass


# ────────────────────────────────────────────────────────────────────────────
#  Спостерігач (фоновий потік)
# ────────────────────────────────────────────────────────────────────────────

class ColorPickerWatcher(object):
    """Один екземпляр на сесію pyRevit (див. get_watcher())."""

    POLL_MS = 250  # як часто перевіряти, чи відкрито діалог "Цвет". Це впливає
                   # лише на фонове виявлення діалогу — рух миші/клік/Esc у
                   # кнопці й оверлеї обробляються напряму, без цієї затримки.

    def __init__(self):
        self._thread      = None
        self._stop_flag   = [False]
        self._button      = None
        self._dialog_hwnd = None
        self._timer       = None

    def is_running(self):
        return self._thread is not None and self._thread.IsAlive

    def start(self):
        if not _CTYPES_OK:
            raise RuntimeError(
                u"ctypes недоступний у цьому середовищі pyRevit — "
                u"піпетка не може працювати."
            )
        if self.is_running():
            return
        self._stop_flag = [False]
        self._thread = Thread(ThreadStart(self._run))
        self._thread.IsBackground = True
        self._thread.SetApartmentState(ApartmentState.STA)
        self._thread.Start()

    def stop(self):
        # Прапорець перевіряється в _on_tick на ТОМУ Ж потоці, де крутиться
        # Application.Run() — тому безпечно виставляти його з іншого (UI)
        # потоку напряму, без Invoke: найближчий тік таймера (макс. POLL_MS)
        # сам викличе Application.ExitThread() і акуратно завершить потік.
        self._stop_flag[0] = True

    def _run(self):
        # СПРАВЖНІЙ Windows message loop замість ручного DoEvents()+sleep().
        # Application.Run() безперервно й миттєво качає повідомлення миші й
        # клавіатури для будь-яких Form, створених на цьому потоці (кнопка,
        # оверлей) — звідси зникають лаг, "відв'язана" лупа й пропущені
        # клік/Esc, які раніше губились між ручними викликами DoEvents().
        # WinForms.Timer сам використовує цей же message loop для тіків,
        # окремого потоку для нього не потрібно.
        self._timer = WinForms.Timer()
        self._timer.Interval = self.POLL_MS
        self._timer.Tick += self._on_tick
        self._timer.Start()
        try:
            WinForms.Application.Run()
        finally:
            try:
                self._timer.Stop()
                self._timer.Dispose()
            except Exception:
                pass
            self._timer = None
            if self._button is not None:
                try:
                    self._button.Close()
                    self._button.Dispose()
                except Exception:
                    pass
                self._button = None
                self._dialog_hwnd = None

    def _on_tick(self, sender, e):
        if self._stop_flag[0]:
            try:
                WinForms.Application.ExitThread()
            except Exception:
                pass
            return

        hwnd = _find_color_dialog()

        if hwnd:
            rect = _get_rect(hwnd)
            if self._button is None:
                self._dialog_hwnd = hwnd
                self._button = _FloatingButton(self._on_pick_clicked)
                if rect:
                    self._position_button(rect)
                try:
                    self._button.Show()
                except Exception:
                    pass
            else:
                self._dialog_hwnd = hwnd
                if rect:
                    self._position_button(rect)
        else:
            if self._button is not None:
                try:
                    self._button.Close()
                    self._button.Dispose()
                except Exception:
                    pass
                self._button = None
                self._dialog_hwnd = None

    def _position_button(self, rect):
        if self._button is None:
            return
        left, top, right, bottom = rect
        btn_w = self._button.Width
        btn_h = self._button.Height

        # Кнопка йде ПІД вікном діалогу (не в шапці) — раніше вона сиділа
        # у правому верхньому куті й перекривала системну кнопку "Закрити".
        x = right - btn_w
        y = bottom + 6

        # Але якщо під вікном не вистачає місця (діалог відкрився близько
        # до низу екрана/за таскбаром) — "під вікном" виїжджає за межі
        # робочої області і кнопка стає невидимою. Тому підтискаємо її до
        # видимих меж екрана, а за браком місця знизу — ставимо над вікном.
        try:
            screen = WinForms.Screen.FromRectangle(Rectangle(left, top, right - left, bottom - top))
            wa = screen.WorkingArea
        except Exception:
            wa = None

        if wa is not None:
            if y + btn_h > wa.Bottom:
                y = top - btn_h - 6
            if y < wa.Top:
                y = wa.Top + 2
            if x + btn_w > wa.Right:
                x = wa.Right - btn_w - 2
            if x < wa.Left:
                x = wa.Left + 2

        self._button.reposition(x, y)

    def _on_pick_clicked(self):
        hwnd = self._dialog_hwnd

        # Явне модальне вікно ПЕРЕД тим, як екран стане прозорим — інакше
        # користувач бачить лише дрібну підказку в кутку (яка на мульти-
        # моніторній системі могла опинитись зовсім не на тому екрані, куди
        # він дивиться) і не розуміє, що взагалі відбувається після кліку.
        WinForms.MessageBox.Show(
            u"Зараз екран стане прозорим для вибору кольору.\n\n"
            u"Клікни лівою кнопкою миші будь-де на екрані (можна й поза "
            u"вікном Revit) — колір під курсором зчитається автоматично.\n\n"
            u"Esc — скасувати й нічого не міняти.",
            u"Піпетка кольору")

        overlay = _PickerOverlay()
        try:
            overlay.ShowDialog()
            color = overlay.picked_color
        finally:
            try:
                overlay.Dispose()
            except Exception:
                pass

        if color is None:
            return  # скасовано через Esc — нічого показувати не треба

        # Тимчасово показуємо діагностику по кожному кліку — поки налагоджуємо
        # саму механіку запису в поля, без цього кожна невдача виглядала як
        # "взагалі нічого не працює" без жодної зачіпки, що саме зламалось.
        if hwnd is None:
            WinForms.MessageBox.Show(
                u"Колір зчитано: R={0} G={1} B={2}\n\n"
                u"Але hwnd діалогу 'Цвет' порожній — я не знаю, куди його вписувати "
                u"(діалог, вочевидь, зник до кліку).".format(color.R, color.G, color.B),
                u"Піпетка — діагностика")
            return

        ok, details = apply_color_to_dialog(hwnd, color)
        WinForms.MessageBox.Show(
            u"Колір зчитано: R={0} G={1} B={2}  (#{0:02X}{1:02X}{2:02X})\n\n{3}".format(
                color.R, color.G, color.B, details),
            u"Піпетка — діагностика: {0}".format(u"успішно" if ok else u"є проблема"))


_watcher_instance = None


def get_watcher():
    """Повертає єдиний (per pyRevit-сесія) екземпляр спостерігача."""
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = ColorPickerWatcher()
    return _watcher_instance
