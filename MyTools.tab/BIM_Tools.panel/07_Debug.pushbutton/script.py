# -*- coding: utf-8 -*-
"""Діагностика: що бачить скрипт Параметри для виділеного елемента."""
from Autodesk.Revit.DB import (
    StorageType, ElementId, FamilyInstance, AssemblyInstance
)
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

selected_ids = list(uidoc.Selection.GetElementIds())
if not selected_ids:
    forms.alert(u"Виділіть елемент.", warn_icon=True)
    script.exit()

el = doc.GetElement(selected_ids[0])
output = script.get_output()

# ── Крок 1: тип елемента ────────────────────────────────────────────────
output.print_md(u"## Елемент: {} [{}]".format(type(el).__name__, el.Id))
output.print_md(u"**FamilyInstance:** {}  |  **AssemblyInstance:** {}".format(
    isinstance(el, FamilyInstance), isinstance(el, AssemblyInstance)))

# ── Крок 2: сирий перебір Parameters ────────────────────────────────────
output.print_md(u"### Сирий el.Parameters:")
ST_INT = {
    int(StorageType.String):    u"String",
    int(StorageType.Double):    u"Double",
    int(StorageType.Integer):   u"Integer",
    int(StorageType.ElementId): u"ElemId",
}
_READ_INT = set([
    int(StorageType.String),
    int(StorageType.Double),
    int(StorageType.Integer),
])

rows = []
try:
    params_list = list(el.Parameters)
    output.print_md(u"Кількість параметрів: **{}**".format(len(params_list)))
    for p in params_list:
        try:
            st      = p.StorageType
            st_int  = int(st)
            st_name = ST_INT.get(st_int, u"?({})".format(st_int))
            ro      = u"RO" if p.IsReadOnly else u"rw"
            name    = p.Definition.Name
            in_read = st_int in _READ_INT
            rows.append(u"[{} {} readable={}]  {}".format(st_name, ro, in_read, name))
        except Exception as ex:
            rows.append(u"[ERR param] {}".format(ex))
except Exception as ex:
    output.print_md(u"**ПОМИЛКА list(el.Parameters): {}**".format(ex))

for r in sorted(rows):
    output.print_md(r)

# ── Крок 3: перевірка ADSK_Количество окремо ────────────────────────────
output.print_md(u"### Пряме LookupParameter('ADSK_\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e'):")
try:
    p = el.LookupParameter(u'ADSK_\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e')
    if p:
        st_int = int(p.StorageType)
        output.print_md(u"Знайдено! StorageType={} int={} RO={} AsDouble={}".format(
            p.StorageType, st_int, p.IsReadOnly,
            p.AsDouble() if st_int == int(StorageType.Double) else u"N/A"))
    else:
        output.print_md(u"**None** — параметр не знайдено через LookupParameter")
except Exception as ex:
    output.print_md(u"**ПОМИЛКА:** {}".format(ex))

# ── Крок 4: симуляція collect_text_params ───────────────────────────────
output.print_md(u"### Симуляція _collect_params_from_el (writable_only=False):")
found = {}
try:
    for p in list(el.Parameters):
        try:
            st     = p.StorageType
            st_int = int(st)
            if st_int not in _READ_INT:
                continue
            name = p.Definition.Name
            key  = (name, u'sys_inst')
            if key not in found:
                found[key] = u"[{} {}] {}".format(
                    ST_INT.get(st_int, u"?"), u"RO" if p.IsReadOnly else u"rw", name)
        except Exception as ex:
            output.print_md(u"param ERR: {}".format(ex))
except Exception as ex:
    output.print_md(u"**ПОМИЛКА ітерації:** {}".format(ex))

output.print_md(u"Зібрано параметрів: **{}**".format(len(found)))
for k, v in sorted(found.items()):
    output.print_md(v)

# ── Крок 5: всі ImageType в проекті ─────────────────────────────────────
output.print_md(u"### ImageType в проекті:")
try:
    from Autodesk.Revit.DB import FilteredElementCollector, ImageType
    imgs = FilteredElementCollector(doc).OfClass(ImageType).ToElements()
    output.print_md(u"Кількість: **{}**".format(len(list(imgs))))
    for img in list(imgs)[:20]:
        try:
            output.print_md(u"  [{}] {}".format(img.Id, img.Path))
        except Exception as ex:
            output.print_md(u"  [ERR] {}".format(ex))
except Exception as ex:
    output.print_md(u"**ПОМИЛКА:** {}".format(ex))
