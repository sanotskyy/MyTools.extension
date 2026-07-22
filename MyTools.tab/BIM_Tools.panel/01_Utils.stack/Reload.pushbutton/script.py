# -*- coding: utf-8 -*-
"""
Перезавантажити.pushbutton/script.py
Перезавантажує розширення MyTools через pyRevit без перезапуску Revit.
"""
from pyrevit import script
from pyrevit.loader import sessionmgr

try:
    sessionmgr.reload_pyrevit()
except Exception as e:
    from pyrevit import forms
    forms.alert(u"Помилка перезавантаження: " + str(e), title=u"MyTools")
