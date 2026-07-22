# -*- coding: utf-8 -*-
import sys, os
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System.Windows.Forms as WinForms
from System.Windows.Forms import Form, Label, RadioButton, Button, TextBox, FormBorderStyle, FormStartPosition
from System.Drawing import Color, Font, FontStyle

_ext_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), u"..","..","..",".."))
if _ext_dir not in sys.path:
    sys.path.insert(0, os.path.join(_ext_dir, u"lib"))

from mytools_updater import load_settings, save_settings, save_repo_url, get_repo_url

BG        = Color.FromArgb(245, 245, 248)
ACCENT    = Color.FromArgb(0, 112, 200)
TEXT      = Color.FromArgb(40, 40, 40)
LIGHT     = Color.FromArgb(110, 110, 130)
BTN_BG    = Color.FromArgb(206, 212, 207)
BTN_BD    = Color.FromArgb(160, 168, 162)
SEP_COLOR = Color.FromArgb(205, 205, 215)

def mkbtn(text, x, y, w, bold=False):
    b = Button()
    b.Text      = text
    b.Font      = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
    b.SetBounds(x, y, w, 28)
    b.FlatStyle = WinForms.FlatStyle.Flat
    b.FlatAppearance.BorderColor = BTN_BD
    b.FlatAppearance.BorderSize  = 1
    b.BackColor  = BTN_BG
    b.ForeColor  = TEXT
    b.UseVisualStyleBackColor = False
    return b

def mksep(form, x, y, w):
    s = Label()
    s.SetBounds(x, y, w, 1)
    s.BackColor = SEP_COLOR
    form.Controls.Add(s)

def mklbl(form, text, x, y, w=340, bold=False, color=None):
    l = Label()
    l.Text = text
    l.Font = Font(u"Segoe UI", 9, FontStyle.Bold if bold else FontStyle.Regular)
    l.ForeColor = color if color else TEXT
    l.BackColor = BG
    l.SetBounds(x, y, w, 18)
    form.Controls.Add(l)

class SettingsDialog(Form):
    def __init__(self):
        super(SettingsDialog, self).__init__()
        self.Text            = u"MyTools \u2014 \u041d\u0430\u043b\u0430\u0448\u0442\u0443\u0432\u0430\u043d\u043d\u044f"
        self.Width           = 400
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition   = FormStartPosition.CenterScreen
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG

        settings = load_settings()
        y = 16

        # Заголовок
        h = Label()
        h.Text = u"\u041d\u0430\u043b\u0430\u0448\u0442\u0443\u0432\u0430\u043d\u043d\u044f"
        h.Font = Font(u"Segoe UI", 11, FontStyle.Bold)
        h.ForeColor = ACCENT
        h.BackColor = BG
        h.SetBounds(20, y, 340, 26)
        self.Controls.Add(h)
        y += 34

        mksep(self, 20, y, 340); y += 12

        # URL
        mklbl(self, u"URL \u0440\u0435\u043f\u043e\u0437\u0438\u0442\u043e\u0440\u0456\u044e GitHub:", 20, y, bold=True)
        y += 22

        self._tb = TextBox()
        self._tb.Font = Font(u"Segoe UI", 9)
        self._tb.SetBounds(20, y, 340, 24)
        self._tb.Text = get_repo_url() or u"https://github.com/sanotskyy/MyTools.extension"
        self.Controls.Add(self._tb)
        y += 28

        mklbl(self, u"https://github.com/\u0432\u0430\u0448-\u043b\u043e\u0433\u0456\u043d/MyTools.extension", 20, y, color=LIGHT)
        y += 22

        mksep(self, 20, y, 340); y += 12

        # Режим
        mklbl(self, u"\u0420\u0435\u0436\u0438\u043c \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u044c:", 20, y, bold=True)
        y += 22

        self._rb_auto = RadioButton()
        self._rb_auto.Text = u"\u0410\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u043d\u043e \u043f\u0440\u0438 \u043a\u043e\u0436\u043d\u043e\u043c\u0443 \u0437\u0430\u043f\u0443\u0441\u043a\u0443 Revit"
        self._rb_auto.Font = Font(u"Segoe UI", 9)
        self._rb_auto.ForeColor = TEXT
        self._rb_auto.BackColor = BG
        self._rb_auto.SetBounds(20, y, 340, 22)
        self._rb_auto.Checked = settings.get(u'auto_update', False)
        self.Controls.Add(self._rb_auto)
        y += 24

        self._rb_manual = RadioButton()
        self._rb_manual.Text = u"\u0412\u0440\u0443\u0447\u043d\u0443 (\u0447\u0435\u0440\u0435\u0437 \u043a\u043d\u043e\u043f\u043a\u0443 \u041e\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f)"
        self._rb_manual.Font = Font(u"Segoe UI", 9)
        self._rb_manual.ForeColor = TEXT
        self._rb_manual.BackColor = BG
        self._rb_manual.SetBounds(20, y, 340, 22)
        self._rb_manual.Checked = not settings.get(u'auto_update', False)
        self.Controls.Add(self._rb_manual)
        y += 28

        mksep(self, 20, y, 340); y += 10

        b1 = mkbtn(u"\u0417\u0431\u0435\u0440\u0435\u0433\u0442\u0438", 20, y, 100, bold=True)
        b1.Click += self._on_save
        self.Controls.Add(b1)

        b2 = mkbtn(u"\u0421\u043a\u0430\u0441\u0443\u0432\u0430\u0442\u0438", 130, y, 100)
        b2.Click += lambda s, e: self.Close()
        self.Controls.Add(b2)

        self.Height = y + 68

    def _on_save(self, sender, e):
        settings = load_settings()
        settings[u'auto_update'] = self._rb_auto.Checked
        save_settings(settings)
        url = self._tb.Text.strip()
        if url:
            save_repo_url(url)
        self.Close()

dlg = SettingsDialog()
dlg.ShowDialog()
