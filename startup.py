# -*- coding: utf-8 -*-
"""startup.py - автоматична перевірка оновлень при запуску pyRevit (асинхронно)."""
import os
import sys

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_EXT_DIR, u"lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    from mytools_updater import check_for_updates, install_update
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    clr.AddReference("System.Threading")
    from System.Windows.Forms import (
        Form, Label, Button, ProgressBar, DialogResult,
        FormBorderStyle, FormStartPosition, MessageBox,
        MessageBoxButtons, MessageBoxIcon, Application
    )
    import System.Windows.Forms as WinForms
    from System.Drawing import Font, FontStyle, Color
    from System.Threading import Thread, ThreadStart, ApartmentState
except Exception:
    raise SystemExit

BG     = Color.FromArgb(245, 245, 248)
ACCENT = Color.FromArgb(0, 112, 200)
TEXT   = Color.FromArgb(40, 40, 40)
LIGHT  = Color.FromArgb(110, 110, 130)
GREEN  = Color.FromArgb(0, 140, 0)
RED    = Color.FromArgb(180, 40, 40)


class UpdateNotice(Form):
    def __init__(self, check_result):
        super(UpdateNotice, self).__init__()
        self._result = check_result
        local_ver  = check_result.get(u'local',  u'?')
        remote_ver = check_result.get(u'remote', u'?')

        self.Text            = u"MyTools — Доступне оновлення"
        self.Width           = 400
        self.Height          = 200
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.TopMost         = True
        self.BackColor       = BG

        lbl1 = Label()
        lbl1.Text      = u"✨  Доступне оновлення MyTools!"
        lbl1.Font      = Font(u"Segoe UI", 10, FontStyle.Bold)
        lbl1.ForeColor = ACCENT
        lbl1.SetBounds(16, 14, 360, 22)
        self.Controls.Add(lbl1)

        lbl2 = Label()
        lbl2.Text      = u"Поточна версія:  " + local_ver
        lbl2.Font      = Font(u"Segoe UI", 9)
        lbl2.ForeColor = TEXT
        lbl2.SetBounds(16, 44, 360, 20)
        self.Controls.Add(lbl2)

        lbl3 = Label()
        lbl3.Text      = u"Нова версія:     " + remote_ver
        lbl3.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl3.ForeColor = GREEN
        lbl3.SetBounds(16, 64, 360, 20)
        self.Controls.Add(lbl3)

        self._lbl_status = Label()
        self._lbl_status.Text      = u""
        self._lbl_status.Font      = Font(u"Segoe UI", 8)
        self._lbl_status.ForeColor = LIGHT
        self._lbl_status.SetBounds(16, 90, 360, 18)
        self.Controls.Add(self._lbl_status)

        self._progress = ProgressBar()
        self._progress.SetBounds(16, 110, 360, 8)
        self._progress.Style   = WinForms.ProgressBarStyle.Marquee
        self._progress.Visible = False
        self.Controls.Add(self._progress)

        self._btn_install = Button()
        self._btn_install.Text      = u"Встановити зараз"
        self._btn_install.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        self._btn_install.SetBounds(16, 128, 160, 30)
        self._btn_install.BackColor = ACCENT
        self._btn_install.ForeColor = Color.White
        self._btn_install.FlatStyle = WinForms.FlatStyle.Flat
        self._btn_install.FlatAppearance.BorderSize = 0
        self._btn_install.Click    += self._on_install
        self.Controls.Add(self._btn_install)

        btn_later = Button()
        btn_later.Text         = u"Пізніше"
        btn_later.Font         = Font(u"Segoe UI", 9)
        btn_later.SetBounds(186, 128, 90, 30)
        btn_later.FlatStyle    = WinForms.FlatStyle.Flat
        btn_later.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_later)
        self.CancelButton = btn_later

    def _on_install(self, sender, e):
        self._btn_install.Enabled  = False
        self._lbl_status.Text      = u"Встановлення…"
        self._lbl_status.ForeColor = LIGHT
        self._progress.Visible     = True
        Application.DoEvents()

        ok, msg = install_update(self._result)

        self._progress.Visible = False
        if ok:
            self._lbl_status.Text      = u"✓  " + msg
            self._lbl_status.ForeColor = GREEN
            MessageBox.Show(
                u"Оновлення встановлено! " + u"Розширення буде перезавантажено автоматично.",
                u"Готово", MessageBoxButtons.OK, MessageBoxIcon.Information)
            self.Close()
            try:
                from pyrevit.loader import sessionmgr
                sessionmgr.reload_pyrevit()
            except Exception:
                pass
        else:
            self._lbl_status.Text      = u"✗  " + msg
            self._lbl_status.ForeColor = RED
            self._btn_install.Enabled  = True


def _run_notice(check_result):
    form = UpdateNotice(check_result)
    form.ShowDialog()


def _check_thread():
    try:
        import time
        time.sleep(10)

        result = check_for_updates()
        if result and result.get(u'has_update'):
            sta = Thread(ThreadStart(lambda: _run_notice(result)))
            sta.SetApartmentState(ApartmentState.STA)
            sta.Start()
            sta.Join()
    except Exception:
        pass


try:
    t = Thread(ThreadStart(_check_thread))
    t.IsBackground = True
    t.Start()
except Exception:
    pass
