# -*- coding: utf-8 -*-
import sys, os
import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System.Windows.Forms as WinForms
from System.Windows.Forms import Form, Label, Button, ProgressBar, FormBorderStyle, FormStartPosition, MessageBox, MessageBoxButtons, MessageBoxIcon
from System.Drawing import Color, Font, FontStyle

_ext_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), u"..","..","..",".."))
if _ext_dir not in sys.path:
    sys.path.insert(0, os.path.join(_ext_dir, u"lib"))

from mytools_updater import check_for_updates, install_update

BG        = Color.FromArgb(245, 245, 248)
ACCENT    = Color.FromArgb(0, 112, 200)
TEXT      = Color.FromArgb(40, 40, 40)
LIGHT     = Color.FromArgb(110, 110, 130)
ERR       = Color.FromArgb(180, 40, 40)
OK_CLR    = Color.FromArgb(0, 140, 0)
BTN_BG    = Color.FromArgb(206, 212, 207)
BTN_BD    = Color.FromArgb(160, 168, 162)
SEP_CLR   = Color.FromArgb(205, 205, 215)

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

class UpdateDialog(Form):
    def __init__(self):
        super(UpdateDialog, self).__init__()
        self.Text            = u"MyTools \u2014 \u041e\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f"
        self.Width           = 420
        self.Height          = 220
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.StartPosition   = FormStartPosition.CenterScreen
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG

        y = 16
        h = Label()
        h.Text = u"\u041f\u0435\u0440\u0435\u0432\u0456\u0440\u043a\u0430 \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u044c"
        h.Font = Font(u"Segoe UI", 11, FontStyle.Bold)
        h.ForeColor = ACCENT
        h.BackColor = BG
        h.SetBounds(20, y, 360, 26)
        self.Controls.Add(h)
        y += 34

        s1 = Label(); s1.SetBounds(20, y, 360, 1); s1.BackColor = SEP_CLR
        self.Controls.Add(s1); y += 12

        self._lbl_local = Label()
        self._lbl_local.Font = Font(u"Segoe UI", 9)
        self._lbl_local.ForeColor = TEXT
        self._lbl_local.BackColor = BG
        self._lbl_local.SetBounds(20, y, 360, 18)
        self._lbl_local.Text = u"\u041f\u043e\u0442\u043e\u0447\u043d\u0430 \u0432\u0435\u0440\u0441\u0456\u044f:  \u2026"
        self.Controls.Add(self._lbl_local); y += 22

        self._lbl_remote = Label()
        self._lbl_remote.Font = Font(u"Segoe UI", 9)
        self._lbl_remote.ForeColor = TEXT
        self._lbl_remote.BackColor = BG
        self._lbl_remote.SetBounds(20, y, 360, 18)
        self._lbl_remote.Text = u"\u0412\u0435\u0440\u0441\u0456\u044f \u043d\u0430 GitHub:  \u2026"
        self.Controls.Add(self._lbl_remote); y += 26

        self._lbl_status = Label()
        self._lbl_status.Font = Font(u"Segoe UI", 9)
        self._lbl_status.ForeColor = LIGHT
        self._lbl_status.BackColor = BG
        self._lbl_status.SetBounds(20, y, 360, 18)
        self._lbl_status.Text = u"\u041f\u0435\u0440\u0435\u0432\u0456\u0440\u043a\u0430\u2026"
        self.Controls.Add(self._lbl_status); y += 22

        self._progress = ProgressBar()
        self._progress.SetBounds(20, y, 360, 8)
        self._progress.Style = WinForms.ProgressBarStyle.Marquee
        self.Controls.Add(self._progress); y += 16

        s2 = Label(); s2.SetBounds(20, y, 360, 1); s2.BackColor = SEP_CLR
        self.Controls.Add(s2); y += 10

        self._btn_install = mkbtn(u"\u0412\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u0438 \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f", 20, y, 180, bold=True)
        self._btn_install.Enabled = False
        self._btn_install.Click  += self._on_install
        self.Controls.Add(self._btn_install)

        self._btn_close = mkbtn(u"\u0417\u0430\u043a\u0440\u0438\u0442\u0438", 210, y, 90)
        self._btn_close.Click += lambda s, e: self.Close()
        self.Controls.Add(self._btn_close)

        self.Height = y + 76
        self._check_result = None
        self.Shown += self._on_shown

    def _on_shown(self, sender, e):
        WinForms.Application.DoEvents()
        self._do_check()

    def _do_check(self):
        self._lbl_status.Text = u"\u0417'\u0454\u0434\u043d\u0430\u043d\u043d\u044f \u0437 GitHub\u2026"
        self._lbl_status.ForeColor = LIGHT
        self._progress.Visible = True
        WinForms.Application.DoEvents()

        result = check_for_updates()
        self._check_result = result
        self._progress.Visible = False
        self._lbl_local.Text  = u"\u041f\u043e\u0442\u043e\u0447\u043d\u0430 \u0432\u0435\u0440\u0441\u0456\u044f:  " + result[u'local']
        self._lbl_remote.Text = u"\u0412\u0435\u0440\u0441\u0456\u044f \u043d\u0430 GitHub:  " + result[u'remote']

        if result[u'error']:
            self._lbl_status.Text = u"\u26a0  " + result[u'error']
            self._lbl_status.ForeColor = ERR
        elif result[u'has_update']:
            self._lbl_status.Text = u"\u2713  \u0414\u043e\u0441\u0442\u0443\u043f\u043d\u0435 \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f!"
            self._lbl_status.ForeColor = OK_CLR
            self._btn_install.Enabled = True
        else:
            self._lbl_status.Text = u"\u2713  \u0423 \u0432\u0430\u0441 \u043e\u0441\u0442\u0430\u043d\u043d\u044f \u0432\u0435\u0440\u0441\u0456\u044f."
            self._lbl_status.ForeColor = OK_CLR

    def _on_install(self, sender, e):
        self._btn_install.Enabled = False
        self._btn_close.Enabled   = False
        self._lbl_status.Text = u"\u0412\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f\u2026"
        self._lbl_status.ForeColor = LIGHT
        self._progress.Visible = True
        WinForms.Application.DoEvents()

        ok, msg = install_update(self._check_result)
        self._progress.Visible  = False
        self._btn_close.Enabled = True

        if ok:
            self._lbl_status.Text = u"\u2713  " + msg
            self._lbl_status.ForeColor = OK_CLR
            MessageBox.Show(
                u"\u041e\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044f \u0432\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e!\n\u0420\u043e\u0437\u0448\u0438\u0440\u0435\u043d\u043d\u044f \u0431\u0443\u0434\u0435 \u043f\u0435\u0440\u0435\u0437\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0435\u043d\u043e \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u043d\u043e.",
                u"\u0413\u043e\u0442\u043e\u0432\u043e", MessageBoxButtons.OK, MessageBoxIcon.Information)
            self.Close()
            try:
                from pyrevit.loader import sessionmgr
                sessionmgr.reload_pyrevit()
            except Exception:
                pass
        else:
            self._lbl_status.Text = u"\u2717  " + msg
            self._lbl_status.ForeColor = ERR
            self._btn_install.Enabled = True

dlg = UpdateDialog()
dlg.ShowDialog()
