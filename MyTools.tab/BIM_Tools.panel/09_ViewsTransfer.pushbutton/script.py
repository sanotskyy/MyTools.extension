# -*- coding: utf-8 -*-
"""
Перенос/копіювання видів між листами.
- Джерело: виділені Viewport на листі АБО View у диспетчері
- Ціль: зі списку листів АБО активний лист (режим "Відкрити лист")
- Позиція: По центру / Зберегти координати / Вручну
- Режим: Копія / Перенос (видалити з джерела якщо viewport)
- Конфлікт: попередити → Замінити / Пропустити
- Пакетно: всі виділені
"""

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Collections")

from System.Windows.Forms import (
    Form, Label, ComboBox, CheckBox, Button, ListBox,
    DialogResult, FormBorderStyle, FormStartPosition,
    ComboBoxStyle, SelectionMode, MessageBox,
    MessageBoxButtons, MessageBoxIcon, GroupBox,
    RadioButton, Panel, BorderStyle, FlowLayoutPanel,
    FlowDirection, ScrollBars,
)
import System.Windows.Forms as WinForms
from System.Drawing import Point, Size, Color, Font, FontStyle
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FilteredElementCollector, ViewSheet, Viewport,
    View, ViewType, ViewSchedule, ScheduleSheetInstance,
    ElementId, Transaction, XYZ, BoundingBoxUV, ViewDuplicateOption,
)
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ════════════════════════════════════════════════════════════════════════════
# КРОК 1: Збір виділених елементів
# ════════════════════════════════════════════════════════════════════════════
selected_ids = list(uidoc.Selection.GetElementIds())

source_viewports = []  # Viewport на листі
source_views     = []  # View з диспетчера (не розміщені)

for eid in selected_ids:
    el = doc.GetElement(eid)
    if el is None:
        continue
    if isinstance(el, Viewport):
        source_viewports.append(el)
    elif isinstance(el, View):
        if not el.IsTemplate and not isinstance(el, ViewSheet):
            source_views.append(el)

if not source_viewports and not source_views:
    forms.alert(
        u"Виділіть види у диспетчері або Viewport-и на листі.",
        title=u"Перенос видів", warn_icon=True)
    script.exit()

# Визначаємо режим джерела
is_from_sheet = len(source_viewports) > 0
source_count  = len(source_viewports) if is_from_sheet else len(source_views)

# Збираємо всі листи проекту
all_sheets = sorted(
    FilteredElementCollector(doc)
        .OfClass(ViewSheet)
        .WhereElementIsNotElementType()
        .ToElements(),
    key=lambda s: s.SheetNumber
)
sheet_labels = [u"{} — {}".format(s.SheetNumber, s.Name) for s in all_sheets]

# ════════════════════════════════════════════════════════════════════════════
# КРОК 2: Форма
# ════════════════════════════════════════════════════════════════════════════
POSITION_OPTIONS = [
    u"По центру листа",
    u"Зберегти координати",
    u"Вручну (клік на листі)",
]

DUPLICATE_OPTIONS = [
    u"Звичайне (без деталізації)",
    u"З анотаціями (With Detailing)",
    u"Залежний вид (As Dependent)",
]
DUPLICATE_VALUES = [
    ViewDuplicateOption.Duplicate,
    ViewDuplicateOption.WithDetailing,
    ViewDuplicateOption.AsDependent,
]

class MainForm(Form):
    def __init__(self):
        super(MainForm, self).__init__()
        self._wait_mode = False  # режим "відкрий лист і встав"

        BG = Color.FromArgb(245, 245, 248)
        self.Text            = u"Перенос видів між листами"
        self.Width           = 520
        self.Height          = 500
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.BackColor       = BG

        y = 10

        # ── Інфо про джерело ────────────────────────────────────────────
        lbl_src = Label()
        if is_from_sheet:
            lbl_src.Text = u"Джерело: {} Viewport-ів з листа".format(source_count)
        else:
            lbl_src.Text = u"Джерело: {} видів з диспетчера".format(source_count)
        lbl_src.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_src.ForeColor = Color.FromArgb(0, 112, 200)
        lbl_src.SetBounds(12, y, 480, 20)
        self.Controls.Add(lbl_src)
        y += 28

        # ── Режим: Копія / Перенос ───────────────────────────────────────
        grp_mode = GroupBox()
        grp_mode.Text = u"Режим"
        grp_mode.Font = Font(u"Segoe UI", 9)
        grp_mode.SetBounds(12, y, 480, 56)
        grp_mode.BackColor = BG

        self.rb_copy = RadioButton()
        self.rb_copy.Text     = u"Копіювати (залишити на поточному листі)"
        self.rb_copy.Font     = Font(u"Segoe UI", 9)
        self.rb_copy.SetBounds(10, 18, 350, 20)
        self.rb_copy.Checked  = True
        grp_mode.Controls.Add(self.rb_copy)

        self.rb_move = RadioButton()
        self.rb_move.Text     = u"Перенести (видалити з поточного листа)"
        self.rb_move.Font     = Font(u"Segoe UI", 9)
        self.rb_move.SetBounds(10, 36, 350, 20)
        if not is_from_sheet:
            self.rb_move.Enabled = False
            self.rb_move.ForeColor = Color.Gray
        self.rb_copy.CheckedChanged += self._on_copy_move_changed
        self.rb_move.CheckedChanged += self._on_copy_move_changed
        grp_mode.Controls.Add(self.rb_move)

        self.Controls.Add(grp_mode)
        y += 64

        # ── Тип дублювання (лише для "Копіювати", коли вид уже десь
        # розміщений і Revit не дозволяє додати той самий вид ще на один
        # лист — тоді робимо дублікат виду саме цим типом) ──────────────
        lbl_dup = Label()
        lbl_dup.Text = u"Тип дублювання (якщо вид уже розміщений деінде):"
        lbl_dup.Font = Font(u"Segoe UI", 9)
        lbl_dup.SetBounds(12, y, 350, 20)
        self.Controls.Add(lbl_dup)
        self._lbl_dup = lbl_dup
        y += 20

        self.combo_dup = ComboBox()
        self.combo_dup.Font          = Font(u"Segoe UI", 9)
        self.combo_dup.DropDownStyle = ComboBoxStyle.DropDownList
        self.combo_dup.SetBounds(12, y, 480, 24)
        for opt in DUPLICATE_OPTIONS:
            self.combo_dup.Items.Add(opt)
        self.combo_dup.SelectedIndex = 1  # "З анотаціями" — найпоширеніший розумний вибір
        self.Controls.Add(self.combo_dup)
        y += 32

        # ── Позиція ──────────────────────────────────────────────────────
        lbl_pos = Label()
        lbl_pos.Text = u"Позиція на цільовому листі:"
        lbl_pos.Font = Font(u"Segoe UI", 9)
        lbl_pos.SetBounds(12, y, 220, 20)
        self.Controls.Add(lbl_pos)

        self.combo_pos = ComboBox()
        self.combo_pos.Font          = Font(u"Segoe UI", 9)
        self.combo_pos.DropDownStyle = ComboBoxStyle.DropDownList
        self.combo_pos.SetBounds(240, y - 2, 252, 24)
        for opt in POSITION_OPTIONS:
            self.combo_pos.Items.Add(opt)
        # Якщо переносимо з листа (є реальна позиція viewport-а) —
        # за замовчуванням зберігаємо координати, як і просив користувач.
        # Якщо джерело — диспетчер видів (координат ще нема), лишаємо
        # "По центру листа" за замовчуванням.
        self.combo_pos.SelectedIndex = 1 if is_from_sheet else 0
        self.Controls.Add(self.combo_pos)
        y += 32

        # ── Цільовий лист ────────────────────────────────────────────────
        grp_tgt = GroupBox()
        grp_tgt.Text = u"Цільовий лист"
        grp_tgt.Font = Font(u"Segoe UI", 9)
        grp_tgt.SetBounds(12, y, 480, 220)
        grp_tgt.BackColor = BG

        # Варіант 1: обрати зі списку
        self.rb_list = RadioButton()
        self.rb_list.Text    = u"Обрати зі списку:"
        self.rb_list.Font    = Font(u"Segoe UI", 9)
        self.rb_list.SetBounds(10, 18, 200, 20)
        self.rb_list.Checked = True
        self.rb_list.CheckedChanged += self._on_mode_changed
        grp_tgt.Controls.Add(self.rb_list)

        self.txt_filter = WinForms.TextBox()
        self.txt_filter.Font             = Font(u"Segoe UI", 8)
        self.txt_filter.SetBounds(10, 40, 455, 22)
        self.txt_filter.PlaceholderText  = u"Фільтр (номер або назва листа)..."
        self.txt_filter.TextChanged     += self._on_filter
        grp_tgt.Controls.Add(self.txt_filter)

        self.lst_sheets = ListBox()
        self.lst_sheets.Font          = Font(u"Segoe UI", 9)
        self.lst_sheets.SetBounds(10, 64, 455, 110)
        self.lst_sheets.SelectionMode = SelectionMode.One
        self._fill_sheets(u"")
        grp_tgt.Controls.Add(self.lst_sheets)

        # Варіант 2: активний лист
        self.rb_active = RadioButton()
        self.rb_active.Text    = u"Вставити на активний лист"
        self.rb_active.Font    = Font(u"Segoe UI", 9)
        self.rb_active.SetBounds(10, 178, 300, 20)
        self.rb_active.CheckedChanged += self._on_mode_changed
        grp_tgt.Controls.Add(self.rb_active)

        self.Controls.Add(grp_tgt)
        y += 228

        # ── Кнопки ───────────────────────────────────────────────────────
        self.btn_run = Button()
        self.btn_run.Text      = u"Вставити"
        self.btn_run.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        self.btn_run.SetBounds(12, y, 140, 32)
        self.btn_run.BackColor = Color.FromArgb(0, 112, 200)
        self.btn_run.ForeColor = Color.White
        self.btn_run.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_run.FlatAppearance.BorderSize = 0
        self.btn_run.DialogResult = DialogResult.OK
        self.Controls.Add(self.btn_run)

        self.btn_open = Button()
        self.btn_open.Text      = u"Відкрити лист..."
        self.btn_open.Font      = Font(u"Segoe UI", 9)
        self.btn_open.SetBounds(162, y, 140, 32)
        self.btn_open.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_open.Click    += self._on_open_sheet
        self.Controls.Add(self.btn_open)

        btn_cancel = Button()
        btn_cancel.Text         = u"Скасувати"
        btn_cancel.Font         = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(362, y, 130, 32)
        btn_cancel.FlatStyle    = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)

        self.AcceptButton = self.btn_run
        self.CancelButton = btn_cancel
        self.Height = y + 72

        self._on_mode_changed(None, None)
        self._on_copy_move_changed(None, None)

    def _fill_sheets(self, query):
        self.lst_sheets.Items.Clear()
        q = query.strip().lower()
        for lbl in sheet_labels:
            if not q or q in lbl.lower():
                self.lst_sheets.Items.Add(lbl)
        if self.lst_sheets.Items.Count > 0:
            self.lst_sheets.SelectedIndex = 0

    def _on_filter(self, sender, e):
        self._fill_sheets(self.txt_filter.Text)

    def _on_mode_changed(self, sender, e):
        is_list = self.rb_list.Checked
        self.txt_filter.Enabled  = is_list
        self.lst_sheets.Enabled  = is_list
        self.btn_open.Enabled    = not is_list

    def _on_copy_move_changed(self, sender, e):
        is_copy = self.rb_copy.Checked
        self.combo_dup.Enabled = is_copy
        self._lbl_dup.ForeColor = Color.Black if is_copy else Color.Gray

    def _on_open_sheet(self, sender, e):
        self.rb_active.Checked = True
        MessageBox.Show(
            u"Відкрийте потрібний лист у Revit. " + u"Потім натисніть кнопку «Вставити».",
            u"Відкрийте лист",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information)
        self.btn_run.PerformClick()

    def get_config(self):
        is_copy   = self.rb_copy.Checked
        pos_idx   = self.combo_pos.SelectedIndex
        dup_option = DUPLICATE_VALUES[self.combo_dup.SelectedIndex]

        if self.rb_active.Checked:
            target_sheet = None  # використаємо активний вид
        else:
            sel_text = self.lst_sheets.SelectedItem
            if sel_text is None:
                return None
            idx = sheet_labels.index(sel_text)
            target_sheet = all_sheets[idx]

        return {
            u'is_copy':      is_copy,
            u'pos_idx':      pos_idx,
            u'dup_option':   dup_option,
            u'target_sheet': target_sheet,
        }


form = MainForm()
if form.ShowDialog() != DialogResult.OK:
    script.exit()

cfg = form.get_config()
if cfg is None:
    forms.alert(u"Не обрано цільовий лист.", warn_icon=True)
    script.exit()

# ════════════════════════════════════════════════════════════════════════════
# КРОК 3: Визначаємо цільовий лист
# ════════════════════════════════════════════════════════════════════════════
is_copy    = cfg[u'is_copy']
pos_idx    = cfg[u'pos_idx']
dup_option = cfg[u'dup_option']

if cfg[u'target_sheet'] is None:
    # Активний вид має бути листом
    active_view = uidoc.ActiveView
    if not isinstance(active_view, ViewSheet):
        forms.alert(
            u"Активний вид не є листом.\n"
            u"Відкрийте потрібний лист у Revit.",
            title=u"Перенос видів", warn_icon=True)
        script.exit()
    target_sheet = active_view
else:
    target_sheet = cfg[u'target_sheet']

# ════════════════════════════════════════════════════════════════════════════
# КРОК 4: Збираємо view_id і source viewport для кожного
# ════════════════════════════════════════════════════════════════════════════
# pairs: list of (view_id, source_viewport_or_None)
pairs = []

if is_from_sheet:
    for vp in source_viewports:
        pairs.append((vp.ViewId, vp))
else:
    for v in source_views:
        pairs.append((v.Id, None))

# ════════════════════════════════════════════════════════════════════════════
# КРОК 5: Визначаємо позицію
# ════════════════════════════════════════════════════════════════════════════
def get_sheet_center(sheet):
    """Центр листа в координатах листа."""
    try:
        outline = sheet.Outline
        if outline:
            min_pt = outline.Min
            max_pt = outline.Max
            cx = (min_pt.U + max_pt.U) / 2.0
            cy = (min_pt.V + max_pt.V) / 2.0
            return XYZ(cx, cy, 0)
    except Exception:
        pass
    return XYZ(0.14, 0.10, 0)  # fallback ~центр А1


def get_position(view_id, source_vp, pos_idx, index, total):
    """Повертає XYZ позицію для вставки viewport на листі."""
    if pos_idx == 2:
        pt = manual_positions.get(view_id)
        if pt is not None:
            return pt
        # Клік скасовано (Esc) для цього виду — по центру листа
        # замість того, щоб зривати весь перенос через один вид.
        return get_sheet_center(target_sheet)
    if pos_idx == 1 and source_vp:
        # Зберегти координати
        return source_vp.GetBoxCenter()
    elif pos_idx == 0 or not source_vp:
        # По центру листа — зміщуємо якщо кілька видів
        cx = get_sheet_center(target_sheet)
        if total > 1:
            offset = (index - (total - 1) / 2.0) * 0.15
            return XYZ(cx.X + offset, cx.Y, 0)
        return cx
    else:
        return get_sheet_center(target_sheet)


# ════════════════════════════════════════════════════════════════════════════
# КРОК 5б: "Вручну" — просимо користувача клікнути позицію для кожного
# viewport-а ДО транзакції (PickPoint не можна викликати у відкритій
# транзакції). Esc під час кліку пропускає лише цей один вид (буде
# розміщений по центру листа), а не перериває весь перенос.
# ════════════════════════════════════════════════════════════════════════════
manual_positions = {}  # view_id -> XYZ або None (скасовано для цього виду)

if pos_idx == 2:
    # PickPoint дає координати в системі АКТИВНОГО виду — тож цільовий
    # лист має бути активним, інакше клік буде не по тому листі.
    if uidoc.ActiveView.Id != target_sheet.Id:
        try:
            uidoc.ActiveView = target_sheet
        except Exception:
            forms.alert(
                u"Не вдалося активувати цільовий лист для ручного розміщення.\n"
                u"Відкрийте лист «{}» вручну і спробуйте ще раз.".format(
                    target_sheet.SheetNumber),
                title=u"Перенос видів", warn_icon=True)
            script.exit()

    for view_id, source_vp in pairs:
        view = doc.GetElement(view_id)
        view_name = view.Name if view else u"?"
        try:
            pt = uidoc.Selection.PickPoint(
                u"Клікніть, де розмістити вид «{}» (Esc — пропустити, буде по центру)".format(
                    view_name))
            manual_positions[view_id] = pt
        except Exception:
            manual_positions[view_id] = None


# ════════════════════════════════════════════════════════════════════════════
# КРОК 6: Виконання
# ════════════════════════════════════════════════════════════════════════════
success_count  = 0
skipped_count  = 0
error_messages = []

def _collect_existing_placements(doc):
    """Повертає (view_to_viewport, schedule_to_instance) — де саме (на
    якому листі) кожен вид/специфікація ЗАРАЗ розміщені У ВСЬОМУ
    документі, а не лише на цільовому листі. Потрібно, бо Revit НЕ
    дозволяє один вид одразу на двох листах — тому перед вставкою на
    новий лист старе розміщення (якщо є) треба спершу прибрати."""
    view_to_viewport = {}
    for vp in (FilteredElementCollector(doc)
               .OfClass(Viewport)
               .WhereElementIsNotElementType()):
        try:
            view_to_viewport[vp.ViewId] = vp
        except Exception:
            continue
    schedule_to_instance = {}
    for si in (FilteredElementCollector(doc)
               .OfClass(ScheduleSheetInstance)
               .WhereElementIsNotElementType()):
        try:
            schedule_to_instance[si.ScheduleId] = si
        except Exception:
            continue
    return view_to_viewport, schedule_to_instance


with Transaction(doc, u"Перенос/копіювання видів") as tx:
    tx.Start()

    view_to_viewport, schedule_to_instance = _collect_existing_placements(doc)
    target_viewport_ids = set(target_sheet.GetAllViewports())

    total = len(pairs)
    for idx, (view_id, source_vp) in enumerate(pairs):
        view = doc.GetElement(view_id)
        if not view:
            error_messages.append(u"[{}] вид не знайдено".format(view_id))
            continue

        view_name = view.Name
        is_schedule = isinstance(view, ViewSchedule)
        is_legend = (not is_schedule and view.ViewType == ViewType.Legend)

        existing = (schedule_to_instance.get(view_id) if is_schedule
                    else view_to_viewport.get(view_id))

        # Якщо вибір був з диспетчера видів (source_vp немає), але вид
        # усе ж десь уже розміщений — використовуємо ТЕ розміщення як
        # опорне для "Зберегти координати", а не лишаємо порожнім.
        effective_source_vp = source_vp
        if effective_source_vp is None and existing is not None and not is_schedule:
            effective_source_vp = existing

        pos = get_position(view_id, effective_source_vp, pos_idx, idx, total)

        insert_view_id = view_id  # може змінитись на дублікат нижче

        if existing:
            if is_schedule:
                same_target = (getattr(existing, 'OwnerViewId', None) == target_sheet.Id)
            else:
                same_target = existing.Id in target_viewport_ids

            if same_target:
                res = MessageBox.Show(
                    u"Вид «{}» вже є на листі {}.\n"
                    u"Замінити?".format(view_name, target_sheet.SheetNumber),
                    u"Конфлікт",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning)
                if res == DialogResult.No:
                    skipped_count += 1
                    continue
                try:
                    doc.Delete(existing.Id)
                except Exception as ex:
                    error_messages.append(
                        u"[{}] не вдалось прибрати попередній екземпляр: {}".format(
                            view_name, ex))
                    continue

            elif is_legend:
                # Легенди — виняток: Revit нативно дозволяє одну легенду
                # одразу на кількох різних листах, тож нічого прибирати
                # чи дублювати не треба, і для Копіювати, і для Перенести
                # (крім явного "Перенести", де прибираємо саме вихідний
                # екземпляр нижче).
                if not is_copy:
                    try:
                        doc.Delete(existing.Id)
                    except Exception as ex:
                        error_messages.append(
                            u"[{}] не вдалось прибрати з вихідного листа: {}".format(
                                view_name, ex))
                        continue

            elif is_copy:
                # Звичайний вид/специфікація, що вже розміщені на ІНШОМУ
                # листі, і обрано "Копіювати": Revit не дозволяє один вид
                # одразу на двох листах, тому справжня копія можлива
                # лише через дублювання самого виду — оригінал і його
                # розміщення на іншому листі лишаються недоторканими,
                # а на цільовий лист вставляється НОВИЙ (дубльований) вид.
                try:
                    dup_id = view.Duplicate(dup_option)
                    if not dup_id or dup_id == ElementId.InvalidElementId:
                        raise Exception(u"Duplicate() повернув недійсний Id")
                    insert_view_id = dup_id
                except Exception as ex:
                    error_messages.append(
                        u"[{}] не вдалось дублювати вид для копіювання: {}".format(
                            view_name, ex))
                    continue

            else:
                # Перенести: прибираємо з попереднього розміщення першим.
                try:
                    doc.Delete(existing.Id)
                except Exception as ex:
                    error_messages.append(
                        u"[{}] не вдалось прибрати з попереднього розміщення: {}".format(
                            view_name, ex))
                    continue

        # Вставляємо: специфікації — через ScheduleSheetInstance.Create,
        # решта видів (плани, розрізи, фасади, 3D, креслення, легенди) —
        # через Viewport.Create. Це два різні класи елементів у Revit.
        try:
            if is_schedule:
                new_el = ScheduleSheetInstance.Create(doc, target_sheet.Id, insert_view_id, pos)
            else:
                new_el = Viewport.Create(doc, target_sheet.Id, insert_view_id, pos)
            if new_el:
                success_count += 1
            else:
                error_messages.append(u"[{}] вставка повернула None".format(view_name))
        except Exception as ex:
            error_messages.append(u"[{}] помилка вставки: {}".format(view_name, ex))

    tx.Commit()

# ════════════════════════════════════════════════════════════════════════════
# КРОК 7: Звіт
# ════════════════════════════════════════════════════════════════════════════
report = []
report.append(u"✅ Успішно: {}".format(success_count))
if skipped_count:
    report.append(u"⏭ Пропущено: {}".format(skipped_count))
if error_messages:
    report.append(u"")
    report.append(u"❌ Помилки:")
    for msg in error_messages:
        report.append(u"  • " + msg)

forms.alert(u"\n".join(report), title=u"Результат")
