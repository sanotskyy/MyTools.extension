# -*- coding: utf-8 -*-
"""startup.py - автоматична перевірка оновлень при запуску pyRevit (асинхронно)."""
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
    clr.AddReference("System.Threading")
    from System.Windows.Forms import (
        Form, Label, Button, DialogResult,
        FormBorderStyle, FormStartPosition
    )
    from System.Drawing import Font, FontStyle, Color
    from System.Threading import Thread, ThreadStart, ApartmentState
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
    lbl2.Text      = u"Поточна версія:  " + local_ver
    lbl2.Font      = Font(u"Segoe UI", 9)
    lbl2.ForeColor = Color.FromArgb(40, 40, 40)
    lbl2.SetBounds(16, 44, 340, 20)
    form.Controls.Add(lbl2)

    lbl3 = Label()
    lbl3.Text      = u"Нова версія:     " + remote_ver
    lbl3.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
    lbl3.ForeColor = Color.FromArgb(0, 140, 0)
    lbl3.SetBounds(16, 64, 340, 20)
    form.Controls.Add(lbl3)

    lbl4 = Label()
    lbl4.Text      = u"Натисніть кнопку «Оновлення» в панелі BIM Tools."
    lbl4.Font      = Font(u"Segoe UI", 8)
    lbl4.ForeColor = Color.FromArgb(100, 100, 120)
    lbl4.SetBounds(16, 92, 340, 18)
    form.Controls.Add(lbl4)

    btn = Button()
    btn.Text         = u"OK"
    btn.SetBounds(284, 108, 72, 28)
    btn.DialogResult = DialogResult.OK
    form.Controls.Add(btn)
    form.AcceptButton = btn

    form.ShowDialog()


def _check_thread():
    """Виконується в окремому потоці - не блокує запуск Revit."""
    try:
        # Затримка 10 секунд - чекаємо поки Revit повністю завантажиться
        import time
        time.sleep(10)

        result = check_for_updates()
        if result and result.get(u'has_update'):
            local_ver  = result.get(u'local',  u'?')
            remote_ver = result.get(u'remote', u'?')

            # Показуємо вікно через STA поток (Windows Forms вимагає STA)
            def _show():
                _show_notice(local_ver, remote_ver)

            sta = Thread(ThreadStart(_show))
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
