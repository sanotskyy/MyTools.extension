# -*- coding: utf-8 -*-
"""Піпетка кольору: Увімк/Вимк спостерігача за системним діалогом 'Цвет'.

НОВА, повністю ізольована кнопка. Логіку інших кнопок MyTools.extension
цей файл не чіпає і від них не залежить — лише читає lib/mytools_colorpicker.py.
"""
import os
import sys

from pyrevit import forms


def _find_ext_root(start_dir):
    """Йде вгору від папки кнопки, поки не знайде extension.json —
    так, незалежно від того, на скільки рівнів вкладена кнопка
    (у стеку чи напряму на панелі)."""
    d = start_dir
    for _ in range(8):
        if os.path.isfile(os.path.join(d, u"extension.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


_ext_dir = _find_ext_root(os.path.dirname(os.path.abspath(__file__)))
if _ext_dir:
    _lib_dir = os.path.join(_ext_dir, u"lib")
    if _lib_dir not in sys.path:
        sys.path.insert(0, _lib_dir)

try:
    import mytools_colorpicker as cp
except Exception as ex:
    forms.alert(
        u"Не вдалося завантажити модуль піпетки (lib/mytools_colorpicker.py):\n\n{0}".format(ex),
        title=u"MyTools — Піпетка",
        warn_icon=True
    )
    script_exit = True
else:
    script_exit = False

if not script_exit:
    watcher = cp.get_watcher()

    if watcher.is_running():
        watcher.stop()
        forms.alert(u"Піпетку кольору вимкнено.", title=u"MyTools — Піпетка")
    else:
        try:
            watcher.start()
        except Exception as ex:
            forms.alert(
                u"Не вдалося запустити піпетку:\n\n{0}".format(ex),
                title=u"MyTools — Піпетка",
                warn_icon=True
            )
        else:
            forms.alert(
                u"Піпетку увімкнено!\n\n"
                u"Відкрийте діалог вибору кольору (\"Цвет\") у Диспетчері "
                u"матеріалів — поруч з ним автоматично з'явиться маленька "
                u"кругла кнопка.\n\n"
                u"Натисніть її, потім клікніть будь-де на екрані (навіть "
                u"поза вікном Revit) — колір під курсором одразу впишеться "
                u"у поля Red/Green/Blue. Esc під час наведення — скасувати.\n\n"
                u"ОК / Добавить у діалозі \"Цвет\" — тиснете самі.\n\n"
                u"Щоб вимкнути піпетку — натисніть цю кнопку ще раз.",
                title=u"MyTools — Піпетка"
            )
