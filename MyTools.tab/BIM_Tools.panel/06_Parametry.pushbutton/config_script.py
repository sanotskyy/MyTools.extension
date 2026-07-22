# -*- coding: utf-8 -*-
"""
Діагностика: виводить ВСІ параметри виділеного елемента з типом StorageType.
Запускати вручну через pyRevit console або як окремий скрипт.
"""
from Autodesk.Revit.DB import StorageType, ElementId
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

selected_ids = list(uidoc.Selection.GetElementIds())
if not selected_ids:
    forms.alert(u"Нічого не виділено.", warn_icon=True)
    script.exit()

el = doc.GetElement(selected_ids[0])
lines = []
lines.append(u"Елемент: {} [{}]".format(type(el).__name__, el.Id))
lines.append(u"")

ST_MAP = {
    StorageType.String:    u"String",
    StorageType.Double:    u"Double",
    StorageType.Integer:   u"Integer",
    StorageType.ElementId: u"ElementId",
    StorageType.None:      u"None",
}

def collect_all(target, label):
    rows = []
    try:
        for p in target.Parameters:
            st = ST_MAP.get(p.StorageType, u"?")
            ro = u"RO" if p.IsReadOnly else u"rw"
            try:
                name = p.Definition.Name
            except Exception:
                name = u"<err>"
            try:
                if p.StorageType == StorageType.String:
                    val = repr(p.AsString())
                elif p.StorageType == StorageType.Double:
                    val = str(p.AsDouble())
                elif p.StorageType == StorageType.Integer:
                    val = str(p.AsInteger())
                elif p.StorageType == StorageType.ElementId:
                    val = str(p.AsElementId())
                else:
                    val = u"-"
            except Exception as e:
                val = u"ERR: {}".format(e)
            rows.append(u"  [{} {}] {} = {}".format(st, ro, name, val))
    except Exception as ex:
        rows.append(u"  ПОМИЛКА ітерації: {}".format(ex))
    if rows:
        lines.append(label)
        lines.extend(sorted(rows))
        lines.append(u"")

collect_all(el, u"=== Параметри ЕКЗЕМПЛЯРА ===")

try:
    type_id = el.GetTypeId()
    if type_id and type_id != ElementId.InvalidElementId:
        type_el = doc.GetElement(type_id)
        if type_el:
            collect_all(type_el, u"=== Параметри ТИПУ [{}] ===".format(type(type_el).__name__))
        else:
            lines.append(u"Тип: GetTypeId()={} але GetElement повернув None".format(type_id))
    else:
        lines.append(u"Тип: GetTypeId() = InvalidElementId (немає типу)")
except Exception as ex:
    lines.append(u"Помилка GetTypeId: {}".format(ex))

output = script.get_output()
output.print_md(u"\n".join(lines))
