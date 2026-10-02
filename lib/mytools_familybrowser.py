# -*- coding: utf-8 -*-
"""
mytools_familybrowser.py — "Диспетчер сімейств" (Family Browser).

Архітектура навмисно проста, щоб не повторити попередню помилку
(повільність через фонові пакетні виклики Revit API, що ставали в
чергу поперед дій користувача, і через синхронне сканування диска
одразу при відкритті вікна):

- При відкритті вікна є РІВНО ОДИН виклик Revit API: зчитати список
  типів, уже завантажених у проєкт (ім'я, категорія, сімейство, id).
  Це дешева операція (без файлів, без прев'ю, без параметрів) —
  секунди, не хвилини, навіть на великому проєкті.
- Фільтр за назвою й категорією працює повністю в пам'яті, без
  жодного звернення до Revit — миттєво.
- Мініатюра запитується ЛИШЕ для картки, яку користувач вибрав —
  один виклик API на клік, ніякого фонового пакетного завантаження.
- Параметри типу читаються теж лише на вибір, одним викликом.
- Розміщення — один виклик API за подвійним кліком або кнопкою.

Бібліотеки .rfa на диску — окремий, другорядний режим (перемикач
зверху). Диск НІКОЛИ не сканується при відкритті вікна — лише коли
користувач явно перемкнеться на "З папок" або натисне "Оновити".
"""
import os
import re
import json
import codecs
import shutil
import time

import clr
clr.AddReference(u"System.Windows.Forms")
clr.AddReference(u"System.Drawing")

from System import Environment, IntPtr, Int64
from System.Environment import SpecialFolder
import System.Windows.Forms as WinForms
from System.Windows.Forms import (
    Form, Label, Button, TextBox, ComboBox, ListView, View, ImageList,
    ListViewItem, FormStartPosition, FolderBrowserDialog,
    DialogResult, DockStyle, AnchorStyles, Timer, ComboBoxStyle, ColorDepth
)
from System.Drawing import (
    Color, Font, FontStyle, Size, Bitmap, Graphics, SolidBrush, Pen,
    StringFormat, StringAlignment, RectangleF
)
from System.Drawing.Drawing2D import SmoothingMode
from System.Diagnostics import Process, ProcessStartInfo

from Autodesk.Revit.DB import (
    Transaction, BuiltInParameter, StorageType, IFamilyLoadOptions,
    FilteredElementCollector, FamilySymbol, ElementId, CategoryType
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, IDropHandler, UIApplication
from Autodesk.Revit.Exceptions import OperationCanceledException
from System.Collections.Generic import List

from mytools_updater import load_settings, save_settings

# ────────────────────────────────────────────────────────────────────
# Палітра — та сама, що і в 01_Utils.stack/Settings.pushbutton
# ────────────────────────────────────────────────────────────────────
BG        = Color.FromArgb(245, 245, 248)
ACCENT    = Color.FromArgb(0, 112, 200)
LIGHT     = Color.FromArgb(110, 110, 130)
SEP_COLOR = Color.FromArgb(205, 205, 215)

BACKUP_RE = re.compile(r'^.*\.\d{3,5}\.rfa$', re.IGNORECASE)
PREVIEW_PREFETCH_LIMIT = 100   # авто-довантаження мініатюр — не більше N видимих карток
MAX_LIST_ITEMS = 400

SRC_PROJECT, SRC_FILES = 0, 1


# ════════════════════════════════════════════════════════════════════
# Спільне
# ════════════════════════════════════════════════════════════════════
def _eid(value):
    """ElementId(int) неоднозначний для IronPython у цій версії Revit —
    є перевантаження й під BuiltInParameter/BuiltInCategory. Явний Int64
    знімає неоднозначність."""
    return ElementId(Int64(value))


def _eid_int(eid):
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def _lib_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _thumb_ps1_path():
    return os.path.join(_lib_dir(), u"mytools_thumbnail.ps1")


def _cache_dir():
    d = os.path.join(
        Environment.GetFolderPath(SpecialFolder.ApplicationData),
        u"pyRevit", u"Extensions", u"MyTools.extension", u"fb_thumb_cache")
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
    except Exception:
        pass
    return d


def get_library_paths():
    s = load_settings()
    return [p for p in s.get(u'family_browser_paths', []) if p]


def add_library_path(path):
    s = load_settings()
    paths = s.get(u'family_browser_paths', [])
    if path not in paths:
        paths.append(path)
    s[u'family_browser_paths'] = paths
    save_settings(s)


def _make_placeholder_bitmap(size=96):
    bmp = Bitmap(size, size)
    g = Graphics.FromImage(bmp)
    try:
        g.SmoothingMode = SmoothingMode.AntiAlias
        g.Clear(Color.White)
        pen = Pen(Color.FromArgb(190, 190, 200), 1.5)
        try:
            g.DrawRectangle(pen, 5, 3, size - 12, size - 8)
        finally:
            pen.Dispose()
        font = Font(u"Segoe UI", max(7.0, size / 9.0), FontStyle.Bold)
        brush = SolidBrush(Color.FromArgb(150, 150, 165))
        try:
            sf = StringFormat()
            sf.Alignment = StringAlignment.Center
            sf.LineAlignment = StringAlignment.Center
            g.DrawString(u".RFA", font, brush, RectangleF(0, 0, size, size), sf)
        finally:
            font.Dispose()
            brush.Dispose()
    finally:
        g.Dispose()
    return bmp


_PLACEHOLDER = [None]


def _cached_placeholder():
    if _PLACEHOLDER[0] is None:
        _PLACEHOLDER[0] = _make_placeholder_bitmap(96)
    return _PLACEHOLDER[0]


def _display_value(fp):
    try:
        st = fp.StorageType
        if st == StorageType.String:
            return fp.AsString() or u""
        if st == StorageType.Integer:
            sv = fp.AsValueString()
            return sv if sv is not None else unicode(fp.AsInteger())
        if st == StorageType.Double:
            sv = fp.AsValueString()
            return sv if sv is not None else unicode(fp.AsDouble())
        if st == StorageType.ElementId:
            sv = fp.AsValueString()
            if sv:
                return sv
            eid = fp.AsElementId()
            return unicode(_eid_int(eid)) if eid else u""
    except Exception:
        pass
    return u""


# ════════════════════════════════════════════════════════════════════
# Сімейства, що вже є в проєкті — один дешевий прохід
# ════════════════════════════════════════════════════════════════════
def _sym_name(sym):
    """Параметр першим: у цьому середовищі FamilySymbol.Name сам по собі
    кидає виняток, а виняток на кожному з тисяч типів — дуже повільно."""
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = sym.get_Parameter(bip)
            if p:
                v = p.AsString()
                if v:
                    return v
        except Exception:
            pass
    try:
        n = sym.Name
        if n:
            return n
    except Exception:
        pass
    return u"(без назви)"


def _fam_name(sym):
    try:
        p = sym.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        if p and p.AsString():
            return p.AsString()
    except Exception:
        pass
    try:
        return sym.Family.Name
    except Exception:
        return u""


def collect_project_types(doc):
    """ОДИН прохід по вже завантажених типах. Жодних файлів, прев'ю чи
    параметрів — лише ім'я/категорія/сімейство/id. Має бути швидко навіть
    на великому проєкті."""
    out = []
    for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            cat_obj = None
            try:
                cat_obj = sym.Category
            except Exception:
                cat_obj = None
            # Анотації (марки, умовні позначення тощо) — не елементи моделі,
            # прибираємо з диспетчера незалежно від мови інтерфейсу Revit.
            if cat_obj is not None:
                try:
                    if cat_obj.CategoryType == CategoryType.Annotation:
                        continue
                except Exception:
                    pass
            cat = u""
            try:
                if cat_obj:
                    cat = cat_obj.Name
            except Exception:
                cat = u""
            out.append({
                u'name':      _sym_name(sym),
                u'family':    _fam_name(sym),
                u'category':  cat or u"(без категорії)",
                u'symbol_id': _eid_int(sym.Id),
                u'source':    u'project',
                u'key':       u'proj:%d' % _eid_int(sym.Id),
            })
        except Exception:
            continue
    out.sort(key=lambda e: (e[u'category'].lower(), e[u'name'].lower()))
    return out


def group_project_families(types):
    """Групує пласкі типи в картки-сімейства: одна картка на сімейство,
    усередині — список його типів. Прев'ю картки — за першим типом."""
    groups = {}
    order = []
    for t in types:
        fam = t[u'family'] or t[u'name']
        gkey = u"%s\x1f%s" % (fam, t[u'category'])
        if gkey not in groups:
            groups[gkey] = {
                u'name':      fam,
                u'category':  t[u'category'],
                u'source':    u'project_family',
                u'key':       u'famgrp:' + gkey,
                u'types':     [],
            }
            order.append(gkey)
        groups[gkey][u'types'].append(t)
    out = []
    for gkey in order:
        g = groups[gkey]
        g[u'types'].sort(key=lambda e: e[u'name'].lower())
        g[u'symbol_id'] = g[u'types'][0][u'symbol_id']
        out.append(g)
    out.sort(key=lambda e: (e[u'category'].lower(), e[u'name'].lower()))
    return out


def get_type_preview(doc, symbol_id, size=96):
    try:
        sym = doc.GetElement(_eid(symbol_id))
        return sym.GetPreviewImage(Size(size, size))
    except Exception:
        return None


def get_type_params(doc, symbol_id):
    try:
        sym = doc.GetElement(_eid(symbol_id))
    except Exception:
        return {}
    params = {}
    for p in sym.Parameters:
        try:
            pname = p.Definition.Name
        except Exception:
            continue
        params[pname] = _display_value(p)
    return params


def _place_symbol(uidoc, sym):
    doc = uidoc.Document
    if not sym.IsActive:
        tx = Transaction(doc, u"Family Browser: активувати тип")
        tx.Start()
        try:
            sym.Activate()
            doc.Regenerate()
            tx.Commit()
        except Exception:
            tx.RollBack()
            raise
    try:
        uidoc.PromptForFamilyInstancePlacement(sym)
    except OperationCanceledException:
        pass


def place_project_symbol(uiapp, symbol_id):
    uidoc = uiapp.ActiveUIDocument
    _place_symbol(uidoc, uidoc.Document.GetElement(_eid(symbol_id)))


class _DropHandler(IDropHandler):
    def Execute(self, uidoc, data):
        sym = uidoc.Document.GetElement(data)
        if sym is not None:
            _place_symbol(uidoc, sym)


# ════════════════════════════════════════════════════════════════════
# Бібліотеки .rfa на диску — другорядний режим, диск не чіпається,
# доки користувач явно не перемкнеться сюди
# ════════════════════════════════════════════════════════════════════
def scan_families(root_paths):
    result = []
    seen = set()
    for root in root_paths:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(u'$') and not d.startswith(u'.')]
            for fn in filenames:
                if not fn.lower().endswith(u'.rfa'):
                    continue
                if BACKUP_RE.match(fn):
                    continue
                full = os.path.join(dirpath, fn)
                if full in seen:
                    continue
                seen.add(full)
                result.append({
                    u'name':   os.path.splitext(fn)[0],
                    u'path':   full,
                    u'folder': os.path.basename(dirpath),
                    u'root':   root,
                    u'source': u'file',
                    u'key':    full,
                })
    result.sort(key=lambda e: e[u'name'].lower())
    return result


class ThumbnailBatch(object):
    """Мініатюра файлу через Windows Shell (той самий прев'ю, що і в
    Провіднику) — окремим процесом, опитується таймером, без Invoke."""
    def __init__(self, entries, size=96, on_ready=None):
        self._entries  = list(entries)
        self._size     = size
        self._on_ready = on_ready
        self._proc     = None
        self._out_dir  = None

    def start(self):
        if not self._entries:
            return False
        try:
            self._out_dir = os.path.join(_cache_dir(), u"batch_%d" % id(self))
            if not os.path.isdir(self._out_dir):
                os.makedirs(self._out_dir)
            req_path = os.path.join(self._out_dir, u"request.json")
            payload = [{u'index': i, u'path': e[u'path']}
                       for i, e in enumerate(self._entries)]
            data = json.dumps(payload, ensure_ascii=False)
            with open(req_path, u'wb') as f:
                f.write(codecs.BOM_UTF8)
                f.write(data.encode(u'utf-8'))

            psi = ProcessStartInfo()
            psi.FileName = u"powershell.exe"
            psi.Arguments = (
                u'-NoProfile -NonInteractive -ExecutionPolicy Bypass '
                u'-WindowStyle Hidden -File "{0}" "{1}" "{2}" {3}'
            ).format(_thumb_ps1_path(), req_path, self._out_dir, self._size)
            psi.UseShellExecute        = False
            psi.CreateNoWindow         = True
            psi.RedirectStandardOutput = True
            psi.RedirectStandardError  = True

            self._proc = Process()
            self._proc.StartInfo = psi
            self._proc.Start()
            return True
        except Exception:
            self._proc = None
            return False

    def poll(self):
        if self._proc is None:
            return True
        try:
            if not self._proc.HasExited:
                return False
        except Exception:
            return True

        results = {}
        try:
            for fn in os.listdir(self._out_dir):
                if fn.lower().endswith(u'.png'):
                    idx = int(os.path.splitext(fn)[0])
                    full = os.path.join(self._out_dir, fn)
                    try:
                        tmp = Bitmap(full)
                        bmp = Bitmap(tmp)
                        tmp.Dispose()
                        results[idx] = bmp
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            shutil.rmtree(self._out_dir, ignore_errors=True)
        except Exception:
            pass

        if self._on_ready:
            self._on_ready(self._entries, results)
        return True


def inspect_family_file(app, path):
    """Типи файлу .rfa (лише для режиму «З папок», на вимогу для однієї
    вибраної картки — файл відкривається й одразу закривається)."""
    fam_doc = None
    try:
        fam_doc = app.OpenDocumentFile(path)
    except Exception as ex:
        return {u'error': unicode(ex)}
    if fam_doc is None:
        return {u'error': u'OpenDocumentFile повернув None'}

    result = {u'types': [], u'params': {}}
    try:
        mgr = fam_doc.FamilyManager
        type_list = list(mgr.Types)
        tx = Transaction(fam_doc, u"Family Browser: читання (без збереження)")
        tx.Start()
        try:
            for ft in type_list:
                tn = None
                try:
                    p = ft.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                    tn = p.AsString() if p else None
                except Exception:
                    tn = None
                if not tn:
                    try:
                        tn = ft.Name
                    except Exception:
                        tn = None
                tn = tn or u"(без назви)"
                try:
                    mgr.CurrentType = ft
                except Exception:
                    continue
                params = {}
                for fp in mgr.Parameters:
                    try:
                        params[fp.Definition.Name] = _display_value(fp)
                    except Exception:
                        continue
                result[u'types'].append(tn)
                result[u'params'][tn] = params
        finally:
            tx.RollBack()
    except Exception as ex:
        result[u'error'] = unicode(ex)
    finally:
        try:
            fam_doc.Close(False)
        except Exception:
            pass
    return result


def load_family_into_project(doc, path):
    class _Loader(IFamilyLoadOptions):
        def OnFamilyFound(self, familyInUse, overwriteParameterValues):
            return True, True

        def OnSharedFamilyFound(self, sharedFamily, familyInUse, source,
                                 overwriteParameterValues):
            from Autodesk.Revit.DB import FamilySource
            return True, FamilySource.Family, True

    tx = Transaction(doc, u"Family Browser: завантажити сімейство")
    tx.Start()
    try:
        ok = doc.LoadFamily(path, _Loader())
        tx.Commit()
        return bool(ok)
    except Exception:
        try:
            tx.RollBack()
        except Exception:
            pass
        raise


# ════════════════════════════════════════════════════════════════════
# ExternalEvent — усі виклики Revit API з немодального вікна йдуть сюди.
# Обробляємо СТРОГО одну задачу за Execute, щоб дія користувача ніколи
# не опинялась позаду накопиченої фонової роботи.
# ════════════════════════════════════════════════════════════════════
class _ApiHandler(IExternalEventHandler):
    def __init__(self, queue):
        self._queue = queue
        self.event = None   # виставляється одразу після ExternalEvent.Create

    def Execute(self, uiapp):
        if not self._queue:
            return
        fn = self._queue.pop(0)
        try:
            fn(uiapp)
        except Exception as ex:
            try:
                WinForms.MessageBox.Show(
                    unicode(ex), u"MyTools \u2014 Диспетчер сімейств",
                    WinForms.MessageBoxButtons.OK, WinForms.MessageBoxIcon.Error)
            except Exception:
                pass
        # Якщо під час обробки додались ще задачі (або вони вже чекали),
        # самі просимо ще один цикл — інакше черга може застрягнути, бо
        # повторний Raise() під час обробки першого є no-op.
        if self._queue and self.event is not None:
            self.event.Raise()

    def GetName(self):
        return u"MyTools Family Browser"


class _Win32Wrapper(WinForms.IWin32Window):
    def __init__(self, handle):
        self._handle = handle

    @property
    def Handle(self):
        return self._handle


# ════════════════════════════════════════════════════════════════════
# Головне вікно
# ════════════════════════════════════════════════════════════════════
class FamilyBrowserForm(Form):
    def __init__(self):
        super(FamilyBrowserForm, self).__init__()

        self._api_queue = []
        _handler = _ApiHandler(self._api_queue)
        self._ext_event = ExternalEvent.Create(_handler)
        _handler.event = self._ext_event

        self._project_types   = []
        self._project_families = []
        self._flat_types      = False   # False = групувати за сімействами (за замовчуванням)
        self._file_entries   = []
        self._shown          = []
        self._thumb_cache    = {}
        self._params_cache   = {}
        self._file_inspect   = {}
        self._selected       = None
        self._source_mode    = SRC_PROJECT
        self._batch          = None
        self._files_scanned  = False
        self._thumb_none     = set()   # ключі, для яких прев'ю точно немає — не повторюємо
        self._preview_inflight = set() # ключі, запит на які вже в дорозі
        self._last_top_index = -1

        self.Text = u"MyTools \u2014 Диспетчер сімейств"
        self.Width  = 860
        self.Height = 640
        self.MinimumSize = Size(600, 440)
        self.StartPosition = FormStartPosition.CenterScreen
        self.BackColor = BG
        self.Font = Font(u"Segoe UI", 9)

        self._build_ui()

        self._timer = Timer()
        self._timer.Interval = 150
        self._timer.Tick += self._on_timer
        self._timer.Start()
        self.FormClosing += self._on_closing

        self.lbl_status.Text = u"Читання типів проєкту…"
        self._run_api(self._collect_project)

    # -------------------------------------------------------------
    def _run_api(self, fn, front=False):
        if front:
            self._api_queue.insert(0, fn)
        else:
            self._api_queue.append(fn)
        self._ext_event.Raise()

    # -------------------------------------------------------------
    # UI
    # -------------------------------------------------------------
    def _build_ui(self):
        top = WinForms.Panel()
        top.Dock = DockStyle.Top
        top.Height = 42
        top.BackColor = BG
        self.Controls.Add(top)

        self.cmb_source = ComboBox()
        self.cmb_source.DropDownStyle = ComboBoxStyle.DropDownList
        self.cmb_source.SetBounds(8, 7, 120, 26)
        self.cmb_source.Items.Add(u"У проєкті")
        self.cmb_source.Items.Add(u"З папок")
        self.cmb_source.SelectedIndex = 0
        self.cmb_source.SelectedIndexChanged += self._on_source_changed
        top.Controls.Add(self.cmb_source)

        lbl_cat = Label()
        lbl_cat.Text = u"Категорія:"
        lbl_cat.SetBounds(136, 12, 66, 20)
        top.Controls.Add(lbl_cat)

        self.cmb_category = ComboBox()
        self.cmb_category.DropDownStyle = ComboBoxStyle.DropDownList
        self.cmb_category.SetBounds(202, 7, 170, 26)
        self.cmb_category.SelectedIndexChanged += self._on_filter_changed
        top.Controls.Add(self.cmb_category)

        lbl_search = Label()
        lbl_search.Text = u"Пошук:"
        lbl_search.SetBounds(360, 12, 45, 20)
        top.Controls.Add(lbl_search)

        self.txt_search = TextBox()
        self.txt_search.SetBounds(408, 7, 180, 26)
        self.txt_search.TextChanged += self._on_filter_changed
        top.Controls.Add(self.txt_search)

        self.chk_flat = WinForms.CheckBox()
        self.chk_flat.Text = u"Типи окремо"
        self.chk_flat.SetBounds(598, 10, 118, 22)
        self.chk_flat.Checked = False
        self.chk_flat.CheckedChanged += self._on_flat_changed
        top.Controls.Add(self.chk_flat)

        btn_refresh = Button()
        btn_refresh.Text = u"\u21bb"
        btn_refresh.SetBounds(722, 7, 34, 26)
        btn_refresh.FlatStyle = WinForms.FlatStyle.Flat
        btn_refresh.Click += self._on_refresh_click
        top.Controls.Add(btn_refresh)

        self.lbl_count = Label()
        self.lbl_count.SetBounds(764, 12, 90, 20)
        self.lbl_count.ForeColor = LIGHT
        top.Controls.Add(self.lbl_count)

        self.image_list = ImageList()
        self.image_list.ImageSize  = Size(96, 96)
        self.image_list.ColorDepth = ColorDepth.Depth32Bit

        self.list_view = ListView()
        self.list_view.Dock = DockStyle.Fill
        self.list_view.View = View.LargeIcon
        self.list_view.LargeImageList = self.image_list
        self.list_view.MultiSelect  = False
        self.list_view.HideSelection = False
        self.list_view.BackColor = Color.White
        self.list_view.SelectedIndexChanged += self._on_selection_changed
        self.list_view.DoubleClick += lambda s, e: self._do_action()
        self.list_view.ItemDrag += self._on_item_drag
        self.Controls.Add(self.list_view)
        self.list_view.BringToFront()

        bottom = WinForms.Panel()
        bottom.Dock = DockStyle.Bottom
        bottom.Height = 200
        bottom.BackColor = BG
        self.Controls.Add(bottom)

        sep = WinForms.Panel()
        sep.Dock = DockStyle.Top
        sep.Height = 1
        sep.BackColor = SEP_COLOR
        bottom.Controls.Add(sep)

        # тип (лише для режиму "З папок" — у файлу кілька типів)
        self.lbl_type = Label()
        self.lbl_type.Text = u"Тип сімейства:"
        self.lbl_type.SetBounds(8, 12, 100, 20)
        bottom.Controls.Add(self.lbl_type)

        self.cmb_type = ComboBox()
        self.cmb_type.DropDownStyle = ComboBoxStyle.DropDownList
        self.cmb_type.SetBounds(112, 9, 260, 24)
        self.cmb_type.SelectedIndexChanged += self._on_type_changed
        bottom.Controls.Add(self.cmb_type)

        self.btn_action = Button()
        self.btn_action.Text = u"Розмістити"
        self.btn_action.SetBounds(384, 8, 170, 26)
        self.btn_action.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_action.BackColor = ACCENT
        self.btn_action.ForeColor = Color.White
        self.btn_action.Enabled = False
        self.btn_action.Click += lambda s, e: self._do_action()
        bottom.Controls.Add(self.btn_action)

        self.lbl_status = Label()
        self.lbl_status.SetBounds(8, 40, 820, 18)
        self.lbl_status.ForeColor = LIGHT
        bottom.Controls.Add(self.lbl_status)

        lbl_params = Label()
        lbl_params.Text = u"Параметри:"
        lbl_params.SetBounds(8, 62, 100, 20)
        bottom.Controls.Add(lbl_params)

        self.grid_params = ListView()
        self.grid_params.SetBounds(8, 86, 828, 106)
        self.grid_params.Anchor = (AnchorStyles.Top | AnchorStyles.Left |
                                    AnchorStyles.Right | AnchorStyles.Bottom)
        self.grid_params.View = View.Details
        self.grid_params.FullRowSelect = True
        self.grid_params.GridLines = True
        self.grid_params.Columns.Add(u"Параметр", 300)
        self.grid_params.Columns.Add(u"Значення", 440)
        bottom.Controls.Add(self.grid_params)

        self._set_mode_ui(SRC_PROJECT)

    def _set_mode_ui(self, mode):
        is_files = (mode == SRC_FILES)
        self.chk_flat.Visible = not is_files
        self.btn_action.Text = u"Завантажити в проєкт" if is_files else u"Розмістити"
        self._set_type_row_visible(is_files)

    def _set_type_row_visible(self, flag):
        self.lbl_type.Visible = flag
        self.cmb_type.Visible = flag

    def _on_flat_changed(self, sender, e):
        self._flat_types = self.chk_flat.Checked
        self._apply_filter()

    # -------------------------------------------------------------
    # Джерело / категорія / пошук — усе в пам'яті, без API
    # -------------------------------------------------------------
    def _on_source_changed(self, sender, e):
        self._source_mode = self.cmb_source.SelectedIndex
        self._set_mode_ui(self._source_mode)
        if self._source_mode == SRC_FILES and not self._files_scanned:
            self._scan_files()
        self._reload_category_list()
        self._apply_filter()

    def _on_refresh_click(self, sender, e):
        if self._source_mode == SRC_PROJECT:
            self.lbl_status.Text = u"Читання типів проєкту…"
            self._run_api(self._collect_project)
        else:
            self._scan_files()

    def _scan_files(self):
        self.lbl_status.Text = u"Сканування папок…"
        WinForms.Application.DoEvents()
        paths = get_library_paths()
        if not paths:
            r = WinForms.MessageBox.Show(
                u"Бібліотеки ще не додано. Обрати папку зараз?",
                u"Диспетчер сімейств",
                WinForms.MessageBoxButtons.YesNo, WinForms.MessageBoxIcon.Question)
            if r == DialogResult.Yes:
                self._pick_folder()
            self.lbl_status.Text = u""
            return
        self._file_entries = scan_families(paths)
        self._files_scanned = True
        self.lbl_status.Text = u""
        self._reload_category_list()
        self._apply_filter()

    def _pick_folder(self):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Оберіть папку з бібліотекою сімейств Revit"
        if dlg.ShowDialog() == DialogResult.OK and dlg.SelectedPath:
            add_library_path(dlg.SelectedPath)
            self._scan_files()

    def _collect_project(self, uiapp):
        self._project_types = collect_project_types(uiapp.ActiveUIDocument.Document)
        self._project_families = group_project_families(self._project_types)
        self.lbl_status.Text = u""
        self._reload_category_list()
        self._apply_filter()

    def _current_pool(self):
        if self._source_mode == SRC_PROJECT:
            return self._project_types if self._flat_types else self._project_families
        return self._file_entries

    def _reload_category_list(self):
        cats = set()
        for en in self._current_pool():
            c = en.get(u'category') or en.get(u'folder')
            if c:
                cats.add(c)
        cur = self.cmb_category.SelectedItem
        self.cmb_category.Items.Clear()
        self.cmb_category.Items.Add(u"Усі категорії")
        for c in sorted(cats, key=lambda s: s.lower()):
            self.cmb_category.Items.Add(c)
        idx = 0
        if cur:
            for i in range(self.cmb_category.Items.Count):
                if self.cmb_category.Items[i] == cur:
                    idx = i
                    break
        self.cmb_category.SelectedIndex = idx

    def _on_filter_changed(self, sender, e):
        self._apply_filter()

    def _apply_filter(self):
        pool = self._current_pool()
        cat = self.cmb_category.SelectedItem
        if cat and cat != u"Усі категорії":
            key = u'category' if self._source_mode == SRC_PROJECT else u'folder'
            pool = [en for en in pool if en.get(key) == cat]

        q = (self.txt_search.Text or u"").strip().lower()
        if q:
            if self._source_mode == SRC_PROJECT and self._flat_types:
                pool = [en for en in pool
                        if q in en[u'name'].lower() or q in en[u'family'].lower()]
            elif self._source_mode == SRC_PROJECT:
                pool = [en for en in pool
                        if q in en[u'name'].lower()
                        or any(q in t[u'name'].lower() for t in en[u'types'])]
            else:
                pool = [en for en in pool if q in en[u'name'].lower()]

        truncated = False
        if len(pool) > MAX_LIST_ITEMS:
            pool = pool[:MAX_LIST_ITEMS]
            truncated = True

        self._shown = pool
        self._populate_list_view(truncated)
        self._last_top_index = -1   # форсуємо перевірку видимої області на наступному тіку

    def _populate_list_view(self, truncated):
        self.list_view.BeginUpdate()
        self.list_view.Items.Clear()
        self.image_list.Images.Clear()
        for i, en in enumerate(self._shown):
            bmp = self._thumb_cache.get(en[u'key']) or _cached_placeholder()
            self.image_list.Images.Add(bmp)
            label = en[u'name']
            if en[u'source'] == u'project_family' and len(en[u'types']) > 1:
                label = u"{0}\n({1} \u0442\u0438\u043f\u0456\u0432)".format(
                    en[u'name'], len(en[u'types']))
            elif self._source_mode == SRC_PROJECT and en.get(u'family') and en[u'family'] != en[u'name']:
                label = u"{0}\n{1}".format(en[u'name'], en[u'family'])
            item = ListViewItem(label)
            item.ImageIndex = i
            item.Tag = en
            self.list_view.Items.Add(item)
        self.list_view.EndUpdate()
        self.lbl_count.Text = u"{0}{1}".format(len(self._shown), u"+" if truncated else u"")

    # -------------------------------------------------------------
    # Вибір картки
    # -------------------------------------------------------------
    def _on_selection_changed(self, sender, e):
        if self.list_view.SelectedItems.Count == 0:
            self._selected = None
            self.cmb_type.Items.Clear()
            self.grid_params.Items.Clear()
            self.btn_action.Enabled = False
            self._set_type_row_visible(False)
            return
        entry = self.list_view.SelectedItems[0].Tag
        self._selected = entry
        self.btn_action.Enabled = True

        if (entry[u'source'] in (u'project', u'project_family')
                and entry[u'key'] not in self._thumb_cache
                and entry[u'key'] not in self._thumb_none
                and entry[u'key'] not in self._preview_inflight):
            # Клікнута картка — пріоритетно, одразу, без черги видимого діапазону.
            self._preview_inflight.add(entry[u'key'])
            self._run_api(lambda uiapp: self._do_project_preview(uiapp, entry), front=True)
        # Мініатюри файлів (і решта видимих карток проєкту) підхоплює
        # _maybe_fetch_visible() на наступному тіку таймера — обраний
        # елемент вже видимий на екрані, тож потрапить у той самий запит.

        if entry[u'source'] == u'project':
            self._set_type_row_visible(False)
            self.cmb_type.Items.Clear()
            self.grid_params.Items.Clear()
            params = self._params_cache.get(entry[u'key'])
            if params is None:
                self.lbl_status.Text = u"Читання параметрів…"
                self._run_api(lambda uiapp: self._do_read_project_params(uiapp, entry), front=True)
            else:
                self._show_params(params)
        elif entry[u'source'] == u'project_family':
            # Кілька типів у сімействі — той самий вибір типу, що й для
            # файлів: список унизу, параметри показуються для вибраного.
            self._set_type_row_visible(True)
            self.cmb_type.Items.Clear()
            self.grid_params.Items.Clear()
            for t in entry[u'types']:
                self.cmb_type.Items.Add(t[u'name'])
            if self.cmb_type.Items.Count > 0:
                self.cmb_type.SelectedIndex = 0   # викличе _on_type_changed
        else:
            self._set_type_row_visible(True)
            self._load_file_types(entry)

    def _do_read_project_params(self, uiapp, type_entry):
        params = get_type_params(uiapp.ActiveUIDocument.Document, type_entry[u'symbol_id'])
        self._params_cache[type_entry[u'key']] = params
        self.lbl_status.Text = u""
        self._maybe_show_type_params(type_entry[u'key'], params)

    def _maybe_show_type_params(self, type_key, params):
        """Показує params, лише якщо вони й досі стосуються того, що зараз
        обрано (картка або тип у випадному списку могли змінитись, поки
        йшов запит до Revit API)."""
        entry = self._selected
        if entry is None:
            return
        if entry[u'source'] == u'project' and entry[u'key'] == type_key:
            self._show_params(params)
        elif entry[u'source'] == u'project_family':
            t = next((t for t in entry[u'types'] if t[u'key'] == type_key), None)
            if t is not None and self.cmb_type.SelectedItem == t[u'name']:
                self._show_params(params)

    def _load_file_types(self, entry):
        info = self._file_inspect.get(entry[u'key'])
        if info is not None:
            self._show_file_info(entry, info)
            return
        self.lbl_status.Text = u"Читання типів/параметрів…"
        self._run_api(lambda uiapp: self._do_inspect_file(uiapp, entry))

    def _do_inspect_file(self, uiapp, entry):
        info = inspect_family_file(uiapp.Application, entry[u'path'])
        self._file_inspect[entry[u'key']] = info
        self.lbl_status.Text = u""
        if self._selected is not None and self._selected[u'key'] == entry[u'key']:
            self._show_file_info(entry, info)

    def _show_file_info(self, entry, info):
        self.cmb_type.Items.Clear()
        self.grid_params.Items.Clear()
        if info.get(u'error'):
            self.lbl_status.Text = u"Помилка читання: {0}".format(info[u'error'])
            return
        for tn in info.get(u'types', []):
            self.cmb_type.Items.Add(tn)
        if self.cmb_type.Items.Count > 0:
            self.cmb_type.SelectedIndex = 0

    def _on_type_changed(self, sender, e):
        entry = self._selected
        if not entry:
            return
        tn = self.cmb_type.SelectedItem
        if not tn:
            return
        if entry[u'source'] == u'file':
            info = self._file_inspect.get(entry[u'key'])
            if not info:
                return
            self._show_params(info.get(u'params', {}).get(tn, {}))
        elif entry[u'source'] == u'project_family':
            t = next((t for t in entry[u'types'] if t[u'name'] == tn), None)
            if t is None:
                return
            params = self._params_cache.get(t[u'key'])
            if params is None:
                self.grid_params.Items.Clear()
                self.lbl_status.Text = u"Читання параметрів…"
                self._run_api(lambda uiapp: self._do_read_project_params(uiapp, t), front=True)
            else:
                self._show_params(params)

    def _show_params(self, params):
        self.grid_params.BeginUpdate()
        self.grid_params.Items.Clear()
        for pname in sorted(params.keys(), key=lambda s: s.lower()):
            item = ListViewItem(pname)
            item.SubItems.Add(params[pname])
            self.grid_params.Items.Add(item)
        self.grid_params.EndUpdate()

    # -------------------------------------------------------------
    # Прев'ю на вимогу — лише для щойно вибраної картки
    # -------------------------------------------------------------
    def _on_timer(self, sender, e):
        if self._batch is not None:
            self._batch.poll()
        self._maybe_fetch_visible()

    def _do_project_preview(self, uiapp, entry):
        bmp = get_type_preview(uiapp.ActiveUIDocument.Document, entry[u'symbol_id'], 96)
        self._preview_inflight.discard(entry[u'key'])
        if bmp is not None:
            self._thumb_cache[entry[u'key']] = bmp
            self._refresh_one(entry[u'key'])
        else:
            self._thumb_none.add(entry[u'key'])

    def _visible_indices(self):
        """Індекси карток, що реально видно у ListView зараз (+невеликий
        запас на 1 ряд вперед). ListView.TopItem у режимі LargeIcon у цій
        збірці WinForms (.NET 10 / Revit 2026) кидає виняток замість
        None — тому визначаємо діапазон лінійним проходом за Bounds, без
        TopItem. Items[i].Bounds — дешева операція (геометрія, без API),
        тож прохід навіть по кількасот елементах відбувається миттєво."""
        if not self._shown:
            return []
        client_h = self.list_view.ClientSize.Height
        n = len(self._shown)
        out = []
        overscan_rows_left = 1  # ще один ряд нижче видимої межі про запас
        i = 0
        while i < n:
            try:
                rect = self.list_view.Items[i].Bounds
            except Exception:
                break
            if rect.Bottom < 0:
                # картка вище видимої області (прокручено вниз) — пропускаємо
                i += 1
                continue
            if rect.Top > client_h:
                if overscan_rows_left <= 0:
                    break
                overscan_rows_left -= 1
            out.append(i)
            i += 1
            if len(out) > 200:   # запобіжник
                break
        return out

    def _maybe_fetch_visible(self):
        if not self._shown:
            return
        visible = self._visible_indices()
        if not visible:
            return
        top_idx = visible[0]
        if top_idx == self._last_top_index and self._preview_inflight:
            return   # нічого не прокручували, попередній запит ще в дорозі
        self._last_top_index = top_idx

        need = []
        for idx in visible:
            en = self._shown[idx]
            key = en[u'key']
            if (key not in self._thumb_cache and key not in self._thumb_none
                    and key not in self._preview_inflight):
                need.append(en)
        if not need:
            return

        if self._source_mode == SRC_PROJECT:
            for en in need:
                self._preview_inflight.add(en[u'key'])
            self._run_api(lambda uiapp, batch=need: self._do_project_preview_batch(uiapp, batch))
        else:
            if self._batch is None:
                for en in need:
                    self._preview_inflight.add(en[u'key'])
                batch = ThumbnailBatch(need, size=96, on_ready=self._on_thumb_batch_ready)
                if batch.start():
                    self._batch = batch
                else:
                    for en in need:
                        self._preview_inflight.discard(en[u'key'])

    def _do_project_preview_batch(self, uiapp, entries):
        doc = uiapp.ActiveUIDocument.Document
        t0 = time.time()
        remaining = list(entries)
        updated = []
        while remaining and (time.time() - t0) < 0.4:
            en = remaining.pop(0)
            key = en[u'key']
            if key in self._thumb_cache:
                self._preview_inflight.discard(key)
                continue
            bmp = get_type_preview(doc, en[u'symbol_id'], 96)
            self._preview_inflight.discard(key)
            if bmp is not None:
                self._thumb_cache[key] = bmp
                updated.append(key)
            else:
                self._thumb_none.add(key)
        if updated:
            self._refresh_many(updated)
        if remaining:
            self._run_api(lambda uiapp: self._do_project_preview_batch(uiapp, remaining))

    def _on_thumb_batch_ready(self, entries, results):
        self._batch = None
        updated = []
        for i, en in enumerate(entries):
            key = en[u'key']
            self._preview_inflight.discard(key)
            bmp = results.get(i)
            if bmp is not None:
                self._thumb_cache[key] = bmp
                updated.append(key)
            else:
                self._thumb_none.add(key)
        if updated:
            self._refresh_many(updated)

    def _refresh_one(self, key):

        self._refresh_many([key])

    def _refresh_many(self, keys):
        keyset = set(keys)
        changed = False
        for i, en in enumerate(self._shown):
            if en[u'key'] in keyset and i < self.image_list.Images.Count:
                self.image_list.Images[i] = self._thumb_cache[en[u'key']]
                changed = True
        if changed:
            self.list_view.BeginUpdate()
            lst = self.list_view.LargeImageList
            self.list_view.LargeImageList = None
            self.list_view.LargeImageList = lst
            self.list_view.EndUpdate()

    # -------------------------------------------------------------
    # Дія
    # -------------------------------------------------------------
    def _do_action(self):
        entry = self._selected
        if not entry:
            return
        if entry[u'source'] == u'project':
            self.lbl_status.Text = u"Розміщення: оберіть точку у вікні Revit (Esc — скасувати)…"
            self._run_api(lambda uiapp: self._do_place(uiapp, entry[u'symbol_id']))
        elif entry[u'source'] == u'project_family':
            tn = self.cmb_type.SelectedItem
            t = next((t for t in entry[u'types'] if t[u'name'] == tn), None) \
                or entry[u'types'][0]
            self.lbl_status.Text = (
                u"Розміщення \u00AB{0}\u00BB: оберіть точку у вікні Revit "
                u"(Esc — скасувати)…").format(t[u'name'])
            self._run_api(lambda uiapp: self._do_place(uiapp, t[u'symbol_id']))
        else:
            self.lbl_status.Text = u"Завантаження сімейства…"
            self._run_api(lambda uiapp: self._do_load_file(uiapp, entry))

    def _do_place(self, uiapp, sid):
        try:
            place_project_symbol(uiapp, sid)
        finally:
            self.lbl_status.Text = u""

    def _do_load_file(self, uiapp, entry):
        try:
            load_family_into_project(uiapp.ActiveUIDocument.Document, entry[u'path'])
            self.lbl_status.Text = u"Завантажено: {0}".format(entry[u'name'])
        except Exception:
            self.lbl_status.Text = u""
            raise
        self._project_types = collect_project_types(uiapp.ActiveUIDocument.Document)
        self._project_families = group_project_families(self._project_types)

    # -------------------------------------------------------------
    # Перетягування у 3D / план / фасад / розріз
    # -------------------------------------------------------------
    def _on_item_drag(self, sender, e):
        try:
            item = e.Item
            entry = item.Tag
            item.Selected = True
            if entry[u'source'] == u'file':
                files = List[str]()
                files.Add(entry[u'path'])
                UIApplication.DoDragDrop(files)
            elif entry[u'source'] == u'project_family':
                tn = self.cmb_type.SelectedItem if self._selected is entry else None
                t = next((t for t in entry[u'types'] if t[u'name'] == tn), None) \
                    or entry[u'types'][0]
                UIApplication.DoDragDrop(_eid(t[u'symbol_id']), _DropHandler())
            else:
                UIApplication.DoDragDrop(_eid(entry[u'symbol_id']), _DropHandler())
        except Exception as ex:
            self.lbl_status.Text = u"Перетягування не вдалося: {0}".format(ex)

    # -------------------------------------------------------------
    def _on_closing(self, sender, e):
        try:
            self._timer.Stop()
        except Exception:
            pass
        try:
            del self._api_queue[:]
        except Exception:
            pass
        try:
            shutil.rmtree(_cache_dir(), ignore_errors=True)
        except Exception:
            pass


def show_family_browser(uiapp=None):
    form = FamilyBrowserForm()
    owner = None
    try:
        proc = Process.GetCurrentProcess()
        handle = proc.MainWindowHandle
        if handle != IntPtr.Zero:
            owner = _Win32Wrapper(handle)
    except Exception:
        owner = None
    if owner:
        form.Show(owner)
    else:
        form.Show()
    return form
