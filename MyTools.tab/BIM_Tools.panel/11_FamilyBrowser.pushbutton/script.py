# -*- coding: utf-8 -*-
"""Диспетчер сімейств: за замовчуванням показує типи, вже завантажені в
проєкт (миттєвий пошук/фільтр за категорією, розміщення одним кліком чи
перетягуванням). Перемикач зверху відкриває другорядний режим — .rfa з
локальних бібліотек (сканування диска лише за явним запитом).

Ізольована кнопка — логіку інших кнопок MyTools.extension не чіпає,
лише читає lib/mytools_familybrowser.py.
"""
import os
import sys

from pyrevit import forms


def _find_ext_root(start_dir):
    """Йде вгору від папки кнопки, поки не знайде extension.json."""
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
    import mytools_familybrowser as fb
except Exception as ex:
    forms.alert(
        u"Не вдалося завантажити модуль диспетчера сімейств "
        u"(lib/mytools_familybrowser.py):\n\n{0}".format(ex),
        title=u"MyTools — Диспетчер сімейств",
        warn_icon=True
    )
    sys.exit()

# Вікно немодальне: усі виклики Revit API усередині йдуть через ExternalEvent,
# який створюється саме тут (у валідному контексті API).
fb.show_family_browser(__revit__)
