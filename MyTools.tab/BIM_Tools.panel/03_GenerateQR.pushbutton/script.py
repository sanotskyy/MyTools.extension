# -*- coding: utf-8 -*-
"""
GenerateQR_to_ImageParam.py
pyRevit | IronPython 2.7 | Revit 2024+

Логіка (3 окремі кроки):
  1. Генерація PNG  — завантажує QR через QuickChart API, зберігає у вибрану папку
  2. Імпорт PNG     — створює ImageType у проекті (поза транзакцією!)
  3. Присвоєння     — записує ImageType у параметр Image (в транзакції)
"""

import os
import re
import json
import codecs
import traceback
import tempfile
import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from Autodesk.Revit.DB import (
    Material, Wall, Floor, Ceiling, RoofBase,
    FilteredElementCollector,
    BuiltInParameter,
    StorageType,
    Transaction,
    ImageTypeOptions,
    ImageType,
    ImageTypeSource,
    ElementId,
    ViewSchedule,
    IFamilyLoadOptions,
    FamilyInstance,
    AssemblyInstance,
)

import System.Windows.Forms as WinForms
from System.Drawing import Color, Font, FontStyle
from System.Windows.Forms import (
    Form, Label, TextBox, Button, CheckBox,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
    FormStartPosition, ComboBox, ComboBoxStyle,
    FolderBrowserDialog, SendKeys,
)
import System.Net as Net
import System.IO as IO
import System

from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


# ============================================================
#  УТИЛІТИ
# ============================================================

def eid_int(element_id):
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|\s]', u"_", (name or u"")).strip(u"_")[:60]


def get_element_name(el):
    try:
        name = el.Name
        if name:
            return name
    except Exception:
        pass
    try:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p and p.AsString():
            return p.AsString()
    except Exception:
        pass
    return u"Element_{}".format(eid_int(el.Id))


def _read_param_val(p):
    if not p:
        return None
    st = int(p.StorageType)
    _str = int(StorageType.String)
    _dbl = int(StorageType.Double)
    _int = int(StorageType.Integer)
    if st == _str:
        v = p.AsString()
        return v.strip() if v and v.strip() else None
    if st == _dbl:
        try:
            from Autodesk.Revit.DB import UnitUtils
            c = UnitUtils.ConvertFromInternalUnits(p.AsDouble(), p.GetUnitTypeId())
            r = u"{:.4f}".format(c).rstrip('0').rstrip('.')
            return r if r else None
        except Exception:
            r = u"{:.4f}".format(p.AsDouble()).rstrip('0').rstrip('.')
            return r if r else None
    if st == _int:
        return u"{}".format(p.AsInteger())
    return None


def get_string_param_value(el, param_name):
    # Матеріальний параметр
    MAT_PREFIX = u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "
    if param_name.startswith(MAT_PREFIX):
        real_name = param_name[len(MAT_PREFIX):]
        try:
            for mat_id in el.GetMaterialIds(False):
                mat = doc.GetElement(mat_id)
                if mat:
                    p = mat.LookupParameter(real_name)
                    v = _read_param_val(p)
                    if v:
                        return v
        except Exception:
            pass
        return None

    p = el.LookupParameter(param_name)
    v = _read_param_val(p)
    if v:
        return v
    try:
        type_el = doc.GetElement(el.GetTypeId())
        if type_el:
            p = type_el.LookupParameter(param_name)
            v = _read_param_val(p)
            if v:
                return v
    except Exception:
        pass
    return None


def get_any_param_as_string(el, param_name):
    for target in [el, None]:
        if target is None:
            try:
                target = doc.GetElement(el.GetTypeId())
            except Exception:
                break
            if target is None:
                break
        p = target.LookupParameter(param_name)
        if p:
            st = int(p.StorageType)
            if st == int(StorageType.String):
                v = p.AsString()
            elif st == int(StorageType.Integer):
                v = str(p.AsInteger())
            elif st == int(StorageType.Double):
                v = p.AsValueString() or str(round(p.AsDouble(), 4))
            else:
                v = p.AsValueString()
            if v and v.strip():
                return v.strip()
    return None


# ── helpers: мітки (екземпляр) / (тип) ──────────────────────────────────────

def _parse_param_label(label):
    """'Name (екземпляр)' -> (name, 'instance'),  'Name (тип)' -> (name, 'type')"""
    if label.endswith(u" (екземпляр)"):
        return label[:-len(u" (екземпляр)")], u"instance"
    if label.endswith(u" (тип)"):
        return label[:-len(u" (тип)")], u"type"
    return label, u"instance"

def _labeled(name, scope):
    suffix = u" (екземпляр)" if scope == u"instance" else u" (тип)"
    return name + suffix

def _collect_labeled(elements, limit, filter_fn, priority):
    inst, typ = set(), set()
    for el in elements[:limit]:
        try:
            for p in el.Parameters:
                if filter_fn(p) and p.Definition.Name:
                    inst.add(p.Definition.Name)
        except Exception:
            pass
        try:
            te = doc.GetElement(el.GetTypeId())
            if te:
                for p in te.Parameters:
                    if filter_fn(p) and p.Definition.Name:
                        typ.add(p.Definition.Name)
        except Exception:
            pass
    result, seen = [], set()
    for pool_order in [(priority, inst, u"instance"), (priority, typ, u"type")]:
        pr, pool, scope = pool_order
        for n in pr:
            if n in pool:
                lbl = _labeled(n, scope)
                if lbl not in seen:
                    result.append(lbl); seen.add(lbl)
    for n in sorted(inst | typ):
        if n in priority:
            continue
        for scope, pool in ((u"instance", inst), (u"type", typ)):
            if n in pool:
                lbl = _labeled(n, scope)
                if lbl not in seen:
                    result.append(lbl); seen.add(lbl)
    return result

# ─────────────────────────────────────────────────────────────────────────────

def collect_string_params(elements, limit=60):
    return _collect_labeled(elements, limit,
        lambda p: int(p.StorageType) == int(StorageType.String),
        [u"URL", u"Hyperlink", u"Посилання", u"Link", u"Web"])

def collect_all_params(elements, limit=60):
    return _collect_labeled(elements, limit,
        lambda p: True,
        [u"Mark", u"Type Mark", u"Марка", u"Name", u"Description"])

def collect_image_params(elements, limit=60):
    return _collect_labeled(elements, limit,
        lambda p: int(p.StorageType) == int(StorageType.ElementId),
        [u"Image", u"Зображення", u"QR", u"QR Code", u"Photo"])


# ============================================================
#  КРОК 1: Генерація QR PNG
# ============================================================

def generate_qr_png(url, file_path, size_px=300):
    try:
        api_url = (
            u"https://quickchart.io/qr?text={0}&size={1}&margin=2&ecLevel=M&format=png"
            .format(System.Uri.EscapeDataString(url), size_px)
        )
        wc = Net.WebClient()
        wc.DownloadFile(api_url, file_path)
        info = IO.FileInfo(file_path)
        return info.Exists and info.Length > 100
    except Exception:
        return False


# ============================================================
#  КРОК 2: Імпорт PNG як ImageType (поза транзакцією)
# ============================================================

def find_existing_image_type(png_path):
    search_name = os.path.splitext(os.path.basename(png_path))[0].lower()
    try:
        for img in FilteredElementCollector(doc).OfClass(ImageType):
            try:
                if (img.Name or u"").lower() == search_name:
                    return img.Id
                try:
                    img_path = img.Path or u""
                    if os.path.splitext(os.path.basename(img_path))[0].lower() == search_name:
                        return img.Id
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass
    return None


def import_png_as_image_type(png_path, overwrite=False):
    """
    Повертає (ElementId, None) або (None, error_str).
    Сама відкриває транзакцію — викликати поза іншою транзакцією.
    """
    existing_id = find_existing_image_type(png_path)
    if existing_id is not None:
        if not overwrite:
            return existing_id, None
        # Видаляємо старий в окремій транзакції
        try:
            tx_del = Transaction(doc, u"QR: видалити старий ImageType")
            tx_del.Start()
            doc.Delete(existing_id)
            tx_del.Commit()
        except Exception:
            try:
                tx_del.RollBack()
            except Exception:
                pass

    try:
        tx = Transaction(doc, u"QR: імпорт ImageType")
        tx.Start()
        # IronPython передає unicode; явно кастуємо до System.String
        path_str = System.String(png_path)
        opts     = ImageTypeOptions(path_str, False, ImageTypeSource.Import)
        img_type = ImageType.Create(doc, opts)
        if img_type:
            tx.Commit()
            return img_type.Id, None
        tx.RollBack()
        return None, u"ImageType.Create() повернув None"
    except Exception as ex:
        try:
            tx.RollBack()
        except Exception:
            pass
        return None, u"{}".format(ex)


# ============================================================
#  КРОК 3а: Запис у параметр ТИПУ через EditFamily
# ============================================================

def set_images_for_family(family, png_path, replace_existing, param_name=None):
    """
    1. Відкриває fam_doc через EditFamily
    2. Знаходить параметр Image в FamilyManager
    3. Імпортує PNG в fam_doc (окрема транзакція)
    4. Записує ImageId в mgr.CurrentType (окрема транзакція)
    5. LoadFamily назад у проект (замінити версію і значення параметрів)
    6. Закриває fam_doc
    Повертає: 'ok' / 'already' / 'error: ...'
    """
    fam_doc = doc.EditFamily(family)
    if not fam_doc:
        return u'error: EditFamily повернув None'

    try:
        mgr = fam_doc.FamilyManager

        # Крок 1 — знаходимо параметр Image
        img_fp = None
        if param_name:
            # Шукаємо ТІЛЬКИ вказаний параметр
            for fp in mgr.Parameters:
                if fp.Definition.Name == param_name:
                    img_fp = fp
                    break
            if not img_fp:
                # Параметр не знайдено в FamilyManager (shared param доданий в проекті)
                # Закриваємо сімейство і сигналізуємо про прямий запис у тип проекту
                fam_doc.Close(False)
                return u'__use_project_type__'
        else:
            # Якщо param_name не вказано — шукаємо вбудований ALL_MODEL_TYPE_IMAGE
            img_fp = mgr.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
            if not img_fp:
                for fp in mgr.Parameters:
                    if fp.Definition.Name in (u'Изображение типоразмера', u'Type Image'):
                        img_fp = fp
                        break
            if not img_fp:
                available = u", ".join(fp.Definition.Name for fp in mgr.Parameters)
                fam_doc.Close(False)
                return u'error: параметр зображення не знайдено. Доступні: {}'.format(available)

        # Крок 2 — перевірка replace_existing
        if not replace_existing:
            cur_val = mgr.AsElementId(img_fp)
            if cur_val and cur_val != ElementId.InvalidElementId:
                fam_doc.Close(False)
                return u'already'

        # Крок 3 — імпортуємо PNG в fam_doc
        if not os.path.isfile(png_path):
            fam_doc.Close(False)
            return u'error: PNG не знайдено: {}'.format(png_path)

        img_id = None
        # Перевіряємо чи вже є
        norm_path = os.path.normcase(os.path.normpath(png_path))
        for ex_img in FilteredElementCollector(fam_doc).OfClass(ImageType).ToElements():
            try:
                if os.path.normcase(os.path.normpath(ex_img.Path)) == norm_path:
                    img_id = ex_img.Id
                    break
            except Exception:
                pass

        if not img_id:
            tx_imp = Transaction(fam_doc, u"QR: імпорт PNG")
            tx_imp.Start()
            try:
                opts   = ImageTypeOptions(System.String(png_path), False, ImageTypeSource.Import)
                new_img = ImageType.Create(fam_doc, opts)
                if not new_img:
                    tx_imp.RollBack()
                    fam_doc.Close(False)
                    return u'error: ImageType.Create повернув None'
                img_id = new_img.Id
                tx_imp.Commit()
            except Exception as ex:
                try:
                    tx_imp.RollBack()
                except Exception:
                    pass
                fam_doc.Close(False)
                return u'error: імпорт PNG: {}'.format(ex)

        # Крок 4 — записуємо в параметр типу
        tx_set = Transaction(fam_doc, u"QR: записати зображення типу")
        tx_set.Start()
        try:
            mgr.Set(img_fp, img_id)
            tx_set.Commit()
        except Exception as ex:
            try:
                tx_set.RollBack()
            except Exception:
                pass
            fam_doc.Close(False)
            return u'error: mgr.Set: {}'.format(ex)

        # Крок 5 — завантажуємо назад у проект
        class FamilyLoader(IFamilyLoadOptions):
            def OnFamilyFound(self, familyInUse, overwriteParameterValues):
                return True, True
            def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
                from Autodesk.Revit.DB import FamilySource
                return True, FamilySource.Family, True

        fam_doc.LoadFamily(doc, FamilyLoader())
        fam_doc.Close(False)
        return u'ok'

    except Exception:
        err_msg = traceback.format_exc()
        try:
            fam_doc.Close(False)
        except Exception:
            pass
        return u'error: {}'.format(err_msg[:300])


# ============================================================
#  КРОК 3: Присвоєння (в транзакції)
# ============================================================

def assign_image_param(el, param_name, image_type_id):
    """Повертає True або рядок з описом помилки.
    Якщо param_name починається з 'Матеріал: ' — записує в параметр матеріалів елемента.
    """
    # Матеріальний параметр
    if param_name.startswith(u'\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: '):
        real_name = param_name[len(u'\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: '):]
        try:
            for mat_id in el.GetMaterialIds(False):
                mat = doc.GetElement(mat_id)
                if mat:
                    p = mat.LookupParameter(real_name)
                    if p and int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                        try:
                            p.Set(image_type_id)
                            return True
                        except Exception as ex:
                            return u"Set mat param: {}".format(ex)
        except Exception as ex:
            return u"GetMaterialIds: {}".format(ex)
        return u"\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440 '{}' \u043d\u0435 \u0437\u043d\u0430\u0439\u0434\u0435\u043d\u043e \u0432 \u043c\u0430\u0442\u0435\u0440\u0456\u0430\u043b\u0430\u0445".format(real_name)

    p = el.LookupParameter(param_name)
    if p is not None:
        if int(p.StorageType) != int(StorageType.ElementId):
            return u"StorageType={}".format(p.StorageType)
        if p.IsReadOnly:
            return u"instance IsReadOnly"
        try:
            p.Set(image_type_id)
            return True
        except Exception as ex:
            return u"Set instance: {}".format(ex)
    try:
        te = doc.GetElement(el.GetTypeId())
        if te:
            p = te.LookupParameter(param_name)
            if p is not None:
                if int(p.StorageType) != int(StorageType.ElementId):
                    return u"StorageType={}".format(p.StorageType)
                if p.IsReadOnly:
                    return u"type IsReadOnly"
                try:
                    p.Set(image_type_id)
                    return True
                except Exception as ex:
                    return u"Set type: {}".format(ex)
    except Exception:
        pass
    return u"параметр '{}' не знайдено".format(param_name)



# ============================================================
# ============================================================
#  ШАБЛОНИ
# ============================================================

def _get_templates_path():
    return os.path.join(
        System.Environment.GetFolderPath(System.Environment.SpecialFolder.ApplicationData),
        u"pyRevit", u"Extensions", u"MyTools.extension", u"qr_templates.json"
    )

TEMPLATES_PATH = _get_templates_path()


def load_templates():
    try:
        if os.path.exists(TEMPLATES_PATH):
            with codecs.open(TEMPLATES_PATH, u"r", encoding=u"utf-8") as f:
                data = json.loads(f.read())
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def save_templates(templates):
    try:
        folder = os.path.dirname(TEMPLATES_PATH)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with codecs.open(TEMPLATES_PATH, u"w", encoding=u"utf-8") as f:
            f.write(json.dumps(templates, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False


# ============================================================
#  КОМБОБОКС З ЖИВОЮ ФІЛЬТРАЦІЄЮ
# ============================================================

class FilteredComboBox(ComboBox):
    """
    ComboBox з фільтрацією списку при введенні тексту.
    При кожній зміні тексту залишає в Items тільки ті, що містять введений рядок.
    ESC — скидає фільтр і повертає повний список.
    """
    def __init__(self, all_items):
        super(FilteredComboBox, self).__init__()
        self._all_items   = list(all_items)
        self._updating    = False
        self.DropDownStyle = ComboBoxStyle.DropDown
        self.Font          = Font(u"Segoe UI", 9)
        self.AutoCompleteMode   = WinForms.AutoCompleteMode.None
        self.AutoCompleteSource = WinForms.AutoCompleteSource.None
        self._fill(self._all_items)
        self.DrawMode  = WinForms.DrawMode.OwnerDrawFixed
        self.DrawItem += self._on_draw_item
        self.TextChanged += self._on_text_changed
        self.KeyDown     += self._on_key_down

    def _fill(self, items):
        self.BeginUpdate()
        self.Items.Clear()
        for it in items:
            self.Items.Add(it)
        self.EndUpdate()

    def _on_draw_item(self, sender, e):
        """Малює елементи списку завжди чорним — незалежно від ForeColor поля (placeholder сірий)."""
        import System.Drawing as Drawing
        if e.Index < 0:
            return
        e.DrawBackground()
        item_text  = self.Items[e.Index]
        text_color = Drawing.Color.FromArgb(40, 40, 40)
        e.Graphics.DrawString(
            item_text,
            e.Font,
            Drawing.SolidBrush(text_color),
            e.Bounds
        )
        e.DrawFocusRectangle()

    def _on_text_changed(self, sender, e):
        if self._updating:
            return
        self._updating = True
        try:
            typed = self.Text
            cur   = len(typed)

            if not typed.strip():
                self._fill(self._all_items)
            else:
                low     = typed.lower()
                matched = [x for x in self._all_items if low in x.lower()]
                self._fill(matched)

            self.Text            = typed
            self.SelectionStart  = cur
            self.SelectionLength = 0

            if self.Items.Count > 0 and typed.strip():
                if not self.DroppedDown:
                    self.DroppedDown = True
            elif self.Items.Count == 0:
                if self.DroppedDown:
                    self.DroppedDown = False
        finally:
            self._updating = False

    def _on_key_down(self, sender, e):
        import System.Windows.Forms as _wf
        if e.KeyCode == _wf.Keys.Escape:
            self._updating = True
            try:
                self._fill(self._all_items)
                self.Text            = u""
                self.SelectionStart  = 0
                self.DroppedDown     = False
            finally:
                self._updating = False
            e.Handled = True


# ============================================================
#  UI ФОРМА
# ============================================================

class _InputDialog(Form):
    """Простий діалог введення рядка (для назви шаблону)."""
    def __init__(self, title, prompt, default=u""):
        super(_InputDialog, self).__init__()
        self.value = u""
        self.Text            = title
        self.Width           = 380
        self.Height          = 140
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.StartPosition   = FormStartPosition.CenterParent
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = Color.FromArgb(245, 245, 248)

        lbl = Label()
        lbl.Text = prompt
        lbl.Font = Font(u"Segoe UI", 9)
        lbl.SetBounds(14, 14, 340, 18)
        self.Controls.Add(lbl)

        self._tb = TextBox()
        self._tb.Font = Font(u"Segoe UI", 9)
        self._tb.SetBounds(14, 36, 340, 24)
        self._tb.Text = default
        self._tb.SelectAll()
        self.Controls.Add(self._tb)

        btn_ok = Button()
        btn_ok.Text = u"OK"
        btn_ok.Font = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_ok.SetBounds(14, 68, 80, 28)
        btn_ok.BackColor = Color.FromArgb(0, 112, 200)
        btn_ok.ForeColor = Color.White
        btn_ok.FlatStyle = WinForms.FlatStyle.Flat
        btn_ok.FlatAppearance.BorderSize = 0
        btn_ok.DialogResult = WinForms.DialogResult.OK
        btn_ok.Click += self._on_ok
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text = u"Скасувати"
        btn_cancel.Font = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(104, 68, 80, 28)
        btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = WinForms.DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

    def _on_ok(self, sender, e):
        self.value = self._tb.Text
        self.DialogResult = WinForms.DialogResult.OK


class QRForm(Form):
    def __init__(self, sched_name, url_params, name_params, image_params, has_mat=False):
        self._has_mat = has_mat
        super(QRForm, self).__init__()
        self._result_ok  = False
        self.url_param   = u""
        self.name_param  = u""
        self.prefix      = u"QR"
        self.suffix      = u""
        self.image_param = u""
        try:
            _dp = doc.PathName
            if _dp:
                self.save_folder = os.path.join(os.path.dirname(_dp), u"QR_codes")
            else:
                raise ValueError()
        except Exception:
            self.save_folder = os.path.join(
                System.Environment.GetFolderPath(System.Environment.SpecialFolder.Desktop),
                u"QR_codes")
        self.qr_size     = 300
        self.overwrite    = False
        self.delete_old   = False
        self.param_mode   = u"instance"  # 'instance' або 'type'
        self._templates   = load_templates()

        self.Text            = u"Генерація QR-кодів → параметр Image"
        self.Width           = 520
        self.Height          = 100
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.BackColor       = Color.FromArgb(245, 245, 248)

        self._build(sched_name, url_params, name_params, image_params)

    def _lbl(self, text, x, y, w=464, bold=False):
        l = Label()
        l.Text = text
        l.Font = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
        l.ForeColor = Color.FromArgb(40, 40, 40)
        l.SetBounds(x, y, w, 17)
        return l

    def _sep(self, y):
        s = Label()
        s.SetBounds(18, y, 464, 1)
        s.BackColor = Color.FromArgb(205, 205, 215)
        return s

    def _combo(self, x, y, w, items, default=None):
        cb = FilteredComboBox(items)
        cb.SetBounds(x, y, w, 26)
        if default and items:
            low = default.lower()
            # шукаємо точний збіг імені (без суфіксу екземпляр/тип)
            for i, it in enumerate(items):
                name, _ = _parse_param_label(it)
                if name.lower() == low:
                    cb._updating = True
                    cb.Text = it
                    cb._updating = False
                    break
        return cb

    def _tb(self, x, y, w, text=u""):
        tb = TextBox()
        tb.SetBounds(x, y, w, 24)
        tb.Font = Font(u"Segoe UI", 9)
        tb.Text = text
        return tb

    def _build(self, sched_name, url_params, name_params, image_params):
        pad = 18
        y   = 14

        # Заголовок
        h = Label()
        h.Text = (sched_name or u"Специфікація")
        h.Font = Font(u"Segoe UI", 10, FontStyle.Bold)
        h.ForeColor = Color.FromArgb(20, 20, 20)
        h.SetBounds(pad, y, 464, 22)
        self.Controls.Add(h)
        y += 28; self.Controls.Add(self._sep(y)); y += 12

        # 1 — URL
        self.Controls.Add(self._lbl(u"1.  Параметр з посиланням (URL):", pad, y, bold=True))
        y += 20
        self.cb_url = self._combo(pad, y, 464, url_params, default=u"URL")
        self.Controls.Add(self.cb_url)
        y += 28
        if self._has_mat:
            lbl_url_note = Label()
            lbl_url_note.Text      = u"ℹ  Параметри з префіксом 'Матеріал: ' — з матеріалу несучої конструкції"
            lbl_url_note.Font      = Font(u"Segoe UI", 8)
            lbl_url_note.ForeColor = Color.FromArgb(80, 80, 180)
            lbl_url_note.SetBounds(pad, y, 464, 16)
            self.Controls.Add(lbl_url_note)
            y += 18
        y += 4; self.Controls.Add(self._sep(y)); y += 12

        # 2 — Ім'я файлу
        self.Controls.Add(self._lbl(u"2.  Ім'я файлу:   {префікс}_{параметр}_{суфікс}.png", pad, y, bold=True))
        y += 20
        self.Controls.Add(self._lbl(u"Параметр:", pad, y + 3, w=80))
        self.cb_name = self._combo(pad + 84, y, 220, name_params, default=u"Маркировка типоразмера")
        self.Controls.Add(self.cb_name)
        y += 32
        self.Controls.Add(self._lbl(u"Префікс:", pad, y + 3, w=70))
        self.tb_prefix = self._tb(pad + 74, y, 120, u"QR")
        self.Controls.Add(self.tb_prefix)
        self.Controls.Add(self._lbl(u"Суфікс:", pad + 212, y + 3, w=60))
        self.tb_suffix = self._tb(pad + 276, y, 120, u"")
        self.Controls.Add(self.tb_suffix)
        y += 32; self.Controls.Add(self._sep(y)); y += 12

        # 3 — Папка
        self.Controls.Add(self._lbl(u"3.  Папка для збереження PNG:", pad, y, bold=True))
        y += 20
        self.tb_folder = self._tb(pad, y, 368, self.save_folder)
        self.Controls.Add(self.tb_folder)
        btn_br = Button()
        btn_br.Text = u"Огляд…"
        btn_br.Font = Font(u"Segoe UI", 9)
        btn_br.SetBounds(pad + 374, y - 1, 90, 26)
        btn_br.FlatStyle = WinForms.FlatStyle.Flat
        btn_br.Click += self._on_browse
        self.Controls.Add(btn_br)
        y += 32; self.Controls.Add(self._sep(y)); y += 12

        # 4 — Параметр Image
        self.Controls.Add(self._lbl(u"4.  Параметр Image (куди записати QR):", pad, y, bold=True))
        y += 20
        self.cb_img = self._combo(pad, y, 464, image_params)
        self.Controls.Add(self.cb_img)
        y += 28
        if self._has_mat:
            lbl_img_note = Label()
            lbl_img_note.Text      = u"ℹ  Параметри з префіксом 'Матеріал: ' — записуються в матеріал несучої конструкції"
            lbl_img_note.Font      = Font(u"Segoe UI", 8)
            lbl_img_note.ForeColor = Color.FromArgb(80, 80, 180)
            lbl_img_note.SetBounds(pad, y, 464, 16)
            self.Controls.Add(lbl_img_note)
            y += 18
        y += 4; self.Controls.Add(self._sep(y)); y += 12

        self.Controls.Add(self._lbl(u"5.  Параметри:", pad, y, bold=True))
        y += 20
        self.Controls.Add(self._lbl(u"Розмір QR (px, 100–600):", pad, y + 3, w=200))
        self.tb_size = self._tb(pad + 204, y, 70, u"300")
        self.Controls.Add(self.tb_size)
        y += 30
        self.chk_overwrite = CheckBox()
        self.chk_overwrite.Text = u"Замінити існуючі зображення (якщо QR вже є в проекті)"
        self.chk_overwrite.Font = Font(u"Segoe UI", 9)
        self.chk_overwrite.ForeColor = Color.FromArgb(160, 70, 0)
        self.chk_overwrite.SetBounds(pad, y, 464, 20)
        self.Controls.Add(self.chk_overwrite)
        y += 26
        self.chk_delete_old = CheckBox()
        self.chk_delete_old.Text = u"Видалити з проекту старі зображення з такою ж назвою перед імпортом"
        self.chk_delete_old.Font = Font(u"Segoe UI", 9)
        self.chk_delete_old.ForeColor = Color.FromArgb(160, 70, 0)
        self.chk_delete_old.SetBounds(pad, y, 464, 20)
        self.Controls.Add(self.chk_delete_old)
        y += 28; self.Controls.Add(self._sep(y)); y += 10

        # Інфо
        note = Label()
        note.Text = u"PNG генерується через QuickChart API (потрібен інтернет)."
        note.Font = Font(u"Segoe UI", 8)
        note.ForeColor = Color.FromArgb(110, 110, 130)
        note.SetBounds(pad, y, 464, 16)
        self.Controls.Add(note)
        y += 24

        # Шаблони
        self.Controls.Add(self._sep(y)); y += 10
        self.Controls.Add(self._lbl(u"Шаблони налаштувань:", pad, y, bold=True))
        y += 20
        tpl_names = sorted(self._templates.keys())
        self.combo_tpl = FilteredComboBox(tpl_names)
        self.combo_tpl.SetBounds(pad, y, 200, 26)
        self.combo_tpl._updating = True
        self.combo_tpl.Text = u"<вибрати шаблон>"
        self.combo_tpl.ForeColor = Color.FromArgb(160, 160, 160)
        self.combo_tpl._updating = False
        self.combo_tpl.TextChanged += self._on_tpl_text_changed
        btn_tpl_load = Button()
        btn_tpl_load.Text      = u"Завантажити"
        btn_tpl_load.Font      = Font(u"Segoe UI", 9)
        btn_tpl_load.SetBounds(pad + 206, y - 1, 90, 26)
        btn_tpl_load.FlatStyle = WinForms.FlatStyle.Flat
        btn_tpl_load.Click    += self._on_load_template
        btn_tpl_save = Button()
        btn_tpl_save.Text      = u"Зберегти"
        btn_tpl_save.Font      = Font(u"Segoe UI", 9)
        btn_tpl_save.SetBounds(pad + 305, y - 1, 80, 26)
        btn_tpl_save.FlatStyle = WinForms.FlatStyle.Flat
        btn_tpl_save.Click    += self._on_save_template
        btn_tpl_del = Button()
        btn_tpl_del.Text       = u"Видалити"
        btn_tpl_del.Font       = Font(u"Segoe UI", 9)
        btn_tpl_del.ForeColor  = Color.FromArgb(180, 40, 40)
        btn_tpl_del.SetBounds(pad + 394, y - 1, 74, 26)
        btn_tpl_del.FlatStyle  = WinForms.FlatStyle.Flat
        btn_tpl_del.Click     += self._on_delete_template
        for ctrl in [self.combo_tpl, btn_tpl_load, btn_tpl_save, btn_tpl_del]:
            self.Controls.Add(ctrl)
        y += 34; self.Controls.Add(self._sep(y)); y += 10

        # Кнопки
        btn_run = Button()
        btn_run.Text = u"Згенерувати QR-коди"
        btn_run.Font = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_run.SetBounds(pad, y, 220, 32)
        btn_run.BackColor = Color.FromArgb(0, 112, 200)
        btn_run.ForeColor = Color.White
        btn_run.FlatStyle = WinForms.FlatStyle.Flat
        btn_run.FlatAppearance.BorderSize = 0
        btn_run.Click += self._on_run
        self.Controls.Add(btn_run)

        btn_cancel = Button()
        btn_cancel.Text = u"Скасувати"
        btn_cancel.Font = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(386, y, 100, 32)
        btn_cancel.FlatStyle = WinForms.FlatStyle.Flat
        btn_cancel.Click += lambda s, e: self.Close()
        self.Controls.Add(btn_cancel)

        self.Height = y + 90

    # ── Шаблони ────────────────────────────────────────────────────────────

    def _fill_templates(self):
        names = sorted(self._templates.keys())
        self.combo_tpl._all_items = names
        self.combo_tpl._fill(names)
        self.combo_tpl._updating = True
        self.combo_tpl.Text = u"<вибрати шаблон>"
        self.combo_tpl.ForeColor = Color.FromArgb(160, 160, 160)
        self.combo_tpl._updating = False

    def _on_tpl_text_changed(self, sender, e):
        if self.combo_tpl.Text.strip() in (u"<вибрати шаблон>", u""):
            self.combo_tpl.ForeColor = Color.FromArgb(160, 160, 160)
        else:
            self.combo_tpl.ForeColor = Color.FromArgb(40, 40, 40)

    def _get_current_tpl_data(self):
        return {
            u"url_param":   self.cb_url.Text.strip(),
            u"name_param":  self.cb_name.Text.strip(),
            u"prefix":      self.tb_prefix.Text,
            u"suffix":      self.tb_suffix.Text,
            u"image_param": self.cb_img.Text.strip(),
            u"qr_size":     self.tb_size.Text.strip(),
            u"overwrite":   self.chk_overwrite.Checked,
            u"delete_old":  self.chk_delete_old.Checked,
            u"save_folder": self.tb_folder.Text.strip(),
        }

    def _apply_tpl_data(self, tpl):
        def _set_combo(cb, val):
            if not val:
                return
            low = val.lower()
            for it in cb._all_items:
                if it.lower() == low:
                    cb._updating = True; cb.Text = it; cb._updating = False
                    return
            name_only, _ = _parse_param_label(val)
            for it in cb._all_items:
                n, _ = _parse_param_label(it)
                if n.lower() == name_only.lower():
                    cb._updating = True; cb.Text = it; cb._updating = False
                    return
            cb._updating = True; cb.Text = val; cb._updating = False

        _set_combo(self.cb_url,  tpl.get(u"url_param",  u""))
        _set_combo(self.cb_name, tpl.get(u"name_param", u""))
        _set_combo(self.cb_img,  tpl.get(u"image_param", u""))
        self.tb_prefix.Text = tpl.get(u"prefix", u"QR")
        self.tb_suffix.Text = tpl.get(u"suffix", u"")
        self.tb_size.Text   = str(tpl.get(u"qr_size", u"300"))
        self.chk_overwrite.Checked  = bool(tpl.get(u"overwrite",  False))
        self.chk_delete_old.Checked = bool(tpl.get(u"delete_old", False))
        sf = tpl.get(u"save_folder", u"")
        if sf:
            self.tb_folder.Text = sf

    def _on_load_template(self, sender, e):
        name = self.combo_tpl.Text.strip()
        if not name or name == u"<вибрати шаблон>":
            MessageBox.Show(u"Оберіть шаблон зі списку.", u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        tpl = self._templates.get(name)
        if not tpl:
            MessageBox.Show(u"Шаблон '{}' не знайдено.".format(name), u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        self._apply_tpl_data(tpl)

    def _on_save_template(self, sender, e):
        suggested = self.combo_tpl.Text.strip()
        if not suggested or suggested == u"<вибрати шаблон>":
            suggested = u"Новий шаблон"
        dlg = _InputDialog(u"Назва шаблону", u"Введіть назву:", suggested)
        if dlg.ShowDialog() != WinForms.DialogResult.OK:
            return
        name = dlg.value.strip()
        if not name:
            return
        if name in self._templates:
            res = MessageBox.Show(
                u"Шаблон '{}' вже існує. Перезаписати?".format(name),
                u"Перезаписати?",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question)
            if res != WinForms.DialogResult.Yes:
                return
        self._templates[name] = self._get_current_tpl_data()
        if save_templates(self._templates):
            self._fill_templates()
            self.combo_tpl._updating = True
            self.combo_tpl.Text = name
            self.combo_tpl.ForeColor = Color.FromArgb(40, 40, 40)
            self.combo_tpl._updating = False
            MessageBox.Show(u"Шаблон '{}' збережено.".format(name), u"Шаблони",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
        else:
            MessageBox.Show(u"Помилка збереження.", u"Шаблони",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    def _on_delete_template(self, sender, e):
        name = self.combo_tpl.Text.strip()
        if not name or name == u"<вибрати шаблон>" or name not in self._templates:
            MessageBox.Show(u"Оберіть шаблон для видалення.", u"Шаблони",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        res = MessageBox.Show(
            u"Видалити шаблон '{}'?".format(name),
            u"Видалити?",
            MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        if res == WinForms.DialogResult.Yes:
            del self._templates[name]
            save_templates(self._templates)
            self._fill_templates()

    def _on_browse(self, sender, e):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Оберіть папку для збереження PNG"
        dlg.SelectedPath = self.tb_folder.Text
        if dlg.ShowDialog() == WinForms.DialogResult.OK:
            self.tb_folder.Text = dlg.SelectedPath

    def _on_run(self, sender, e):
        ok = True
        def mark(ctrl, err):
            ctrl.BackColor = Color.FromArgb(255, 180, 180) if err else Color.White

        mark(self.cb_url,    not self.cb_url.Text.strip());    ok = ok and bool(self.cb_url.Text.strip())
        mark(self.cb_name,   not self.cb_name.Text.strip());   ok = ok and bool(self.cb_name.Text.strip())
        mark(self.tb_folder, not self.tb_folder.Text.strip()); ok = ok and bool(self.tb_folder.Text.strip())
        mark(self.cb_img,    not self.cb_img.Text.strip());    ok = ok and bool(self.cb_img.Text.strip())
        try:
            sz = int(self.tb_size.Text.strip())
            if sz < 100 or sz > 600: raise ValueError()
            mark(self.tb_size, False)
        except Exception:
            mark(self.tb_size, True); ok = False

        if not ok:
            MessageBox.Show(u"Перевірте виділені поля.", u"Перевірка",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        url_name,  _         = _parse_param_label(self.cb_url.Text.strip())
        name_name, _         = _parse_param_label(self.cb_name.Text.strip())
        img_name,  img_scope = _parse_param_label(self.cb_img.Text.strip())
        self.url_param   = url_name
        self.name_param  = name_name
        self.prefix      = sanitize_filename(self.tb_prefix.Text)
        self.suffix      = sanitize_filename(self.tb_suffix.Text)
        self.save_folder = self.tb_folder.Text.strip()
        self.image_param = img_name
        self.qr_size     = int(self.tb_size.Text.strip())
        self.overwrite    = self.chk_overwrite.Checked
        self.delete_old   = self.chk_delete_old.Checked
        self.param_mode   = u"type" if img_scope == u"type" else u"instance"
        self._result_ok  = True
        self.Close()


# ============================================================
#  ГОЛОВНА ЛОГІКА
# ============================================================

def build_filename(frm, el):
    base  = sanitize_filename(get_any_param_as_string(el, frm.name_param) or get_element_name(el))
    parts = [p for p in [frm.prefix, base, frm.suffix] if p]
    return u"_".join(parts) + u".png"


def _is_assembly(el):
    """Повертає True якщо елемент є AssemblyInstance."""
    return isinstance(el, AssemblyInstance)


def _get_structural_material_qr(el):
    """Повертає матеріал несучої конструкції елемента для QR."""
    try:
        from Autodesk.Revit.DB import BuiltInParameter as BIP
        p = el.get_Parameter(BIP.STRUCTURAL_MATERIAL_PARAM)
        if p and p.AsElementId() != ElementId.InvalidElementId:
            return doc.GetElement(p.AsElementId())
    except Exception:
        pass
    try:
        mat_ids = list(el.GetMaterialIds(False))
        if mat_ids:
            return doc.GetElement(mat_ids[0])
    except Exception:
        pass
    return None


def run():
    # ── Збираємо виділені елементи (будь-який вид) ───────────────────────
    sel_ids = list(uidoc.Selection.GetElementIds())
    if not sel_ids:
        forms.alert(u"Немає виділених елементів.", title=u"Увага", warn_icon=True)
        script.exit()

    elements = [e for e in (doc.GetElement(i) for i in sel_ids) if e is not None]

    # ── Визначаємо режим: збірки або сімейства ───────────────────────────
    assemblies = [e for e in elements if _is_assembly(e)]
    families   = [e for e in elements if not _is_assembly(e)]

    if assemblies and families:
        forms.alert(
            u"Виділено одночасно збірки та звичайні елементи.\n"
            u"Будь ласка, виділіть або тільки збірки, або тільки сімейства.",
            title=u"Змішане виділення", warn_icon=True)
        script.exit()

    is_assembly_mode = bool(assemblies)
    elements         = assemblies if is_assembly_mode else families

    # Матеріали елементів (стіни/перекриття)
    _MATERIAL_HOST_TYPES = (Wall, Floor, Ceiling, RoofBase)
    _all_mat = {}
    for el in elements:
        try:
            if isinstance(el, _MATERIAL_HOST_TYPES):
                for mat_id in el.GetMaterialIds(False):
                    if mat_id not in _all_mat:
                        mat = doc.GetElement(mat_id)
                        if mat and isinstance(mat, Material):
                            _all_mat[mat_id] = mat
        except Exception:
            pass
    has_mat = len(_all_mat) > 0

    # ── Для сімейств — перевіряємо що вид є специфікацією ───────────────
    active_view = uidoc.ActiveView
    view_name   = active_view.Name
    if not is_assembly_mode and not isinstance(active_view, ViewSchedule):
        forms.alert(u"Для сімейств активний вид має бути специфікацією.",
                    title=u"Помилка", warn_icon=True)
        script.exit()

    # ── Збираємо доступні параметри ──────────────────────────────────────
    url_params   = collect_string_params(elements)
    name_params  = collect_all_params(elements)
    image_params = collect_image_params(elements)

    # Параметри матеріалів — додаємо до списків
    if has_mat:
        _mat_list = list(_all_mat.values())
        _mat_strings = set()
        _mat_elemids = set()
        _readable_int = set([int(StorageType.String), int(StorageType.Double), int(StorageType.Integer)])
        for mat in _mat_list:
            try:
                for p in list(mat.Parameters):
                    try:
                        st = int(p.StorageType)
                        if st in _readable_int:
                            _mat_strings.add(p.Definition.Name)
                        elif st == int(StorageType.ElementId) and not p.IsReadOnly:
                            _mat_elemids.add(p.Definition.Name)
                    except Exception:
                        continue
            except Exception:
                pass
        # Додаємо до існуючих списків з префіксом
        for n in sorted(_mat_strings):
            lbl = u"Матеріал: " + n
            if lbl not in url_params:
                url_params.append(lbl)
            if lbl not in name_params:
                name_params.append(lbl)
        for n in sorted(_mat_elemids):
            lbl = u"Матеріал: " + n
            if lbl not in image_params:
                image_params.append(lbl)

    if not image_params:
        forms.alert(u"Не знайдено параметрів типу Image (ElementId).",
                    title=u"Параметр Image не знайдено", warn_icon=True)
        script.exit()

    title = (u"[Збірки] " if is_assembly_mode else u"") + view_name
    has_mat = len(_all_mat) > 0
    frm = QRForm(title, url_params, name_params, image_params, has_mat=has_mat)
    frm.ShowDialog()
    if not frm._result_ok:
        script.exit()

    # Створюємо папку
    try:
        if not os.path.isdir(frm.save_folder):
            os.makedirs(frm.save_folder)
    except Exception as ex:
        forms.alert(u"Не вдалось створити папку:\n{}".format(ex),
                    title=u"Помилка папки", warn_icon=True)
        script.exit()

    # ── КРОК 0: Видалення старих зображень з проекту (якщо увімкнено) ───
    if frm.delete_old:
        names_to_delete   = set()
        seen_type_ids_pre = set()
        for el in elements:
            if frm.url_param.startswith(u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "):
                _real_p = frm.url_param[len(u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "):]
                _mat_el = _get_structural_material_qr(el)
                url = get_string_param_value(_mat_el, _real_p) if _mat_el else None
            else:
                url = get_string_param_value(el, frm.url_param)
            if not url or not (u"http" in url or u"." in url):
                continue
            # Для збірок дедуплікація по самому елементу (кожна збірка унікальна)
            if is_assembly_mode:
                dedup_key = eid_int(el.Id)
            else:
                try:
                    dedup_key = eid_int(el.GetTypeId())
                except Exception:
                    dedup_key = None
            if dedup_key is not None and dedup_key in seen_type_ids_pre:
                continue
            if dedup_key is not None:
                seen_type_ids_pre.add(dedup_key)
            fname = build_filename(frm, el)
            names_to_delete.add(os.path.splitext(fname)[0].lower())

        if names_to_delete:
            imgs_to_del = []
            for img in FilteredElementCollector(doc).OfClass(ImageType):
                try:
                    img_name      = (img.Name or u"").lower()
                    img_path_name = os.path.splitext(
                        os.path.basename(img.Path or u""))[0].lower()
                    if img_name in names_to_delete or img_path_name in names_to_delete:
                        imgs_to_del.append(img.Id)
                except Exception:
                    pass
            if imgs_to_del:
                try:
                    tx_del = Transaction(doc, u"QR: видалити старі зображення")
                    tx_del.Start()
                    for del_id in imgs_to_del:
                        try:
                            doc.Delete(del_id)
                        except Exception:
                            pass
                    tx_del.Commit()
                except Exception:
                    try:
                        tx_del.RollBack()
                    except Exception:
                        pass

    # ── КРОК 1: Генерація PNG ────────────────────────────────────────────
    # Збірки: кожна збірка унікальна — без дедуплікації по типу.
    # Сімейства: дедуплікація по type_id (один PNG на тип).
    step1      = []
    skip_count = 0
    errors     = []
    seen_keys  = {}  # type_id/el_id -> png_path

    for el in elements:
        if frm.url_param.startswith(u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "):
            _real_p = frm.url_param[len(u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "):]
            _mat_el = _get_structural_material_qr(el)
            url = get_string_param_value(_mat_el, _real_p) if _mat_el else None
        else:
            url = get_string_param_value(el, frm.url_param)
        if not url or not (u"http" in url or u"." in url):
            skip_count += 1
            continue

        if is_assembly_mode:
            # Збірки: унікальні за екземпляром, дедуплікації немає
            dedup_key = None
        else:
            try:
                dedup_key = eid_int(el.GetTypeId())
            except Exception:
                dedup_key = None

        if dedup_key is not None and dedup_key in seen_keys:
            step1.append((el, seen_keys[dedup_key]))
            continue

        fname    = build_filename(frm, el)
        png_path = os.path.join(frm.save_folder, fname)
        if generate_qr_png(url, png_path, frm.qr_size):
            step1.append((el, png_path))
            if dedup_key is not None:
                seen_keys[dedup_key] = png_path
        else:
            errors.append(u"[{}] {} — не вдалось завантажити QR PNG".format(
                eid_int(el.Id), get_element_name(el)))

    if not step1:
        forms.alert(u"Не вдалось згенерувати жодного QR.\n" + u"\n".join(errors),
                    title=u"Помилка генерації", warn_icon=True)
        script.exit()

    # ── КРОК 2: Імпорт PNG як ImageType ──────────────────────────────────
    # Для збірок — завжди instance-режим (EditFamily недоступний).
    # Для сімейств — залежить від param_mode.
    step2        = []
    ok_count     = 0
    error_ids    = []
    actual_mode  = u"instance" if is_assembly_mode else frm.param_mode

    if actual_mode == u"instance":
        seen_png_img = {}
        for el, png_path in step1:
            if png_path in seen_png_img:
                step2.append((el, seen_png_img[png_path]))
                continue
            img_id, err = import_png_as_image_type(png_path, overwrite=frm.overwrite)
            if img_id is not None:
                seen_png_img[png_path] = img_id
                step2.append((el, img_id))
            else:
                errors.append(u"[{}] {} — імпорт ImageType: {}".format(
                    eid_int(el.Id), get_element_name(el), err))

    # ── КРОК 3: Присвоєння ───────────────────────────────────────────────
    family_map = {}
    if actual_mode == u"type":
        # ── Режим типу: тільки для сімейств, через EditFamily ────────────
        family_map = {}

        # Розділяємо: FamilyInstance → EditFamily, системні → пряме присвоєння
        sys_step1 = []  # (el, png_path) для системних елементів

        for el, png_path in step1:
            if not isinstance(el, FamilyInstance):
                # Системне сімейство (DuctType, FlexDuctType, WallType тощо)
                # не має атрибуту Family — обробляємо окремо через assign_image_param
                sys_step1.append((el, png_path))
                continue
            try:
                fam    = doc.GetElement(el.Symbol.Family.Id)
                fam_id = fam.Id
            except Exception as ex:
                error_ids.append(el.Id)
                errors.append(u"[{}] {} — не вдалось отримати сімейство: {}".format(
                    eid_int(el.Id), get_element_name(el), ex))
                continue
            # Один PNG на сімейство — останній перемагає якщо кілька типів
            family_map[fam_id] = {u'family': fam, u'png_path': png_path}

        _proj_type_families = {}  # fam_id -> {family, png_path} для прямого запису

        for fam_id, data in family_map.items():
            result = set_images_for_family(
                data[u'family'], data[u'png_path'], frm.overwrite, frm.image_param)
            if result == u'ok':
                ok_count += 1
            elif result == u'already':
                errors.append(u"[{}] — вже є, не замінено".format(eid_int(fam_id)))
            elif result == u'__use_project_type__':
                # Параметр не в FamilyManager — запишемо напряму в тип проекту
                _proj_type_families[fam_id] = data
            else:
                errors.append(u"[{}] — {}".format(eid_int(fam_id), result))

        # Прямий запис у тип проекту (для shared params)
        if _proj_type_families:
            # Крок А: завантажуємо ImageType поза транзакцією
            _pt_pairs = []  # (family_symbol, img_id)
            for fam_id, data in _proj_type_families.items():
                png_path = data[u'png_path']
                img_id, err = import_png_as_image_type(png_path, overwrite=frm.overwrite)
                if not img_id:
                    errors.append(u"[{}] ImageType не завантажено: {}".format(
                        eid_int(fam_id), err))
                    continue
                # Знаходимо типи цього сімейства в проекті
                family = data[u'family']
                try:
                    from Autodesk.Revit.DB import FamilySymbol
                    for sym in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
                        if sym.Family.Id == fam_id:
                            _pt_pairs.append((sym, img_id))
                except Exception as ex:
                    errors.append(u"[{}] пошук типів: {}".format(eid_int(fam_id), ex))

            # Крок Б: записуємо в транзакції
            if _pt_pairs:
                _pt_tx = Transaction(doc, u"QR: прямий запис у тип проекту")
                _pt_tx.Start()
                _written_pt = set()
                try:
                    for sym, img_id in _pt_pairs:
                        if sym.Id in _written_pt:
                            continue
                        p = sym.LookupParameter(frm.image_param)
                        if p and not p.IsReadOnly:
                            current = p.AsElementId()
                            if current != ElementId.InvalidElementId and not frm.overwrite:
                                errors.append(u"{} — вже є".format(sym.Name))
                            else:
                                try:
                                    p.Set(img_id)
                                    ok_count += 1
                                    _written_pt.add(sym.Id)
                                except Exception as ex:
                                    errors.append(u"{} — Set: {}".format(sym.Name, ex))
                        else:
                            errors.append(u"{} — параметр '{}' не знайдено".format(
                                sym.Name, frm.image_param))
                    _pt_tx.Commit()
                except Exception as ex:
                    errors.append(u"Транзакція прямого запису: {}".format(ex))
                    try:
                        _pt_tx.RollBack()
                    except Exception:
                        pass

        # Системні елементи в режимі type — завантажуємо ImageType і пишемо в тип
        if sys_step1:
            # Крок А: завантажуємо ImageType поза транзакцією
            _processed_sys_types = {}
            _sys_pairs = []  # (el, img_id)
            for el, png_path in sys_step1:
                try:
                    if png_path in _processed_sys_types:
                        img_id = _processed_sys_types[png_path]
                    else:
                        img_id, _err = import_png_as_image_type(png_path, overwrite=frm.overwrite)
                        _processed_sys_types[png_path] = img_id
                    if not img_id:
                        raise Exception(u"ImageType не завантажено: {}".format(_err))
                    _sys_pairs.append((el, img_id))
                except Exception as ex:
                    error_ids.append(el.Id)
                    errors.append(u"[{}] {} — системний тип (імпорт): {}".format(
                        eid_int(el.Id), get_element_name(el), ex))

            # Крок Б: записуємо параметри в транзакції
            if _sys_pairs:
                _sys_tx = Transaction(doc, u"QR: системні типи — зображення")
                _sys_tx.Start()
                _written_type_ids = set()
                try:
                    for el, img_id in _sys_pairs:
                        try:
                            # Дедублікація по типу
                            type_id = el.GetTypeId()
                            if type_id in _written_type_ids:
                                ok_count += 1
                                continue
                            result = assign_image_param(el, frm.image_param, img_id)
                            if result is True:
                                ok_count += 1
                                _written_type_ids.add(type_id)
                            else:
                                error_ids.append(el.Id)
                                errors.append(u"[{}] {} — {}".format(
                                    eid_int(el.Id), get_element_name(el), result))
                        except Exception as ex:
                            error_ids.append(el.Id)
                            errors.append(u"[{}] {} — системний тип (запис): {}".format(
                                eid_int(el.Id), get_element_name(el), ex))
                    _sys_tx.Commit()
                except Exception:
                    try:
                        _sys_tx.RollBack()
                    except Exception:
                        pass

    else:
        # ── Режим екземпляра: збірки і сімейства (instance) ─────────────
        tx = Transaction(doc, u"QR: призначити зображення")
        tx.Start()
        try:
            for el, img_id in step2:
                result = assign_image_param(el, frm.image_param, img_id)
                if result is True:
                    ok_count += 1
                else:
                    error_ids.append(el.Id)
                    errors.append(u"[{}] {} — присвоєння: {}".format(
                        eid_int(el.Id), get_element_name(el), result))
            tx.Commit()
        except Exception:
            try:
                tx.RollBack()
            except Exception:
                pass
            forms.alert(u"Критична помилка:\n\n" + traceback.format_exc(), title=u"Помилка")
            script.exit()

    if error_ids:
        from System.Collections.Generic import List
        uidoc.Selection.SetElementIds(List[ElementId](error_ids))

    # ── Звіт ─────────────────────────────────────────────────────────────
    mode_str = u"збірки" if is_assembly_mode else u"сімейства"
    lines = [
        u"Режим:      {}".format(mode_str),
        u"Успішно:    {}".format(ok_count),
        u"Пропущено: {} (немає URL)".format(skip_count),
        u"Помилки:   {}".format(len(errors)),
        u"[debug] elements:{} step1:{} mode:{}{}".format(
            len(elements), len(step1), actual_mode,
            u" family_map:{}".format(len(family_map)) if actual_mode == u"type" else u""),
        u"",
        u"PNG збережено у:",
        u"    " + frm.save_folder,
    ]
    if errors:
        lines += [u"", u"─" * 44, u"Деталі (перші 10):"]
        lines += [u"  • " + e[:300] for e in errors[:10]]
        if len(errors) > 10:
            lines.append(u"  … та ще {}".format(len(errors) - 10))

    forms.alert(u"\n".join(lines), title=u"QR-коди згенеровано")


if __name__ == u"__main__":
    run()
