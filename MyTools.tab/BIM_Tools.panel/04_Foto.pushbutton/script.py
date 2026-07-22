# -*- coding: utf-8 -*-
"""
Завантаження зображень у параметр сімейства.
Підтримка шаблонів налаштувань.
"""

import os
import json
import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Collections")

import System.Windows.Forms as WinForms
from System.Windows.Forms import (
    Form, Label, ComboBox, CheckBox, Button, TextBox,
    FolderBrowserDialog, DialogResult,
    FormBorderStyle, FormStartPosition, ComboBoxStyle,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
)
from System.Drawing import Point, Size, Color, Font, FontStyle
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilyInstance, AssemblyInstance,
    ImageType, ImageTypeOptions, ImageTypeSource,
    StorageType, ElementId, Transaction,
    BuiltInParameter, IFamilyLoadOptions, Material,
    Wall, Floor, Ceiling, RoofBase,
)
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

SUPPORTED_EXT   = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
import System
TEMPLATES_PATH  = os.path.join(
    System.Environment.GetFolderPath(System.Environment.SpecialFolder.ApplicationData),
    "pyRevit", "Extensions", "MyTools.extension", "photo_templates.json"
)


# ════════════════════════════════════════════════════════════════════════════
# ШАБЛОНИ
# ════════════════════════════════════════════════════════════════════════════
def load_templates():
    try:
        import codecs
        if os.path.exists(TEMPLATES_PATH):
            with codecs.open(TEMPLATES_PATH, 'r', encoding='utf-8') as f:
                return json.loads(f.read())
    except Exception:
        pass
    return {}


def save_templates(templates):
    try:
        import codecs
        folder = os.path.dirname(TEMPLATES_PATH)
        if not os.path.exists(folder):
            os.makedirs(folder)
        data = json.dumps(templates, ensure_ascii=False, indent=2)
        with codecs.open(TEMPLATES_PATH, 'w', encoding='utf-8') as f:
            f.write(data)
        return True
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════════
# КРОК 1: Перевірка виділення
# ════════════════════════════════════════════════════════════════════════════
selected_ids = list(uidoc.Selection.GetElementIds())

if not selected_ids:
    forms.alert(u"Не виділено жодного елемента.", title=u"Фото", warn_icon=True)
    script.exit()

selected_instances  = []
selected_assemblies = []
selected_generic    = []  # Системні сімейства (Стіни, Перекриття, Стелі тощо)
for eid in selected_ids:
    el = doc.GetElement(eid)
    if isinstance(el, FamilyInstance):
        selected_instances.append(el)
    elif isinstance(el, AssemblyInstance):
        selected_assemblies.append(el)
    elif el is not None:
        try:
            _ = el.Parameters
            selected_generic.append(el)
        except Exception:
            pass

# Елементи що мають матеріали (стіни, перекриття, стелі, покрівля)
_MATERIAL_HOST_TYPES = (Wall, Floor, Ceiling, RoofBase)
selected_material_hosts = []
for el in selected_generic:
    try:
        if isinstance(el, _MATERIAL_HOST_TYPES):
            selected_material_hosts.append(el)
    except Exception:
        pass

# Збираємо унікальні матеріали з матеріальних хостів
_all_materials = {}  # material_id -> Material
for el in selected_material_hosts:
    try:
        for mat_id in el.GetMaterialIds(False):
            if mat_id not in _all_materials:
                mat = doc.GetElement(mat_id)
                if mat and isinstance(mat, Material):
                    _all_materials[mat_id] = mat
    except Exception:
        pass

has_materials = len(_all_materials) > 0

_MATERIAL_HOST_TYPES = (Wall, Floor, Ceiling, RoofBase)
selected_material_hosts = []
for el in selected_generic:
    try:
        if isinstance(el, _MATERIAL_HOST_TYPES):
            selected_material_hosts.append(el)
    except Exception:
        pass

_all_materials = {}
for el in selected_material_hosts:
    try:
        for mat_id in el.GetMaterialIds(False):
            if mat_id not in _all_materials:
                mat = doc.GetElement(mat_id)
                if mat and isinstance(mat, Material):
                    _all_materials[mat_id] = mat
    except Exception:
        pass
has_materials = len(_all_materials) > 0

if not selected_instances and not selected_assemblies and not selected_generic:
    forms.alert(u"Серед виділених елементів немає підтримуваних елементів.", title=u"Фото", warn_icon=True)
    script.exit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 2: Збір параметрів
# ════════════════════════════════════════════════════════════════════════════
def collect_image_params(instances):
    found = {}

    # ALL_MODEL_TYPE_IMAGE: в типі ReadOnly=True, але через екземпляр — False
    # Тому додаємо як окремий запис з level='instance_builtin'
    BUILTIN_TYPE_IMAGE_NAME = u"Изображение типоразмера"

    for inst in instances:
        # ALL_MODEL_TYPE_IMAGE — тільки для FamilyInstance (системні кидають TypeError)
        if isinstance(inst, FamilyInstance):
            try:
                bip_param = inst.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
                if bip_param is not None:
                    key = (BUILTIN_TYPE_IMAGE_NAME, 'instance_builtin')
                    if key not in found:
                        found[key] = {
                            'name':  BUILTIN_TYPE_IMAGE_NAME,
                            'level': 'instance_builtin',
                            'bip':   BuiltInParameter.ALL_MODEL_TYPE_IMAGE,
                        }
            except Exception:
                pass

        # Звичайні параметри екземпляра
        try:
            for p in list(inst.Parameters):
                try:
                    if int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                        key = (p.Definition.Name, 'instance')
                        if key not in found:
                            found[key] = {'name': p.Definition.Name, 'level': 'instance'}
                except Exception:
                    continue
        except Exception:
            pass

        # Звичайні параметри типу
        try:
            type_el = doc.GetElement(inst.GetTypeId())
            if type_el:
                for p in list(type_el.Parameters):
                    try:
                        if int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                            key = (p.Definition.Name, 'type')
                            if key not in found:
                                found[key] = {'name': p.Definition.Name, 'level': 'type'}
                    except Exception:
                        continue
        except Exception:
            pass

    return sorted(found.values(), key=lambda x: x['name'])


def collect_source_params(instances):
    found = set()
    _readable = set([int(StorageType.String), int(StorageType.Double), int(StorageType.Integer)])
    for inst in instances:
        try:
            for p in list(inst.Parameters):
                try:
                    if int(p.StorageType) in _readable:
                        found.add(p.Definition.Name)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            type_el = doc.GetElement(inst.GetTypeId())
            if type_el:
                for p in list(type_el.Parameters):
                    try:
                        if int(p.StorageType) in _readable:
                            found.add(p.Definition.Name)
                    except Exception:
                        continue
        except Exception:
            pass
    return sorted(found)


param_list        = collect_image_params(selected_instances + selected_generic)
source_param_list = collect_source_params(selected_instances + selected_generic)

# Параметри матеріалів (для стін/перекриттів)
def collect_material_image_params(materials):
    """Збирає ElemId rw параметри матеріалів."""
    found = {}
    for mat in materials:
        try:
            for p in list(mat.Parameters):
                try:
                    if int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                        name = p.Definition.Name
                        key  = (name, 'mat_instance')
                        if key not in found:
                            found[key] = {'name': name, 'level': 'mat_instance'}
                except Exception:
                    continue
        except Exception:
            pass
    return sorted(found.values(), key=lambda x: x['name'])

def collect_material_source_params(materials):
    """Збирає String/Double/Integer параметри матеріалів як джерела."""
    found = set()
    _readable = set([int(StorageType.String), int(StorageType.Double), int(StorageType.Integer)])
    for mat in materials:
        try:
            for p in list(mat.Parameters):
                try:
                    if int(p.StorageType) in _readable:
                        found.add(p.Definition.Name)
                except Exception:
                    continue
        except Exception:
            pass
    return sorted(found)

mat_list        = collect_material_image_params(list(_all_materials.values())) if has_materials else []
mat_source_list = collect_material_source_params(list(_all_materials.values())) if has_materials else []

# Матеріали — додаємо як звичайні параметри з префіксом "Матеріал: ",
# за принципом скрипта QR-код: не окремий чекбокс, а пункти в тих самих списках.
_MAT_PREFIX = u"\u041c\u0430\u0442\u0435\u0440\u0456\u0430\u043b: "  # "Матеріал: "
if has_materials:
    for _mp in mat_list:
        param_list.append({'name': _MAT_PREFIX + _mp['name'], 'level': 'material'})
    for _ms in mat_source_list:
        _lbl_ms = _MAT_PREFIX + _ms
        if _lbl_ms not in source_param_list:
            source_param_list.append(_lbl_ms)
    source_param_list = sorted(source_param_list)

# Якщо є збірки — збираємо їхні власні параметри
if selected_assemblies:
    # Параметри зображення (ElementId, не ReadOnly) зі збірок
    asm_img_found = {}
    for asm in selected_assemblies:
        for p in asm.Parameters:
            if int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                key = (p.Definition.Name, 'instance')
                if key not in asm_img_found:
                    asm_img_found[key] = {'name': p.Definition.Name, 'level': 'instance'}
        asm_type = doc.GetElement(asm.GetTypeId())
        if asm_type:
            for p in asm_type.Parameters:
                if int(p.StorageType) == int(StorageType.ElementId) and not p.IsReadOnly:
                    key = (p.Definition.Name, 'type')
                    if key not in asm_img_found:
                        asm_img_found[key] = {'name': p.Definition.Name, 'level': 'type'}
    asm_img_list = sorted(asm_img_found.values(), key=lambda x: x['name'])
    param_list = param_list + asm_img_list

    # Рядкові параметри збірок для пошуку файлу
    asm_source_set = set(source_param_list)
    for asm in selected_assemblies:
        for p in asm.Parameters:
            if int(p.StorageType) == int(StorageType.String):
                asm_source_set.add(p.Definition.Name)
        asm_type = doc.GetElement(asm.GetTypeId())
        if asm_type:
            for p in asm_type.Parameters:
                if int(p.StorageType) == int(StorageType.String):
                    asm_source_set.add(p.Definition.Name)
    source_param_list = sorted(asm_source_set)

if not param_list:
    forms.alert(u"Не знайдено доступних параметрів зображення.", title=u"Фото", warn_icon=True)
    script.exit()

if not source_param_list:
    forms.alert(u"Не знайдено текстових параметрів.", title=u"Фото", warn_icon=True)
    script.exit()




# ════════════════════════════════════════════════════════════════════════════
# ДОПОМІЖНІ UI-КЛАСИ
# ════════════════════════════════════════════════════════════════════════════

class FilteredComboBox(ComboBox):
    """ComboBox з фільтрацією списку при введенні тексту."""
    def __init__(self, all_items):
        super(FilteredComboBox, self).__init__()
        self._all_items   = list(all_items)
        self._updating    = False
        self.DropDownStyle = ComboBoxStyle.DropDown
        self.Font          = Font(u"Segoe UI", 9)
        self.AutoCompleteMode   = WinForms.AutoCompleteMode.None
        self.AutoCompleteSource = WinForms.AutoCompleteSource.None
        self._fill(self._all_items)
        self.DrawMode = WinForms.DrawMode.OwnerDrawFixed
        self.DrawItem += self._on_draw_item
        self.TextChanged += self._on_text_changed
        self.KeyDown     += self._on_key_down

    def _fill(self, items):
        self.BeginUpdate()
        self.Items.Clear()
        for it in items:
            self.Items.Add(it)
        self.EndUpdate()

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
        if e.KeyCode == WinForms.Keys.Escape:
            self._updating = True
            try:
                self._fill(self._all_items)
                self.Text            = u""
                self.SelectionStart  = 0
                self.DroppedDown     = False
            finally:
                self._updating = False
            e.Handled = True

    def _on_draw_item(self, sender, e):
        """Малює елементи списку: завжди чорним, незалежно від ForeColor поля."""
        import System.Drawing as Drawing
        if e.Index < 0:
            return
        e.DrawBackground()
        item_text = self.Items[e.Index]
        text_color = Drawing.Color.FromArgb(40, 40, 40)
        e.Graphics.DrawString(
            item_text,
            e.Font,
            Drawing.SolidBrush(text_color),
            e.Bounds
        )
        e.DrawFocusRectangle()

    def set_value(self, val):
        """Встановлює текст без тригеру фільтрації."""
        if not val:
            return
        low = val.lower()
        for it in self._all_items:
            if it.lower() == low:
                self._updating = True
                self.Text = it
                self._updating = False
                return
        self._updating = True
        self.Text = val
        self._updating = False

# ════════════════════════════════════════════════════════════════════════════
# КРОК 3: UI
# ════════════════════════════════════════════════════════════════════════════
class _InputDialog(Form):
    """Простий діалог введення рядка."""
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
        btn_ok.Text      = u"OK"
        btn_ok.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_ok.SetBounds(14, 68, 80, 28)
        btn_ok.BackColor = Color.FromArgb(0, 112, 200)
        btn_ok.ForeColor = Color.White
        btn_ok.FlatStyle = WinForms.FlatStyle.Flat
        btn_ok.FlatAppearance.BorderSize = 0
        btn_ok.DialogResult = DialogResult.OK
        btn_ok.Click += self._on_ok
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = Button()
        btn_cancel.Text        = u"Скасувати"
        btn_cancel.Font        = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(104, 68, 80, 28)
        btn_cancel.FlatStyle   = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

    def _on_ok(self, sender, e):
        self.value = self._tb.Text
        self.DialogResult = DialogResult.OK


class SettingsForm(Form):
    def __init__(self, params, source_params, has_materials=False):
        super(SettingsForm, self).__init__()

        self._templates        = load_templates()
        self._params           = params
        self._source_params    = source_params
        self._has_materials    = has_materials

        # Константи стилю
        self._pad = 18
        BG = Color.FromArgb(245, 245, 248)

        self.Text            = u"Завантаження зображень у параметр сімейства"
        self.Width           = 520
        self.Height          = 100          # буде перераховано в _build
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG

        self._build()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _lbl(self, text, x, y, w=464, bold=False):
        l = Label()
        l.Text     = text
        l.Font     = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
        l.ForeColor = Color.FromArgb(40, 40, 40)
        l.SetBounds(x, y, w, 17)
        return l

    def _sep(self, y):
        s = Label()
        s.SetBounds(self._pad, y, 464, 1)
        s.BackColor = Color.FromArgb(205, 205, 215)
        return s

    def _tb(self, x, y, w, text=u"", readonly=False):
        tb = TextBox()
        tb.SetBounds(x, y, w, 24)
        tb.Font     = Font(u"Segoe UI", 9)
        tb.Text     = text
        tb.ReadOnly = readonly
        if readonly:
            tb.BackColor = Color.White
        return tb

    def _build(self):
        pad = self._pad
        y   = 14

        # ── Заголовок ────────────────────────────────────────────────────
        h = Label()
        h.Text      = u"Завантаження зображень"
        h.Font      = Font(u"Segoe UI", 10, FontStyle.Bold)
        h.ForeColor = Color.FromArgb(20, 20, 20)
        h.SetBounds(pad, y, 464, 22)
        self.Controls.Add(h)
        y += 28; self.Controls.Add(self._sep(y)); y += 12

        # ── 1. Папка з зображеннями ──────────────────────────────────────
        self.Controls.Add(self._lbl(u"1.  Папка з зображеннями:", pad, y, bold=True))
        y += 20
        self.txt_folder = self._tb(pad, y, 368, u"")
        self.txt_folder.ReadOnly  = True
        self.txt_folder.BackColor = Color.White
        self.txt_folder.TextChanged += self._on_folder_changed
        self.Controls.Add(self.txt_folder)
        btn_folder = Button()
        btn_folder.Text      = u"Огляд..."
        btn_folder.Font      = Font(u"Segoe UI", 9)
        btn_folder.SetBounds(pad + 374, y - 1, 90, 26)
        btn_folder.FlatStyle = WinForms.FlatStyle.Flat
        btn_folder.Click    += self._on_browse_folder
        self.Controls.Add(btn_folder)
        y += 32; self.Controls.Add(self._sep(y)); y += 12

        # ── 2. Параметр для пошуку файлу ────────────────────────────────
        self.Controls.Add(self._lbl(u"2.  Параметр для пошуку файлу:", pad, y, bold=True))
        y += 20
        self.combo_source = FilteredComboBox(self._source_params)
        self.combo_source.SetBounds(pad, y, 464, 26)
        default_src = u"Маркировка типоразмера"
        if default_src in self._source_params:
            self.combo_source.set_value(default_src)
        elif self._source_params:
            self.combo_source.set_value(self._source_params[0])
        self.Controls.Add(self.combo_source)
        y += 28
        if self._has_materials:
            lbl_src_note = Label()
            lbl_src_note.Text      = u"ℹ  Параметри з префіксом 'Матеріал: ' — з матеріалу несучої конструкції"
            lbl_src_note.Font      = Font(u"Segoe UI", 8)
            lbl_src_note.ForeColor = Color.FromArgb(80, 80, 180)
            lbl_src_note.SetBounds(pad, y, 464, 16)
            self.Controls.Add(lbl_src_note)
            y += 18
        y += 4; self.Controls.Add(self._sep(y)); y += 12

        # ── 3. Параметр для запису зображення ───────────────────────────
        self.Controls.Add(self._lbl(u"3.  Параметр для запису зображення:", pad, y, bold=True))
        y += 20
        param_labels = []
        for p in self._params:
            if p['level'] == 'material':
                param_labels.append(p['name'])
            elif p['level'] in ('instance_builtin', 'type'):
                param_labels.append(u"{} [тип]".format(p['name']))
            else:
                param_labels.append(u"{} [екземпляр]".format(p['name']))
        self.combo = FilteredComboBox(param_labels)
        self.combo.SetBounds(pad, y, 464, 26)
        if param_labels:
            self.combo.set_value(param_labels[0])
        self.Controls.Add(self.combo)
        y += 28
        if self._has_materials:
            lbl_tgt_note = Label()
            lbl_tgt_note.Text      = u"ℹ  Параметри з префіксом 'Матеріал: ' — записуються в матеріал несучої конструкції"
            lbl_tgt_note.Font      = Font(u"Segoe UI", 8)
            lbl_tgt_note.ForeColor = Color.FromArgb(80, 80, 180)
            lbl_tgt_note.SetBounds(pad, y, 464, 16)
            self.Controls.Add(lbl_tgt_note)
            y += 18
        y += 4; self.Controls.Add(self._sep(y)); y += 12

        # ── 4. Ім'я файлу: префікс / суфікс ────────────────────────────
        self.Controls.Add(self._lbl(u"4.  Пошук файлу:   {префікс}_{параметр}_{суфікс}", pad, y, bold=True))
        y += 20
        self.Controls.Add(self._lbl(u"Префікс:", pad, y + 3, w=70))
        self.txt_prefix = self._tb(pad + 74, y, 120, u"")
        self.Controls.Add(self.txt_prefix)
        self.Controls.Add(self._lbl(u"Суфікс:", pad + 212, y + 3, w=60))
        self.txt_suffix = self._tb(pad + 276, y, 120, u"")
        self.Controls.Add(self.txt_suffix)
        y += 32; self.Controls.Add(self._sep(y)); y += 12

        # ── 5. Параметри ─────────────────────────────────────────────────
        self.Controls.Add(self._lbl(u"5.  Параметри:", pad, y, bold=True))
        y += 20
        self.chk_replace = CheckBox()
        self.chk_replace.Text     = u"Замінювати існуючі зображення"
        self.chk_replace.Font     = Font(u"Segoe UI", 9)
        self.chk_replace.ForeColor = Color.FromArgb(160, 70, 0)
        self.chk_replace.SetBounds(pad, y, 464, 20)
        self.chk_replace.Checked  = False
        self.Controls.Add(self.chk_replace)
        y += 26
        self.chk_cleanup = CheckBox()
        self.chk_cleanup.Text     = u"Видалити старі зображення з такою ж назвою"
        self.chk_cleanup.Font     = Font(u"Segoe UI", 9)
        self.chk_cleanup.ForeColor = Color.FromArgb(160, 70, 0)
        self.chk_cleanup.SetBounds(pad, y, 464, 20)
        self.chk_cleanup.Checked  = False
        self.Controls.Add(self.chk_cleanup)
        y += 28

        self.Controls.Add(self._sep(y)); y += 10

        # ── Шаблони ──────────────────────────────────────────────────────
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
        y += 34

        # ── Кнопки ───────────────────────────────────────────────────────
        btn_ok = Button()
        btn_ok.Text      = u"Запустити"
        btn_ok.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_ok.SetBounds(pad, y, 220, 32)
        btn_ok.BackColor = Color.FromArgb(0, 112, 200)
        btn_ok.ForeColor = Color.White
        btn_ok.FlatStyle = WinForms.FlatStyle.Flat
        btn_ok.FlatAppearance.BorderSize = 0
        btn_ok.Click    += self._on_ok_click
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text         = u"Скасувати"
        btn_cancel.Font         = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(386, y, 100, 32)
        btn_cancel.FlatStyle    = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = DialogResult.Cancel
        btn_cancel.Click       += lambda s, e: self.Close()
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

        self.Height = y + 90

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

    def _on_load_template(self, sender, e):
        name = self.combo_tpl.Text.strip()
        if not name:
            MessageBox.Show(u"Оберіть шаблон зі списку.", u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return
        tpl = self._templates.get(name, {})
        if not tpl:
            MessageBox.Show(u"Шаблон '{}' не знайдено.".format(name), u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        # Перевіряємо папку
        folder = tpl.get('folder', u'')
        if folder and not os.path.isdir(folder):
            res = MessageBox.Show(
                u"Папка '{}' не існує.\nОновити шлях?".format(folder),
                u"Шаблон",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning
            )
            if res == DialogResult.Yes:
                dlg = FolderBrowserDialog()
                dlg.Description = u"Оберіть нову папку"
                if dlg.ShowDialog() == DialogResult.OK:
                    folder = dlg.SelectedPath
                    tpl['folder'] = folder
                    self._templates[name] = tpl
                    save_templates(self._templates)

        self.txt_folder.Text = folder

        # Параметр джерела
        src = tpl.get('source_param', u'')
        self.combo_source.set_value(src)

        # Параметр запису
        img_param = tpl.get('image_param', u'')
        for lbl in self.combo._all_items:
            if lbl.startswith(img_param):
                self.combo.set_value(lbl)
                break

        self.txt_prefix.Text     = tpl.get('prefix', u'')
        self.txt_suffix.Text     = tpl.get('suffix', u'')
        self.chk_replace.Checked = tpl.get('replace', False)
        self.chk_cleanup.Checked = tpl.get('cleanup', False)

    def _on_browse_folder(self, sender, e):
        dlg = FolderBrowserDialog()
        dlg.Description = u"Оберіть папку із зображеннями"
        dlg.ShowNewFolderButton = False
        if self.txt_folder.Text and os.path.isdir(self.txt_folder.Text):
            dlg.SelectedPath = self.txt_folder.Text
        if dlg.ShowDialog() == DialogResult.OK:
            self.txt_folder.Text = dlg.SelectedPath

    def _on_folder_changed(self, sender, e):
        # Як тільки папку вибрано — знімаємо червоне підсвічування
        if self.txt_folder.Text.strip() and os.path.isdir(self.txt_folder.Text.strip()):
            self.txt_folder.BackColor = Color.White

    def _on_ok_click(self, sender, e):
        if not self.txt_folder.Text.strip() or not os.path.isdir(self.txt_folder.Text.strip()):
            self.txt_folder.BackColor = Color.FromArgb(255, 180, 180)
            self.txt_folder.Focus()
            return
        self.DialogResult = DialogResult.OK
        self.Close()

    def _get_current_tpl_data(self):
        """Збирає поточні налаштування у словник."""
        img_label = self.combo.Items[self.combo.SelectedIndex] if self.combo.SelectedIndex >= 0 else u''
        img_name  = img_label.split(u' [')[0] if u' [' in img_label else img_label
        return {
            'folder':       self.txt_folder.Text.strip(),
            'source_param': self.combo_source.Items[self.combo_source.SelectedIndex] if self.combo_source.SelectedIndex >= 0 else u'',
            'image_param':  img_name,
            'prefix':       self.txt_prefix.Text,
            'suffix':       self.txt_suffix.Text,
            'replace':      self.chk_replace.Checked,
            'cleanup':      self.chk_cleanup.Checked,
        }

    def _on_save_template(self, sender, e):
        suggested = self.combo_tpl.Text.strip() or u"Новий шаблон"
        dlg = _InputDialog(u"Назва шаблону", u"Введіть назву:", suggested)
        if dlg.ShowDialog() != DialogResult.OK:
            return
        name = dlg.value.strip()
        if not name:
            return
        if name in self._templates:
            res = MessageBox.Show(
                u"Шаблон '{}' вже існує. Перезаписати?".format(name),
                u"Перезаписати?",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question)
            if res != DialogResult.Yes:
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
        if not name or name not in self._templates:
            MessageBox.Show(u"Оберіть шаблон для видалення.", u"Шаблони",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        res = MessageBox.Show(
            u"Видалити шаблон '{}'?".format(name),
            u"Видалити?",
            MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        if res == DialogResult.Yes:
            del self._templates[name]
            save_templates(self._templates)
            self._fill_templates()


# Показуємо форму
settings_form = SettingsForm(param_list, source_param_list, has_materials)
if settings_form.ShowDialog() != DialogResult.OK:
    script.exit()

# Перевіряємо папку
image_folder = settings_form.txt_folder.Text.strip()
if not image_folder or not os.path.isdir(image_folder):
    forms.alert(u"Папку не вказано або вона не існує.", title=u"Фото", warn_icon=True)
    script.exit()

# Збираємо налаштування
# combo — FilteredComboBox: шукаємо по тексту
_combo_text = settings_form.combo.Text.strip()
selected_param = param_list[0]
for _i, _p in enumerate(param_list):
    if _p['level'] == 'material':
        _lbl = _p['name']
    elif _p['level'] in ('instance_builtin', 'type'):
        _lbl = u"{} [тип]".format(_p['name'])
    else:
        _lbl = u"{} [екземпляр]".format(_p['name'])
    if _lbl == _combo_text:
        selected_param = _p
        break
_src_text = settings_form.combo_source.Text.strip()
source_param_name = _src_text if _src_text in source_param_list else (source_param_list[0] if source_param_list else u"")
replace_existing  = settings_form.chk_replace.Checked
cleanup_dupes     = settings_form.chk_cleanup.Checked
img_prefix        = settings_form.txt_prefix.Text
img_suffix        = settings_form.txt_suffix.Text
param_name        = selected_param['name']
param_level       = selected_param['level']

# ── ПЕРШИЙ АЛЕРТ — одразу після читання налаштувань ─────────────────────
# Словник зображень
image_dict = {}
for filename in os.listdir(image_folder):
    name, ext = os.path.splitext(filename)
    if ext.lower() in SUPPORTED_EXT:
        key = name.lower()
        if key not in image_dict:
            image_dict[key] = os.path.join(image_folder, filename)

if not image_dict:
    forms.alert(u"У папці не знайдено зображень.", title=u"Фото", warn_icon=True)
    script.exit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 4: Допоміжні функції
# ════════════════════════════════════════════════════════════════════════════
def _param_to_str(p):
    """Читає параметр будь-якого типу як рядок."""
    if not p:
        return None
    st = int(p.StorageType)
    if st == int(StorageType.String):
        val = p.AsString()
        return val.strip() if val and val.strip() else None
    if st == int(StorageType.Double):
        try:
            from Autodesk.Revit.DB import UnitUtils
            converted = UnitUtils.ConvertFromInternalUnits(p.AsDouble(), p.GetUnitTypeId())
            result = u"{:.4f}".format(converted).rstrip('0').rstrip('.')
            return result if result else None
        except Exception:
            result = u"{:.4f}".format(p.AsDouble()).rstrip('0').rstrip('.')
            return result if result else None
    if st == int(StorageType.Integer):
        return u"{}".format(p.AsInteger())
    return None


def is_material_param(param_name):
    """Чи є ім'я параметра посиланням на параметр матеріалу (префікс 'Матеріал: ')."""
    return bool(param_name) and param_name.startswith(_MAT_PREFIX)


def get_structural_material(el):
    """Повертає матеріал несучої конструкції елемента (з fallback на перший матеріал)."""
    try:
        p = el.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM)
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


def get_source_value(instance, src_param_name):
    if is_material_param(src_param_name):
        real_name = src_param_name[len(_MAT_PREFIX):]
        mat = get_structural_material(instance)
        if not mat:
            return None
        return _param_to_str(mat.LookupParameter(real_name))
    try:
        type_el = doc.GetElement(instance.GetTypeId())
        if type_el:
            p = type_el.LookupParameter(src_param_name)
            val = _param_to_str(p)
            if val:
                return val
    except Exception:
        pass
    try:
        p = instance.LookupParameter(src_param_name)
        val = _param_to_str(p)
        if val:
            return val
    except Exception:
        pass
    return None


# Глобальний список помилок імпорту зображень
_image_errors = []

def get_or_load_image(image_path):
    norm_path = os.path.normcase(os.path.normpath(image_path))
    existing  = FilteredElementCollector(doc).OfClass(ImageType).ToElements()
    for img in existing:
        try:
            if os.path.normcase(os.path.normpath(img.Path)) == norm_path:
                return img.Id
        except Exception:
            pass
    try:
        options = ImageTypeOptions(image_path, False, ImageTypeSource.Import)
        new_img = ImageType.Create(doc, options)
        if new_img:
            return new_img.Id
        else:
            _image_errors.append(u"{} — ImageType.Create повернув None".format(
                os.path.basename(image_path)))
    except Exception as ex:
        _image_errors.append(u"{} — {}".format(
            os.path.basename(image_path), str(ex)))
    return ElementId.InvalidElementId


def assign_image_param(el, param_name, image_type_id):
    """
    Записує image_type_id у параметр param_name елемента el.
    Якщо param_name починається з 'Матеріал: ' — записує в перший матеріал
    елемента el, що має відповідний нередагований ElementId-параметр
    (той самий принцип, що й у скрипті QR-код).
    Повертає True або рядок з описом помилки.
    """
    if is_material_param(param_name):
        real_name = param_name[len(_MAT_PREFIX):]
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
        return u"Параметр '{}' не знайдено в матеріалах".format(real_name)

    p = el.LookupParameter(param_name)
    if not p:
        return u"параметр '{}' не знайдено".format(param_name)
    if int(p.StorageType) != int(StorageType.ElementId):
        return u"StorageType={}".format(p.StorageType)
    if p.IsReadOnly:
        return u"ReadOnly"
    try:
        p.Set(image_type_id)
        return True
    except Exception as ex:
        return u"Set: {}".format(ex)


def get_current_image_id(el, param_name):
    """Повертає поточний ElementId параметра зображення (або None)."""
    if is_material_param(param_name):
        real_name = param_name[len(_MAT_PREFIX):]
        try:
            for mat_id in el.GetMaterialIds(False):
                mat = doc.GetElement(mat_id)
                if mat:
                    p = mat.LookupParameter(real_name)
                    if p and int(p.StorageType) == int(StorageType.ElementId):
                        return p.AsElementId()
        except Exception:
            pass
        return None
    p = el.LookupParameter(param_name)
    if p:
        try:
            return p.AsElementId()
        except Exception:
            return None
    return None


def delete_old_images(base_name):
    """Видаляє старі зображення з такою назвою крім щойно завантаженого."""
    base_lower = base_name.lower()
    all_images = FilteredElementCollector(doc).OfClass(ImageType).ToElements()
    to_delete  = []
    for img in all_images:
        try:
            fname = os.path.splitext(os.path.basename(img.Path))[0].lower()
            if fname == base_lower or fname.startswith(base_lower + u" ("):
                to_delete.append(img.Id)
        except Exception:
            pass
    for img_id in to_delete:
        try:
            doc.Delete(img_id)
        except Exception:
            pass


def delete_old_images_except(base_name, keep_id):
    """Видаляє старі зображення з такою назвою але зберігає keep_id."""
    base_lower = base_name.lower()
    all_images = FilteredElementCollector(doc).OfClass(ImageType).ToElements()
    to_delete  = []
    for img in all_images:
        if img.Id == keep_id:
            continue
        try:
            fname = os.path.splitext(os.path.basename(img.Path))[0].lower()
            if fname == base_lower or fname.startswith(base_lower + u" ("):
                to_delete.append(img.Id)
        except Exception:
            pass
    for img_id in to_delete:
        try:
            doc.Delete(img_id)
        except Exception:
            pass


def set_images_for_family(family, type_image_map, replace_existing, target_param_name=None):
    """
    Відкриває сімейство один раз і записує зображення кожному типу окремо.
    type_image_map: { type_name (str) -> image_path (str) }
    target_param_name: назва параметра-цілі всередині FamilyManager.
        None -> ALL_MODEL_TYPE_IMAGE (вбудований "Изображение типоразмера").
        Інакше шукає власний параметр типу з такою назвою.
    Повертає: { type_name -> 'ok'/'already'/'no_image'/'error' }
    """
    results = {}

    fam_doc = doc.EditFamily(family)
    if not fam_doc:
        for tn in type_image_map:
            results[tn] = 'error: EditFamily() повернув None (можливо системна родина без .rfa)'
        return results

    try:
        mgr = fam_doc.FamilyManager

        # Знаходимо параметр зображення
        img_fp = None
        if target_param_name:
            # Власний параметр типу з заданою назвою
            for fp in mgr.Parameters:
                try:
                    if fp.Definition.Name == target_param_name:
                        img_fp = fp
                        break
                except Exception:
                    continue
        else:
            img_fp = mgr.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_IMAGE)
            if not img_fp:
                for fp in mgr.Parameters:
                    if fp.Definition.Name == u'Изображение типоразмера':
                        img_fp = fp
                        break
        if not img_fp:
            # Параметр не знайдено у FamilyManager — закриваємо сімейство
            # і пишемо напряму в тип проекту (shared param доданий до типу)
            fam_doc.Close(False)
            results[u'__use_project_type__'] = True
            return results

        # Збираємо типи сімейства по імені (без транзакції)
        fam_types = {}
        mgr_types_list = list(mgr.Types)
        for ft in mgr_types_list:
            try:
                ft_name = ft.Name
            except Exception:
                try:
                    p = ft.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                    ft_name = p.AsString() if p else None
                except Exception:
                    ft_name = None
            if ft_name:
                fam_types[ft_name] = ft
            elif ft_name == u"" or ft_name is None:
                # Unnamed type - store with empty key
                fam_types[u""] = ft

        # Одна транзакція для всіх типів
        tx = Transaction(fam_doc, u"Зображення типоразмера")
        tx.Start()
        try:
            if True:
                changed = False
                for type_name, image_path in type_image_map.items():
                    ft = fam_types.get(type_name)
                    if not ft:
                        # Спроба 1: unnamed type зі словника
                        ft = fam_types.get(u"")
                    if not ft:
                        # Спроба 2: CurrentType
                        try:
                            ft = mgr.CurrentType
                        except Exception:
                            ft = None
                    if not ft:
                        # Спроба 3: перший тип зі списку
                        if mgr_types_list:
                            ft = mgr_types_list[0]
                    if not ft:
                        avail_types = u"mgr.Types count={}, CurrentType={}, fam_types keys={}".format(
                            len(mgr_types_list),
                            type(mgr.CurrentType).__name__ if mgr.CurrentType else "None",
                            list(fam_types.keys())[:5])
                        results[type_name] = u'error: тип не знайдено. Debug: {}'.format(avail_types)
                        continue

                    mgr.CurrentType = ft

                    # Перевіряємо replace_existing
                    if not replace_existing:
                        cur_val = mgr.AsElementId(img_fp)
                        if cur_val and cur_val != ElementId.InvalidElementId:
                            results[type_name] = 'already'
                            continue

                    if not image_path:
                        results[type_name] = 'no_image'
                        continue

                    # Перевіряємо чи зображення вже є у fam_doc
                    norm_path = os.path.normcase(os.path.normpath(image_path))
                    existing_imgs = FilteredElementCollector(fam_doc).OfClass(ImageType).ToElements()
                    new_img_id = None
                    for ex_img in existing_imgs:
                        try:
                            if os.path.normcase(os.path.normpath(ex_img.Path)) == norm_path:
                                new_img_id = ex_img.Id
                                break
                        except Exception:
                            pass
                    if not new_img_id:
                        opts    = ImageTypeOptions(image_path, False, ImageTypeSource.Import)
                        new_img = ImageType.Create(fam_doc, opts)
                        if not new_img:
                            results[type_name] = u'error: ImageType.Create у fam_doc повернув None для {}'.format(
                                os.path.basename(image_path))
                            continue
                        new_img_id = new_img.Id

                    mgr.Set(img_fp, new_img_id)
                    results[type_name] = 'ok'
                    changed = True

                if changed:
                    tx.Commit()
                else:
                    tx.RollBack()

        except Exception as ex:
            import traceback
            err_msg = traceback.format_exc()
            tx.RollBack()
            fam_doc.Close(False)
            for tn in type_image_map:
                if tn not in results:
                    results[tn] = u'error: виняток у транзакції - {}'.format(str(ex))
            results['__error__'] = err_msg
            return results

        # Завантажуємо назад якщо були зміни
        if any(v == 'ok' for v in results.values()):
            class FamilyLoader(IFamilyLoadOptions):
                def OnFamilyFound(self, familyInUse, overwriteParameterValues):
                    overwriteParameterValues = True
                    return True
                def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
                    from Autodesk.Revit.DB import FamilySource
                    source = FamilySource.Family
                    overwriteParameterValues = True
                    return True
            fam_doc.LoadFamily(doc, FamilyLoader())

        fam_doc.Close(False)

    except Exception as ex:
        import traceback
        err_msg = traceback.format_exc()
        try:
            fam_doc.Close(False)
        except Exception:
            pass
        for tn in type_image_map:
            if tn not in results:
                results[tn] = u'error: зовнішній виняток - {}'.format(str(ex))
        results['__error__'] = err_msg

    return results
# ════════════════════════════════════════════════════════════════════════════
# КРОК 5: Основний цикл
# ════════════════════════════════════════════════════════════════════════════
success_count      = 0
skipped_ids        = []
already_ids        = []
processed_types    = {}
processed_families = {}  # для instance_builtin

if param_level == 'instance_builtin':
    # ── Режим EditFamily — групуємо по сімейству ────────────────────────
    # Збираємо для кожного сімейства: { family -> { type_name -> image_path } }
    family_type_map = {}  # family_id -> { 'family': family, 'types': { type_name -> image_path } }

    for inst in selected_instances:
        type_mark = get_source_value(inst, source_param_name)
        if not type_mark:
            skipped_ids.append(inst.Id)
            continue

        search_key = u"{}{}{}".format(img_prefix, type_mark, img_suffix).lower()
        image_path = image_dict.get(search_key)
        if not image_path:
            _image_errors.append(u"[{}] файл не знайдено: ключ='{}'".format(inst.Id, search_key))
            skipped_ids.append(inst.Id)
            continue

        type_el = doc.GetElement(inst.GetTypeId())
        if not type_el:
            _image_errors.append(u"[{}] GetTypeId() -> None".format(inst.Id))
            skipped_ids.append(inst.Id)
            continue

        try:
            family = type_el.Family
            fam_id = family.Id
            try:
                type_name = type_el.Name
            except Exception:
                p = type_el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                type_name = p.AsString() if p else u""
            if not type_name:
                _image_errors.append(u"[{}] type_name порожній".format(inst.Id))
                skipped_ids.append(inst.Id)
                continue
        except Exception as ex:
            _image_errors.append(u"[{}] type_el.Family помилка: {}".format(inst.Id, str(ex)))
            skipped_ids.append(inst.Id)
            continue

        if fam_id not in family_type_map:
            family_type_map[fam_id] = {'family': family, 'types': {}}

        # Один тип = одне зображення (останнє виділене перемагає)
        family_type_map[fam_id]['types'][type_name] = image_path

    # Обробляємо кожне сімейство один раз
    for fam_id, data in family_type_map.items():
        results = set_images_for_family(
            data['family'],
            data['types'],
            replace_existing
        )

        # Fallback: параметр не у FamilyManager — пишемо напряму в тип проекту
        if results.get(u'__use_project_type__'):
            # Крок А: завантажуємо ImageType поза транзакцією
            _proj_pairs = []  # (proj_type, image_el_id, type_name)
            for type_name, image_path in data['types'].items():
                proj_type = None
                try:
                    from Autodesk.Revit.DB import FilteredElementCollector, FamilySymbol
                    for sym in FilteredElementCollector(doc).OfClass(FamilySymbol).ToElements():
                        if sym.Family.Id == fam_id and sym.Name == type_name:
                            proj_type = sym
                            break
                except Exception:
                    pass

                if not proj_type:
                    _image_errors.append(u"{} — тип не знайдено в проекті".format(type_name))
                    continue

                image_el_id = get_or_load_image(image_path)
                if image_el_id == ElementId.InvalidElementId:
                    _image_errors.append(u"{} — ImageType не завантажено".format(type_name))
                    continue

                _proj_pairs.append((proj_type, image_el_id, type_name))

            # Крок Б: записуємо в транзакції
            if _proj_pairs:
                tx_pt = Transaction(doc, u"Фото: прямий запис у тип")
                tx_pt.Start()
                try:
                    for proj_type, image_el_id, type_name in _proj_pairs:
                        try:
                            p = proj_type.LookupParameter(param_name)
                            if p and not p.IsReadOnly:
                                current = p.AsElementId()
                                if current != ElementId.InvalidElementId and not replace_existing:
                                    already_ids.append(proj_type.Id)
                                else:
                                    p.Set(image_el_id)
                                    success_count += 1
                            else:
                                _image_errors.append(
                                    u"{} — параметр '{}' не знайдено або ReadOnly".format(
                                        type_name, param_name))
                        except Exception as ex:
                            _image_errors.append(u"{} — помилка Set: {}".format(type_name, ex))
                    tx_pt.Commit()
                except Exception as ex:
                    _image_errors.append(u"Транзакція прямого запису: {}".format(ex))
                    try:
                        tx_pt.RollBack()
                    except Exception:
                        pass
        else:
            for type_name, result in results.items():
                if type_name == '__error__':
                    _image_errors.append(u"__error__ [fam {}]: {}".format(fam_id, str(result)[:300]))
                    continue
                if type_name == u'__use_project_type__':
                    continue
                if result == 'ok':
                    success_count += 1
                elif result == 'already':
                    already_ids.append(fam_id)
                else:
                    skipped_ids.append(fam_id)
                    _image_errors.append(u"{} [fam {}] -> {}".format(
                        type_name, fam_id, str(result)[:300]))

elif param_level == 'type':
    # ── Режим EditFamily для власних параметрів типу ────────────────────
    # Уникає прямого param.Set() на закритому FamilySymbol — натомість
    # відкриває сімейство, пише параметр через FamilyManager, вантажить назад.
    family_type_map = {}  # family_id -> {'family': family, 'types': {type_name -> image_path}}

    for inst in selected_instances:
        type_mark = get_source_value(inst, source_param_name)
        if not type_mark:
            skipped_ids.append(inst.Id)
            continue

        search_key = u"{}{}{}".format(img_prefix, type_mark, img_suffix).lower()
        image_path = image_dict.get(search_key)
        if not image_path:
            _image_errors.append(u"[{}] файл не знайдено: ключ='{}'".format(inst.Id, search_key))
            skipped_ids.append(inst.Id)
            continue

        type_el = doc.GetElement(inst.GetTypeId())
        if not type_el:
            _image_errors.append(u"[{}] GetTypeId() -> None".format(inst.Id))
            skipped_ids.append(inst.Id)
            continue

        try:
            family = type_el.Family
            fam_id = family.Id
            try:
                type_name = type_el.Name
            except Exception:
                p = type_el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                type_name = p.AsString() if p else u""
            if not type_name:
                _image_errors.append(u"[{}] type_name порожній".format(inst.Id))
                skipped_ids.append(inst.Id)
                continue
        except Exception as ex:
            _image_errors.append(u"[{}] type_el.Family помилка: {}".format(inst.Id, str(ex)))
            skipped_ids.append(inst.Id)
            continue

        if fam_id not in family_type_map:
            family_type_map[fam_id] = {'family': family, 'types': {}}
        family_type_map[fam_id]['types'][type_name] = image_path

    for fam_id, data in family_type_map.items():
        results = set_images_for_family(
            data['family'],
            data['types'],
            replace_existing,
            target_param_name=param_name
        )
        for type_name, result in results.items():
            if type_name == '__error__':
                _image_errors.append(u"__error__ [fam {}]: {}".format(fam_id, str(result)[:200]))
                continue
            if result == 'ok':
                success_count += 1
            elif result == 'already':
                already_ids.append(fam_id)
            else:
                skipped_ids.append(fam_id)
                _image_errors.append(u"{} [fam {}] -> result={}".format(
                    type_name, fam_id, str(result)[:300]))

else:
    # ── Звичайний режим (запис в проект) ────────────────────────────────
    with Transaction(doc, u"Завантаження зображень") as tx:
        tx.Start()

        for inst in selected_instances:
            type_mark = get_source_value(inst, source_param_name)
            if not type_mark:
                skipped_ids.append(inst.Id)
                continue

            search_key = u"{}{}{}".format(img_prefix, type_mark, img_suffix).lower()
            image_path = image_dict.get(search_key)
            if not image_path:
                skipped_ids.append(inst.Id)
                continue

            if param_level == 'type':
                try:
                    target_el = doc.GetElement(inst.GetTypeId())
                except Exception:
                    target_el = None
            else:
                target_el = inst
            if not target_el:
                _image_errors.append(u"[{}] target_el = None".format(inst.Id))
                skipped_ids.append(inst.Id)
                continue

            current_val = get_current_image_id(target_el, param_name)
            if current_val and current_val != ElementId.InvalidElementId and not replace_existing:
                already_ids.append(inst.Id)
                continue

            type_id = inst.GetTypeId()

            if param_level == 'type':
                if type_id in processed_types:
                    image_el_id = processed_types[type_id]
                else:
                    image_el_id = get_or_load_image(image_path)
                    if cleanup_dupes and image_el_id != ElementId.InvalidElementId:
                        base_name = u"{}{}{}".format(img_prefix, type_mark, img_suffix)
                        delete_old_images_except(base_name, image_el_id)
                    processed_types[type_id] = image_el_id
            else:
                image_el_id = get_or_load_image(image_path)
                if cleanup_dupes and image_el_id != ElementId.InvalidElementId:
                    base_name = u"{}{}{}".format(img_prefix, type_mark, img_suffix)
                    delete_old_images_except(base_name, image_el_id)

            if image_el_id == ElementId.InvalidElementId:
                skipped_ids.append(inst.Id)
                continue

            result = assign_image_param(target_el, param_name, image_el_id)
            if result is True:
                success_count += 1
            else:
                _image_errors.append(u"[{}] {}".format(inst.Id, result))
                skipped_ids.append(inst.Id)

        tx.Commit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 5а: Системні елементи (WallSweep, FilledRegion, Wall тощо)
# Виконується для БУДЬ-ЯКОГО param_level (instance або type)
# ════════════════════════════════════════════════════════════════════════════
if selected_generic:
    tx_sys = Transaction(doc, u"Завантаження зображень: системні елементи")
    tx_sys.Start()
    _processed_sys_types = {}
    try:
        for inst in selected_generic:
            type_mark = get_source_value(inst, source_param_name)
            if not type_mark:
                _image_errors.append(u"[{}] джерело '{}' порожнє".format(inst.Id, source_param_name))
                skipped_ids.append(inst.Id)
                continue

            search_key = u"{}{}{}".format(img_prefix, type_mark, img_suffix).lower()
            image_path = image_dict.get(search_key)
            if not image_path:
                _image_errors.append(u"[{}] файл не знайдено: '{}'".format(inst.Id, search_key))
                skipped_ids.append(inst.Id)
                continue

            # Визначаємо target_el залежно від param_level
            if param_level in ('type', 'instance_builtin'):
                try:
                    target_el = doc.GetElement(inst.GetTypeId())
                except Exception:
                    target_el = None
            else:
                target_el = inst

            if not target_el:
                _image_errors.append(u"[{}] target_el = None".format(inst.Id))
                skipped_ids.append(inst.Id)
                continue

            # Перевірка чи вже є зображення (враховує і параметри матеріалу)
            current_val = get_current_image_id(target_el, param_name)
            if current_val and current_val != ElementId.InvalidElementId and not replace_existing:
                already_ids.append(inst.Id)
                continue

            # Дедублікація по типу
            try:
                type_id = inst.GetTypeId()
            except Exception:
                type_id = None

            if param_level in ('type', 'instance_builtin') and type_id:
                if type_id in _processed_sys_types:
                    image_el_id = _processed_sys_types[type_id]
                else:
                    image_el_id = get_or_load_image(image_path)
                    _processed_sys_types[type_id] = image_el_id
            else:
                image_el_id = get_or_load_image(image_path)

            if image_el_id == ElementId.InvalidElementId:
                _image_errors.append(u"[{}] ImageType не завантажено: {}".format(
                    inst.Id, os.path.basename(image_path)))
                skipped_ids.append(inst.Id)
                continue

            result = assign_image_param(target_el, param_name, image_el_id)
            if result is True:
                success_count += 1
            else:
                _image_errors.append(u"[{}] {}".format(inst.Id, result))
                skipped_ids.append(inst.Id)

        tx_sys.Commit()
    except Exception as ex:
        try:
            tx_sys.RollBack()
        except Exception:
            pass
        _image_errors.append(u"Системні елементи: зовнішня помилка: {}".format(ex))


# ════════════════════════════════════════════════════════════════════════════
# КРОК 5в: Збірки — запис зображення прямо в параметр AssemblyInstance
# ════════════════════════════════════════════════════════════════════════════
if selected_assemblies:
    with Transaction(doc, u"Завантаження зображень у збірки") as tx_asm:
        tx_asm.Start()
        for asm in selected_assemblies:
            # Читаємо маркування з параметра збірки (екземпляр, тип або матеріал)
            type_mark = get_source_value(asm, source_param_name)
            if not type_mark:
                skipped_ids.append(asm.Id)
                continue

            search_key = u"{}{}{}".format(img_prefix, type_mark, img_suffix).lower()
            image_path = image_dict.get(search_key)
            if not image_path:
                skipped_ids.append(asm.Id)
                continue

            # Параметр для запису — на екземплярі, типі збірки або в матеріалі
            target_el = doc.GetElement(asm.GetTypeId()) if param_level == 'type' else asm
            if not target_el:
                skipped_ids.append(asm.Id)
                continue

            current_val = get_current_image_id(target_el, param_name)
            if current_val and current_val != ElementId.InvalidElementId and not replace_existing:
                already_ids.append(asm.Id)
                continue

            image_el_id = get_or_load_image(image_path)
            if image_el_id == ElementId.InvalidElementId:
                skipped_ids.append(asm.Id)
                continue

            result = assign_image_param(target_el, param_name, image_el_id)
            if result is True:
                success_count += 1
            else:
                _image_errors.append(u"[{}] {}".format(asm.Id, result))
                skipped_ids.append(asm.Id)
        tx_asm.Commit()

# ════════════════════════════════════════════════════════════════════════════
# КРОК 6: Звіт
# ════════════════════════════════════════════════════════════════════════════
if skipped_ids:
    id_list = List[ElementId]()
    for eid in skipped_ids:
        id_list.Add(eid)
    uidoc.Selection.SetElementIds(id_list)

report = []
report.append(u"\u2705 Успішно записано: {}".format(success_count))
if skipped_ids:
    report.append(u"\u26a0\ufe0f Не знайдено зображення: {} (виділено в моделі)".format(len(skipped_ids)))
if already_ids:
    report.append(u"\u23ed Пропущено (зображення вже є): {}".format(len(already_ids)))
if _image_errors:
    report.append(u"")
    report.append(u"Помилки імпорту:")
    for e in _image_errors[:10]:
        report.append(u"  {}".format(e))

forms.alert(u"\n".join(report), title=u"Результат завантаження зображень")
