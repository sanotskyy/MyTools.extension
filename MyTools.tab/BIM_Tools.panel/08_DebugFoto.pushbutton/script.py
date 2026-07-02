# -*- coding: utf-8 -*-
"""Показує точну категорію та параметри WallSweep і подібних елементів."""
from Autodesk.Revit.DB import StorageType, ElementId, ElementType
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()

selected_ids = list(uidoc.Selection.GetElementIds())
if not selected_ids:
    forms.alert(u"Виділіть елемент.", warn_icon=True)
    script.exit()

el = doc.GetElement(selected_ids[0])
output.print_md(u"## {} [{}]".format(type(el).__name__, el.Id))

try:
    cat = el.Category
    output.print_md(u"Категорія: **{}**".format(cat.Name if cat else u"None"))
except Exception as ex:
    output.print_md(u"Категорія: ERR {}".format(ex))

ST = {
    int(StorageType.String):    u"String",
    int(StorageType.Double):    u"Double",
    int(StorageType.Integer):   u"Integer",
    int(StorageType.ElementId): u"ElemId",
}

def dump_params(target, label):
    output.print_md(u"### {}".format(label))
    try:
        rows = []
        for p in list(target.Parameters):
            try:
                st   = ST.get(int(p.StorageType), u"?")
                ro   = u"RO" if p.IsReadOnly else u"rw"
                name = p.Definition.Name
                if int(p.StorageType) == int(StorageType.String):
                    val = repr(p.AsString())
                elif int(p.StorageType) == int(StorageType.Double):
                    val = str(p.AsDouble())
                elif int(p.StorageType) == int(StorageType.Integer):
                    val = str(p.AsInteger())
                elif int(p.StorageType) == int(StorageType.ElementId):
                    val = str(p.AsElementId())
                else:
                    val = u"?"
                rows.append(u"[{} {}] {} = {}".format(st, ro, name, val))
            except Exception as ex:
                rows.append(u"[ERR] {}".format(ex))
        for r in sorted(rows):
            output.print_md(r)
    except Exception as ex:
        output.print_md(u"**ПОМИЛКА: {}**".format(ex))

dump_params(el, u"Параметри екземпляра")

try:
    tid = el.GetTypeId()
    if tid and tid != ElementId.InvalidElementId:
        te = doc.GetElement(tid)
        if te:
            output.print_md(u"Тип: **{} [{}]**".format(type(te).__name__, te.Id))
            dump_params(te, u"Параметри типу")
        else:
            output.print_md(u"Тип: GetElement -> None")
    else:
        output.print_md(u"Тип: InvalidElementId")
except Exception as ex:
    output.print_md(u"Тип: ERR {}".format(ex))
