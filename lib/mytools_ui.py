# -*- coding: utf-8 -*-
"""
mytools_ui.py — спільні UI-утиліти для MyTools.extension
"""

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

import System.Windows.Forms as WinForms
from System.Windows.Forms import (
    ComboBox, ComboBoxStyle, Label, Button, TextBox, Form,
    FormBorderStyle, FormStartPosition, DialogResult, MessageBox,
    MessageBoxButtons, MessageBoxIcon,
)
from System.Drawing import Color, Font, FontStyle


# ────────────────────────────────────────────────────────────────────────────
#  Кольорова палітра
# ────────────────────────────────────────────────────────────────────────────
BG_COLOR         = Color.FromArgb(245, 245, 248)
ACCENT_COLOR     = Color.FromArgb(0, 112, 200)
SEPARATOR_COLOR  = Color.FromArgb(205, 205, 215)
TEXT_COLOR       = Color.FromArgb(40, 40, 40)
LIGHT_TEXT_COLOR = Color.FromArgb(110, 110, 130)
WARN_COLOR       = Color.FromArgb(160, 70, 0)
ERROR_TEXT_COLOR = Color.FromArgb(180, 40, 40)
PLACEHOLDER_COLOR = Color.FromArgb(160, 160, 160)


# ────────────────────────────────────────────────────────────────────────────
#  Базові helpers
# ────────────────────────────────────────────────────────────────────────────

def make_label(text, x, y, w=464, bold=False, color=None):
    l = Label()
    l.Text      = text
    l.Font      = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
    l.ForeColor = color if color else TEXT_COLOR
    l.BackColor = BG_COLOR
    l.SetBounds(x, y, w, 17)
    return l


def make_separator(x, y, w=464):
    s = Label()
    s.SetBounds(x, y, w, 1)
    s.BackColor = SEPARATOR_COLOR
    return s


def make_textbox(x, y, w, text=u"", readonly=False):
    tb = TextBox()
    tb.SetBounds(x, y, w, 24)
    tb.Font     = Font(u"Segoe UI", 9)
    tb.Text     = text
    tb.ReadOnly = readonly
    if readonly:
        tb.BackColor = Color.White
    return tb


def make_button(text, x, y, w, h=32, primary=False, danger=False):
    btn = Button()
    btn.Text      = text
    btn.Font      = Font(u"Segoe UI", 9, FontStyle.Bold if primary else FontStyle.Regular)
    btn.SetBounds(x, y, w, h)
    btn.FlatStyle = WinForms.FlatStyle.Flat
    btn.FlatAppearance.BorderSize = 0 if primary else 1
    if primary:
        btn.BackColor = ACCENT_COLOR
        btn.ForeColor = Color.White
    elif danger:
        btn.ForeColor = ERROR_TEXT_COLOR
    return btn


def make_header(text, x, y, w=464):
    l = Label()
    l.Text      = text
    l.Font      = Font(u"Segoe UI", 10, FontStyle.Bold)
    l.ForeColor = Color.FromArgb(20, 20, 20)
    l.BackColor = BG_COLOR
    l.SetBounds(x, y, w, 22)
    return l


def highlight_error(ctrl):
    ctrl.BackColor = Color.FromArgb(255, 180, 180)


def clear_error(ctrl):
    ctrl.BackColor = Color.White


# ────────────────────────────────────────────────────────────────────────────
#  FilteredComboBox — ComboBox з живою фільтрацією
# ────────────────────────────────────────────────────────────────────────────

class FilteredComboBox(ComboBox):
    """
    ComboBox з фільтрацією списку при введенні тексту.
    ESC скидає фільтр і повертає повний список.
    """
    def __init__(self, all_items):
        super(FilteredComboBox, self).__init__()
        self._all_items = list(all_items)
        self._updating  = False

        self.DropDownStyle      = ComboBoxStyle.DropDown
        self.Font               = Font(u"Segoe UI", 9)
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
        import System.Drawing as Drawing
        if e.Index < 0:
            return
        e.DrawBackground()
        e.Graphics.DrawString(
            self.Items[e.Index],
            e.Font,
            Drawing.SolidBrush(Drawing.Color.FromArgb(40, 40, 40)),
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
            elif self.Items.Count == 0 and self.DroppedDown:
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

    def update_items(self, new_items):
        self._all_items = list(new_items)
        self._fill(self._all_items)
        if self.Items.Count > 0:
            self.SelectedIndex = 0


# ────────────────────────────────────────────────────────────────────────────
#  InputDialog — простий діалог введення рядка
# ────────────────────────────────────────────────────────────────────────────

class InputDialog(Form):
    def __init__(self, title, prompt, default=u""):
        super(InputDialog, self).__init__()
        self.value = u""
        self.Text            = title
        self.Width           = 380
        self.Height          = 140
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition   = FormStartPosition.CenterParent
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG_COLOR

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

        btn_ok = make_button(u"OK", 14, 68, 80, 28, primary=True)
        btn_ok.DialogResult = DialogResult.OK
        btn_ok.Click += self._on_ok
        self.Controls.Add(btn_ok)
        self.AcceptButton = btn_ok

        btn_cancel = make_button(u"Скасувати", 104, 68, 90, 28)
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)
        self.CancelButton = btn_cancel

    def _on_ok(self, sender, e):
        self.value = self._tb.Text
        self.DialogResult = DialogResult.OK
