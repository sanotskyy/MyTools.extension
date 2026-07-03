# -*- coding: utf-8 -*-
"""
startup.py - автоматична перевірка оновлень при запуску pyRevit.
"""
import os
import sys

_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_DIR = os.path.join(_EXT_DIR, u"lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    from mytools_updater import check_for_updates
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, Label, Button, DialogResult,
        FormBorderStyle, FormStartPosition
    )
    from System.Drawing import Font, FontStyle, Color
except Exception:
    raise SystemExit


def _show_notice(local_ver, remote_ver):
    form = Form()
    form.Text            = u"MyTools — Доступне оновлення"
    form.Width           = 380
    form.Height          = 165
    form.StartPosition   = FormStartPosition.CenterScreen
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.MaximizeBox     = False
    form.MinimizeBox     = False
    form.TopMost         = True
    form.BackColor       = Color.FromArgb(245, 245, 248)

    lbl1 = Label()
    lbl1.Text      = u"✨  Доступне оновлення MyTools!"
    lbl1.Font      = Font(u"Segoe UI", 10, FontStyle.Bold)
    lbl1.ForeColor = Color.FromArgb(0, 112, 200)
    lbl1.SetBounds(16, 14, 340, 22)
    form.Controls.Add(lbl1)

    lbl2 = Label()
    lbl2.Text      = u"Поточна версія:  {}
Нова версія:     {}".format(
        local_ver, remote_ver)
    lbl2.Font      = Font(u"Segoe UI", 9)
    lbl2.ForeColor = Color.FromArgb(40, 40, 40)
    lbl2.SetBounds(16, 44, 340, 40)
    form.Controls.Add(lbl2)

    lbl3 = Label()
    lbl3.Text      = u'Натисніть кнопку "Оновлення" в панелі BIM Tools.'
    lbl3.Font      = Font(u"Segoe UI", 8)
    lbl3.ForeColor = Color.FromArgb(100, 100, 120)
    lbl3.SetBounds(16, 86, 340, 18)
    form.Controls.Add(lbl3)

    btn = Button()
    btn.Text         = u"OK"
    btn.SetBounds(284, 100, 72, 28)
    btn.DialogResult = DialogResult.OK
    form.Controls.Add(btn)
    form.AcceptButton = btn

    form.ShowDialog()


try:
    result = check_for_updates()
    if result and result.get(u'has_update'):
        _show_notice(
            result.get(u'local',  u'?'),
            result.get(u'remote', u'?')
        )
except Exception:
    pass
