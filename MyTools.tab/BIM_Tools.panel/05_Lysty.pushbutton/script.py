# -*- coding: utf-8 -*-
"""
Перенумерація листів проекту.
Вибір: всі / виділені / по колекції
Сортування: за номером / за назвою / вручну
Формат: префікс + номер + суфікс
"""

import clr

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Collections")

import System.Windows.Forms as WinForms
from System.Windows.Forms import (
    Form, Label, ComboBox, Button, Panel, TextBox, RadioButton,
    ListBox, GroupBox, DialogResult, FormBorderStyle, FormStartPosition,
    ComboBoxStyle, SelectionMode, DragDropEffects, MessageBox,
    MessageBoxButtons, MessageBoxIcon,
)
from System.Drawing import Point, Size, Color, Font, FontStyle
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSheet, BuiltInParameter,
    StorageType, ElementId, Transaction,
)
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


# ════════════════════════════════════════════════════════════════════════════
# КРОК 1: Збір даних
# ════════════════════════════════════════════════════════════════════════════
def get_all_sheets():
    return sorted(
        FilteredElementCollector(doc).OfClass(ViewSheet).ToElements(),
        key=lambda s: s.SheetNumber
    )


def get_selected_sheets():
    selected_ids = list(uidoc.Selection.GetElementIds())
    sheets = []
    for eid in selected_ids:
        el = doc.GetElement(eid)
        if isinstance(el, ViewSheet):
            sheets.append(el)
    return sheets


def get_sheet_collections():
    """Повертає унікальні колекції листів через параметр 'Коллекция листов'."""
    collections = {}
    for sheet in get_all_sheets():
        for p in sheet.Parameters:
            name = p.Definition.Name
            if u"коллекци" in name.lower() or u"collection" in name.lower() or u"колекц" in name.lower():
                if p.StorageType == StorageType.String:
                    val = p.AsString()
                    if val and val.strip():
                        collections[val.strip()] = (name, val.strip())
                elif p.StorageType == StorageType.ElementId:
                    eid = p.AsElementId()
                    if eid:
                        try:
                            eid_val = eid.Value
                        except AttributeError:
                            eid_val = eid.IntegerValue
                        if eid_val > 0:
                            el = doc.GetElement(eid)
                            if el:
                                try:
                                    val = el.Name
                                except Exception:
                                    val = str(eid_val)
                                if val:
                                    collections[val] = (name, val)
    return sorted(collections.values(), key=lambda x: x[1])


def get_sheets_by_collection(param_name, collection_value):
    sheets = []
    for sheet in get_all_sheets():
        p = sheet.LookupParameter(param_name)
        if not p:
            continue
        if p.StorageType == StorageType.String:
            val = p.AsString()
            if val and val.strip() == collection_value:
                sheets.append(sheet)
        elif p.StorageType == StorageType.ElementId:
            eid = p.AsElementId()
            if eid:
                try:
                    eid_val = eid.Value
                except AttributeError:
                    eid_val = eid.IntegerValue
                if eid_val > 0:
                    el = doc.GetElement(eid)
                    if el:
                        try:
                            val = el.Name
                        except Exception:
                            val = str(eid_val)
                        if val == collection_value:
                            sheets.append(sheet)
    return sheets


all_sheets        = get_all_sheets()
sheet_collections = get_sheet_collections()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 2: Головна форма
# ════════════════════════════════════════════════════════════════════════════
class SheetNumberForm(Form):
    def __init__(self):
        super(SheetNumberForm, self).__init__()

        PAD = 18
        BG  = Color.FromArgb(245, 245, 248)

        self.Text            = u"Перенумерація листів"
        self.Width           = 560
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG

        self._sheets     = []
        self._drag_index = -1

        y = 14

        # ── helpers ──────────────────────────────────────────────────────

        def lbl(text, x, ly, w=500, bold=False):
            l = Label()
            l.Text      = text
            l.Font      = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
            l.ForeColor = Color.FromArgb(40, 40, 40)
            l.SetBounds(x, ly, w, 17)
            l.BackColor = BG
            return l

        def sep(ly):
            s = Label()
            s.SetBounds(PAD, ly, 500, 1)
            s.BackColor = Color.FromArgb(205, 205, 215)
            return s

        def rb(text, x, ly, w=130):
            r = RadioButton()
            r.Text      = text
            r.Font      = Font(u"Segoe UI", 9)
            r.ForeColor = Color.FromArgb(40, 40, 40)
            r.SetBounds(x, ly, w, 20)
            r.BackColor = BG
            return r

        def tb(x, ly, w, text=u""):
            t = TextBox()
            t.Font = Font(u"Segoe UI", 9)
            t.SetBounds(x, ly, w, 24)
            t.Text = text
            return t

        # ── Заголовок ────────────────────────────────────────────────────
        h = Label()
        h.Text      = u"Перенумерація листів"
        h.Font      = Font(u"Segoe UI", 10, FontStyle.Bold)
        h.ForeColor = Color.FromArgb(20, 20, 20)
        h.SetBounds(PAD, y, 500, 22)
        h.BackColor = BG
        self.Controls.Add(h)
        y += 28; self.Controls.Add(sep(y)); y += 12

        # ── 1. Вибір листів ──────────────────────────────────────────────
        self.Controls.Add(lbl(u"1.  Вибір листів:", PAD, y, bold=True))
        y += 22

        self.rb_all = rb(u"Всі в проекті", PAD, y)
        self.rb_all.Checked = True
        self.rb_all.CheckedChanged += self._on_source_changed
        self.Controls.Add(self.rb_all)

        self.rb_selected = rb(u"Виділені", PAD + 150, y)
        self.rb_selected.CheckedChanged += self._on_source_changed
        self.Controls.Add(self.rb_selected)

        self.rb_collection = rb(u"Колекція:", PAD + 290, y, w=90)
        self.rb_collection.CheckedChanged += self._on_source_changed
        self.Controls.Add(self.rb_collection)
        y += 26

        self.combo_collection = ComboBox()
        self.combo_collection.Font         = Font(u"Segoe UI", 9)
        self.combo_collection.SetBounds(PAD, y, 500, 26)
        self.combo_collection.DropDownStyle = ComboBoxStyle.DropDownList
        self.combo_collection.Enabled       = False
        for param_name, val in sheet_collections:
            self.combo_collection.Items.Add(u"{}: {}".format(param_name, val))
        if self.combo_collection.Items.Count > 0:
            self.combo_collection.SelectedIndex = 0
        self.combo_collection.SelectedIndexChanged += self._on_collection_changed
        self.Controls.Add(self.combo_collection)
        y += 32; self.Controls.Add(sep(y)); y += 12

        # ── 2. Сортування ────────────────────────────────────────────────
        self.Controls.Add(lbl(u"2.  Сортування:", PAD, y, bold=True))
        y += 22

        self.rb_sort_num = rb(u"За номером", PAD, y)
        self.rb_sort_num.Checked = True
        self.rb_sort_num.CheckedChanged += self._on_sort_changed
        self.Controls.Add(self.rb_sort_num)

        self.rb_sort_name = rb(u"За назвою", PAD + 150, y)
        self.rb_sort_name.CheckedChanged += self._on_sort_changed
        self.Controls.Add(self.rb_sort_name)

        self.rb_sort_manual = rb(u"Вручну", PAD + 290, y)
        self.rb_sort_manual.CheckedChanged += self._on_sort_changed
        self.Controls.Add(self.rb_sort_manual)
        y += 30; self.Controls.Add(sep(y)); y += 12

        # ── 3. Список листів ─────────────────────────────────────────────
        self.Controls.Add(lbl(u"3.  Порядок листів (перетягуй для ручного сортування):", PAD, y, bold=True))
        y += 22

        self.sheet_list = ListBox()
        self.sheet_list.Font          = Font(u"Segoe UI", 9)
        self.sheet_list.SetBounds(PAD, y, 500, 190)
        self.sheet_list.SelectionMode  = SelectionMode.One
        self.sheet_list.AllowDrop      = True
        self.sheet_list.MouseDown     += self._on_list_mousedown
        self.sheet_list.MouseMove     += self._on_list_mousemove
        self.sheet_list.DragOver      += self._on_list_dragover
        self.sheet_list.DragDrop      += self._on_list_dragdrop
        self.Controls.Add(self.sheet_list)
        y += 198; self.Controls.Add(sep(y)); y += 12

        # ── 4. Формат номера ─────────────────────────────────────────────
        self.Controls.Add(lbl(u"4.  Формат номера:", PAD, y, bold=True))
        y += 22

        # Рядок 1: Префікс | Початок | Суфікс
        self.Controls.Add(lbl(u"Префікс:", PAD, y + 3, w=70))
        self.txt_prefix = tb(PAD + 74, y, 90, u"")
        self.txt_prefix.TextChanged += self._update_preview
        self.Controls.Add(self.txt_prefix)

        self.Controls.Add(lbl(u"Початок:", PAD + 178, y + 3, w=70))
        self.txt_start = tb(PAD + 252, y, 70, u"1")
        self.txt_start.TextChanged += self._update_preview
        self.Controls.Add(self.txt_start)

        self.Controls.Add(lbl(u"Суфікс:", PAD + 338, y + 3, w=60))
        self.txt_suffix = tb(PAD + 402, y, 98, u"")
        self.txt_suffix.TextChanged += self._update_preview
        self.Controls.Add(self.txt_suffix)
        y += 32

        # Рядок 2: Нулі | Preview
        self.Controls.Add(lbl(u"Нулі зліва (digits):", PAD, y + 3, w=150))
        self.txt_pad = tb(PAD + 154, y, 40, u"0")
        self.txt_pad.TextChanged += self._update_preview
        self.Controls.Add(self.txt_pad)

        self.lbl_preview = Label()
        self.lbl_preview.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        self.lbl_preview.ForeColor = Color.FromArgb(0, 112, 200)
        self.lbl_preview.SetBounds(PAD + 210, y + 3, 308, 18)
        self.lbl_preview.BackColor = BG
        self.Controls.Add(self.lbl_preview)
        y += 32; self.Controls.Add(sep(y)); y += 10

        # ── Кнопки ───────────────────────────────────────────────────────
        btn_ok = Button()
        btn_ok.Text      = u"Пронумерувати"
        btn_ok.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_ok.SetBounds(PAD, y, 220, 32)
        btn_ok.BackColor = Color.FromArgb(0, 112, 200)
        btn_ok.ForeColor = Color.White
        btn_ok.FlatStyle = WinForms.FlatStyle.Flat
        btn_ok.FlatAppearance.BorderSize = 0
        btn_ok.DialogResult = DialogResult.OK
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text         = u"Скасувати"
        btn_cancel.Font         = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(386, y, 132, 32)
        btn_cancel.FlatStyle    = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)

        self.AcceptButton = btn_ok
        self.CancelButton = btn_cancel
        self.Height = y + 90

        # Початкове заповнення
        self._refresh_sheets()
        self._update_preview(None, None)

    # ── Логіка вибору джерела ────────────────────────────────────────────
    def _on_source_changed(self, sender, e):
        self.combo_collection.Enabled = self.rb_collection.Checked
        self._refresh_sheets()

    def _on_collection_changed(self, sender, e):
        if self.rb_collection.Checked:
            self._refresh_sheets()

    def _on_sort_changed(self, sender, e):
        self._refresh_sheets()

    def _refresh_sheets(self):
        """Оновлює список листів відповідно до вибраного джерела і сортування."""
        # Вибір джерела
        if self.rb_all.Checked:
            sheets = list(all_sheets)
        elif self.rb_selected.Checked:
            sheets = get_selected_sheets()
            if not sheets:
                sheets = list(all_sheets)
        else:
            if self.combo_collection.SelectedIndex >= 0 and sheet_collections:
                param_name, val = sheet_collections[self.combo_collection.SelectedIndex]
                sheets = get_sheets_by_collection(param_name, val)
            else:
                sheets = list(all_sheets)

        # Сортування
        if self.rb_sort_num.Checked:
            sheets = sorted(sheets, key=lambda s: s.SheetNumber)
        elif self.rb_sort_name.Checked:
            sheets = sorted(sheets, key=lambda s: s.Name)
        # Вручну — залишаємо як є

        self._sheets = sheets
        self._fill_list()

    def _fill_list(self):
        self.sheet_list.Items.Clear()
        for s in self._sheets:
            self.sheet_list.Items.Add(u"{} — {}".format(s.SheetNumber, s.Name))

    # ── Drag & Drop для ручного сортування ──────────────────────────────
    def _on_list_mousedown(self, sender, e):
        if self.rb_sort_manual.Checked:
            self._drag_index = self.sheet_list.IndexFromPoint(e.X, e.Y)

    def _on_list_mousemove(self, sender, e):
        if self.rb_sort_manual.Checked and e.Button.ToString() == "Left" and self._drag_index >= 0:
            self.sheet_list.DoDragDrop(self._drag_index, DragDropEffects.Move)

    def _on_list_dragover(self, sender, e):
        if self.rb_sort_manual.Checked:
            e.Effect = DragDropEffects.Move

    def _on_list_dragdrop(self, sender, e):
        if not self.rb_sort_manual.Checked:
            return
        target_idx = self.sheet_list.IndexFromPoint(
            self.sheet_list.PointToClient(
                System.Drawing.Point(e.X, e.Y) if False else
                __import__('System.Drawing', fromlist=['Point']).Point(e.X, e.Y)
            )
        )
        src_idx = self._drag_index
        if src_idx < 0 or target_idx < 0 or src_idx == target_idx:
            return
        sheet = self._sheets.pop(src_idx)
        self._sheets.insert(target_idx, sheet)
        self._fill_list()
        self.sheet_list.SelectedIndex = target_idx
        self._drag_index = -1

    # ── Формат і прев'ю ──────────────────────────────────────────────────
    def _format_number(self, n):
        prefix  = self.txt_prefix.Text
        suffix  = self.txt_suffix.Text
        try:
            pad = int(self.txt_pad.Text)
        except Exception:
            pad = 0
        try:
            start = int(self.txt_start.Text)
        except Exception:
            start = 1
        num_str = str(start + n).zfill(pad) if pad > 0 else str(start + n)
        return u"{}{}{}".format(prefix, num_str, suffix)

    def _update_preview(self, sender, e):
        preview = self._format_number(0)
        self.lbl_preview.Text = u"Прев'ю: {}".format(preview)

    def get_sheets(self):
        return self._sheets

    def get_number(self, index):
        return self._format_number(index)


# ════════════════════════════════════════════════════════════════════════════
# КРОК 3: Показуємо форму
# ════════════════════════════════════════════════════════════════════════════
# Потрібен імпорт System.Drawing для drag&drop
import System.Drawing

sheet_form = SheetNumberForm()
if sheet_form.ShowDialog() != DialogResult.OK:
    script.exit()

sheets_to_number = sheet_form.get_sheets()

if not sheets_to_number:
    forms.alert(u"Не знайдено листів для нумерації.", title=u"Листи", warn_icon=True)
    script.exit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 4: Перенумерація
# ════════════════════════════════════════════════════════════════════════════
success_count = 0
error_list    = []

with Transaction(doc, u"Перенумерація листів") as tx:
    tx.Start()

    for i, sheet in enumerate(sheets_to_number):
        new_number = sheet_form.get_number(i)
        try:
            sheet.SheetNumber = new_number
            success_count += 1
        except Exception as ex:
            error_list.append(u"{} → {} : {}".format(
                sheet.SheetNumber, new_number, str(ex)))

    tx.Commit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 5: Звіт
# ════════════════════════════════════════════════════════════════════════════
report = []
report.append(u"✅ Успішно пронумеровано: {}".format(success_count))
if error_list:
    report.append(u"❌ Помилки ({}):\n{}".format(
        len(error_list), u"\n".join(error_list[:10])))

forms.alert(u"\n".join(report), title=u"Результат перенумерації")
