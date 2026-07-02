# -*- coding: utf-8 -*-
"""
Параметри:
- Вкладка 1: Копіювати (до 5 пар, з приміщення)
- Вкладка 2: Підсімейства (до 5 пар + шаблони)
- Вкладка 3: Умови
- Вкладка 4: Заміна тексту
- Вкладка 5: Збірки (читання/запис параметрів збірок)

Підтримує системні сімейства (Стіни, Перекриття, Стелі, Покриття, Сходи,
Пандуси, Перила, Зони, ColorFillRegion тощо) — автоматично.
"""

import clr
import re
import os
import json

clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Collections")

from System.Windows.Forms import (
    Form, Label, ComboBox, CheckBox, Button, Panel, TextBox, RadioButton,
    TabControl, TabPage, FlowLayoutPanel, FlowDirection, ListBox,
    DialogResult, FormBorderStyle, FormStartPosition,
    ComboBoxStyle, BorderStyle, SelectionMode,
    MessageBox, MessageBoxButtons, MessageBoxIcon,
    GroupBox, DockStyle,
)
import System.Windows.Forms as WinForms
from System.Drawing import Point, Size, Color, Font, FontStyle
from System.Collections.Generic import List

from Autodesk.Revit.DB import (
    FamilyInstance, FilteredElementCollector,
    BuiltInCategory, StorageType, ElementId, Transaction,
    AssemblyInstance, Element,
)
from Autodesk.Revit.DB.Architecture import Room
from pyrevit import forms, script

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
MAX_PAIRS = 5


# ════════════════════════════════════════════════════════════════════════════
# КРОК 1: Перевірка виділення
# ════════════════════════════════════════════════════════════════════════════
selected_ids = list(uidoc.Selection.GetElementIds())
if not selected_ids:
    forms.alert(u"Не виділено жодного елемента.", title=u"Параметри", warn_icon=True)
    script.exit()

selected_instances  = []  # FamilyInstance
selected_assemblies = []  # AssemblyInstance
selected_generic    = []  # Системні елементи (Стіни, Перекриття, Стелі тощо)

for eid in selected_ids:
    el = doc.GetElement(eid)
    if el is None:
        continue
    if isinstance(el, FamilyInstance):
        selected_instances.append(el)
    elif isinstance(el, AssemblyInstance):
        selected_assemblies.append(el)
    elif isinstance(el, Room):
        pass  # Room — тільки як джерело параметрів
    else:
        # Будь-який елемент з параметрами: системні сімейства та ін.
        try:
            _ = el.Parameters
            selected_generic.append(el)
        except Exception:
            pass

all_selected = selected_instances + selected_assemblies + selected_generic

if not all_selected:
    forms.alert(u"Серед виділених елементів немає підтримуваних елементів.",
                title=u"Параметри", warn_icon=True)
    script.exit()


def is_system_element(el):
    """Повертає True якщо елемент — системне сімейство (не FamilyInstance і не AssemblyInstance)."""
    return not isinstance(el, FamilyInstance) and not isinstance(el, AssemblyInstance)


# ════════════════════════════════════════════════════════════════════════════
# КРОК 2: Допоміжні функції
# ════════════════════════════════════════════════════════════════════════════
def get_room(instance):
    try:
        phase_id = instance.CreatedPhaseId
        if phase_id:
            phase = doc.GetElement(phase_id)
            if phase:
                r = instance.get_Room(phase)
                if r and hasattr(r, 'LookupParameter'):
                    return r
    except Exception:
        pass
    try:
        phases = doc.Phases
        for i in range(phases.Size):
            phase = phases.get_Item(i)
            try:
                r = instance.get_Room(phase)
                if r and hasattr(r, 'LookupParameter'):
                    return r
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_nested(instance, depth=2):
    result = []
    if depth == 0:
        return result

    if isinstance(instance, AssemblyInstance):
        try:
            for mid in instance.GetMemberIds():
                el = doc.GetElement(mid)
                if isinstance(el, FamilyInstance):
                    result.append(el)
        except Exception:
            pass
        return result

    if is_system_element(instance):
        # Системні сімейства не мають підкомпонентів
        return result

    try:
        for sid in instance.GetSubComponentIds():
            el = doc.GetElement(sid)
            if isinstance(el, FamilyInstance):
                result.append(el)
                result.extend(get_nested(el, depth - 1))
    except Exception:
        pass
    return result


# Типи StorageType які дозволяємо як ДЖЕРЕЛО (читання → конвертація у рядок)
_READABLE_STORAGE = (StorageType.String, StorageType.Double, StorageType.Integer)
# int-значення для надійного порівняння в IronPython 2
_READABLE_STORAGE_INT = set([int(StorageType.String), int(StorageType.Double), int(StorageType.Integer)])


def _param_storage_ok(p, writable_only, is_source):
    """Перевіряє чи параметр підходить для збору."""
    if is_source:
        # Джерело: String + Double + Integer (тільки для читання, конвертуємо)
        return p.StorageType in _READABLE_STORAGE
    else:
        # Ціль: тільки String і тільки якщо не ReadOnly
        if p.StorageType != StorageType.String:
            return False
        if p.IsReadOnly:
            return False
        return True


def _collect_params_from_el(el, writable_only, level_inst, level_type, found):
    """Збирає параметри екземпляра та типу з будь-якого елемента.
    writable_only=True → тільки цілі (String, !ReadOnly)
    writable_only=False → джерела (String + Double + Integer для ВСІХ елементів)
    """
    # Параметри екземпляра
    try:
        params_iter = list(el.Parameters)
    except Exception:
        params_iter = []
    for p in params_iter:
        try:
            st = p.StorageType
            # Ціль: тільки String не-ReadOnly
            if writable_only:
                # Ціль: String + Double + Integer, але не ReadOnly
                if int(st) not in _READABLE_STORAGE_INT or p.IsReadOnly:
                    continue
            else:
                # Джерело: String + Double + Integer
                if int(st) not in _READABLE_STORAGE_INT:
                    continue
            name = p.Definition.Name
            key  = (name, level_inst)
            if key not in found:
                found[key] = {
                    'name':         name,
                    'level':        level_inst,
                    'source':       'element',
                    'readonly':     p.IsReadOnly,
                    'storage_type': st,
                }
        except Exception:
            continue

    # Параметри типу
    try:
        type_id = el.GetTypeId()
        if type_id and type_id != ElementId.InvalidElementId:
            type_el = doc.GetElement(type_id)
            if type_el:
                try:
                    type_params_iter = list(type_el.Parameters)
                except Exception:
                    type_params_iter = []
                for p in type_params_iter:
                    try:
                        st = p.StorageType
                        if writable_only:
                            if int(st) not in _READABLE_STORAGE_INT or p.IsReadOnly:
                                continue
                        else:
                            if int(st) not in _READABLE_STORAGE_INT:
                                continue
                        name = p.Definition.Name
                        key  = (name, level_type)
                        if key not in found:
                            found[key] = {
                                'name':         name,
                                'level':        level_type,
                                'source':       'element',
                                'readonly':     p.IsReadOnly,
                                'storage_type': st,
                            }
                    except Exception:
                        continue
    except Exception:
        pass


def collect_text_params(elements, writable_only=False):
    """
    Збирає текстові параметри для будь-яких елементів.
    FamilyInstance/AssemblyInstance → level 'instance'/'type'
    Системні → level 'sys_inst'/'sys_type'
    Обидва набори повертаються разом.
    """
    found = {}
    for el in elements:
        if is_system_element(el):
            _collect_params_from_el(el, writable_only, 'sys_inst', 'sys_type', found)
        else:
            _collect_params_from_el(el, writable_only, 'instance', 'type', found)
    return sorted(found.values(), key=lambda x: x['name'])


def collect_room_params(instances):
    found = {}
    for inst in instances:
        if is_system_element(inst):
            continue
        room = get_room(inst)
        if not room:
            continue
        try:
            for p in room.Parameters:
                if int(p.StorageType) in _READABLE_STORAGE_INT:
                    name = p.Definition.Name
                    if name not in found:
                        found[name] = {'name': name, 'level': 'room',
                                       'source': 'room', 'readonly': True,
                                       'storage_type': p.StorageType}
        except Exception:
            pass
    if not found:
        try:
            all_rooms = FilteredElementCollector(doc)\
                .OfCategory(BuiltInCategory.OST_Rooms)\
                .WhereElementIsNotElementType().ToElements()
            for r in all_rooms:
                try:
                    for p in r.Parameters:
                        if int(p.StorageType) in _READABLE_STORAGE_INT:
                            name = p.Definition.Name
                            if name not in found:
                                found[name] = {'name': name, 'level': 'room',
                                               'source': 'room', 'readonly': True,
                                               'storage_type': p.StorageType}
                    if found:
                        break
                except Exception:
                    continue
        except Exception:
            pass
    return sorted(found.values(), key=lambda x: x['name'])


def _resolve_el(element, level):
    """Повертає element або його type залежно від level."""
    if level in ('type', 'sys_type'):
        try:
            type_id = element.GetTypeId()
            if type_id and type_id != ElementId.InvalidElementId:
                return doc.GetElement(type_id)
        except Exception:
            pass
    return element


def _read_param_as_string(p, doc_ref=None):
    """Читає параметр будь-якого типу і повертає рядок або None."""
    if not p:
        return None
    st = p.StorageType
    st_int = int(st)
    if st_int == int(StorageType.String):
        val = p.AsString()
        return val if val else None
    if st_int == int(StorageType.Double):
        try:
            raw = p.AsDouble()
            try:
                from Autodesk.Revit.DB import UnitUtils
                unit_type = p.GetUnitTypeId()
                converted = UnitUtils.ConvertFromInternalUnits(raw, unit_type)
                result = u"{:.4f}".format(converted).rstrip('0').rstrip('.')
                return result if result else u"0"
            except Exception:
                result = u"{:.6f}".format(raw).rstrip('0').rstrip('.')
                return result if result else u"0"
        except Exception:
            return None
    if st_int == int(StorageType.Integer):
        try:
            return u"{}".format(p.AsInteger())
        except Exception:
            return None
    return None


def get_value(element, param):
    if param.get('source') == 'room':
        if is_system_element(element):
            return None
        room = get_room(element)
        if not room:
            return None
        p = room.LookupParameter(param['name'])
    else:
        el = _resolve_el(element, param['level'])
        if not el:
            return None
        p = el.LookupParameter(param['name'])
    return _read_param_as_string(p)


def _str_to_number(value):
    """Конвертує рядок у число для запису в Double/Integer параметр."""
    try:
        # Прибираємо пробіли, замінюємо кому на крапку
        cleaned = value.strip().replace(u',', u'.')
        return float(cleaned)
    except Exception:
        return None


def set_value(element, param, value):
    el = _resolve_el(element, param['level'])
    if not el:
        return False
    p = el.LookupParameter(param['name'])
    if not p or p.IsReadOnly:
        return False
    st_int = int(p.StorageType)
    if st_int == int(StorageType.String):
        p.Set(value)
        return True
    if st_int == int(StorageType.Double):
        num = _str_to_number(value)
        if num is None:
            return False
        try:
            # Конвертуємо з одиниць відображення у внутрішні одиниці Revit
            from Autodesk.Revit.DB import UnitUtils
            unit_type = p.GetUnitTypeId()
            internal_val = UnitUtils.ConvertToInternalUnits(num, unit_type)
            p.Set(internal_val)
        except Exception:
            # Fallback: пишемо сире значення
            p.Set(num)
        return True
    if st_int == int(StorageType.Integer):
        num = _str_to_number(value)
        if num is None:
            return False
        p.Set(int(round(num)))
        return True
    return False


def get_param_val(element, param):
    """Читає значення параметра — для будь-якого рівня включно з sys_inst/sys_type.
    Підтримує String, Double (→ рядок з одиницями), Integer.
    """
    el = _resolve_el(element, param.get('level', 'instance'))
    if not el:
        return None
    p = el.LookupParameter(param['name'])
    val = _read_param_as_string(p)
    return val.strip() if val else None


# ════════════════════════════════════════════════════════════════════════════
# ЗБІРКИ: допоміжні функції (без змін)
# ════════════════════════════════════════════════════════════════════════════
def collect_assembly_type_params(assemblies, writable_only=False):
    found = {}
    for asm in assemblies:
        try:
            asm_type = doc.GetElement(asm.GetTypeId())
            if not asm_type:
                continue
            for p in asm_type.Parameters:
                st = p.StorageType
                if writable_only:
                    if int(st) not in _READABLE_STORAGE_INT or p.IsReadOnly:
                        continue
                else:
                    if int(st) not in _READABLE_STORAGE_INT:
                        continue
                key = p.Definition.Name
                if key not in found:
                    found[key] = {'name': key, 'level': 'asm_type',
                                  'source': 'assembly', 'readonly': p.IsReadOnly,
                                  'storage_type': st}
        except Exception:
            pass
    return sorted(found.values(), key=lambda x: x['name'])


def collect_assembly_instance_params(assemblies, writable_only=False):
    found = {}
    for asm in assemblies:
        try:
            for p in asm.Parameters:
                st = p.StorageType
                if writable_only:
                    if int(st) not in _READABLE_STORAGE_INT or p.IsReadOnly:
                        continue
                else:
                    if int(st) not in _READABLE_STORAGE_INT:
                        continue
                key = p.Definition.Name
                if key not in found:
                    found[key] = {'name': key, 'level': 'asm_instance',
                                  'source': 'assembly', 'readonly': p.IsReadOnly,
                                  'storage_type': st}
        except Exception:
            pass
    return sorted(found.values(), key=lambda x: x['name'])


def get_all_assemblies_for_members(members):
    assemblies = {}
    for el in members:
        try:
            asm_id = el.AssemblyInstanceId
            if asm_id and asm_id != ElementId.InvalidElementId:
                asm = doc.GetElement(asm_id)
                if asm and isinstance(asm, AssemblyInstance):
                    assemblies[asm_id] = asm
        except Exception:
            pass
    return list(assemblies.values())


def get_assembly_param_value(asm, param_info):
    try:
        if param_info['level'] == 'asm_type':
            el = doc.GetElement(asm.GetTypeId())
        else:
            el = asm
        if not el:
            return None
        p = el.LookupParameter(param_info['name'])
        v = _read_param_as_string(p)
        return v.strip() if v else None
    except Exception:
        pass
    return None


def get_member_param_value(member, param_info):
    try:
        el = _resolve_el(member, param_info.get('level', 'instance'))
        if not el:
            return None
        p = el.LookupParameter(param_info['name'])
        v = _read_param_as_string(p)
        return v.strip() if v else None
    except Exception:
        pass
    return None


def set_member_param_value(member, param_info, value):
    try:
        el = _resolve_el(member, param_info.get('level', 'instance'))
        if not el:
            return False
        p = el.LookupParameter(param_info['name'])
        if p and not p.IsReadOnly and p.StorageType == StorageType.String:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


def set_assembly_param_value(asm, param_info, value):
    try:
        if param_info['level'] == 'asm_type':
            el = doc.GetElement(asm.GetTypeId())
        else:
            el = asm
        if not el:
            return False
        p = el.LookupParameter(param_info['name'])
        if p and not p.IsReadOnly and p.StorageType == StorageType.String:
            p.Set(value)
            return True
    except Exception:
        pass
    return False


# ════════════════════════════════════════════════════════════════════════════
# КРОК 3: Збір параметрів
# ════════════════════════════════════════════════════════════════════════════

# ── Визначаємо хости і підсімейства ─────────────────────────────────────
# Якщо виділено підсімейство (має SuperComponent) — знаходимо його хост.
# Якщо виділено хост — знаходимо підсімейства через GetSubComponentIds().
# Дедублікація: кожна пара хост→підсімейство обробляється тільки раз.

_explicit_hosts    = {}   # id -> element: прямо виділені хости
_explicit_nested   = {}   # id -> element: прямо виділені підсімейства
_auto_hosts        = {}   # id -> element: хости знайдені через SuperComponent

for inst in selected_instances:
    try:
        parent = inst.SuperComponent
        if parent and isinstance(parent, FamilyInstance):
            # Це підсімейство — запам'ятовуємо його і його хост
            _explicit_nested[inst.Id] = inst
            _auto_hosts[parent.Id]    = parent
        else:
            _explicit_hosts[inst.Id] = inst
    except Exception:
        _explicit_hosts[inst.Id] = inst

# Всі унікальні хости = прямо виділені + знайдені через SuperComponent
_all_host_ids = set(list(_explicit_hosts.keys()) + list(_auto_hosts.keys()))
_all_hosts_map = {}
for eid in _all_host_ids:
    if eid in _explicit_hosts:
        _all_hosts_map[eid] = _explicit_hosts[eid]
    else:
        _all_hosts_map[eid] = _auto_hosts[eid]

# Збираємо підсімейства: для кожного хоста беремо його підкомпоненти
# Якщо підсімейство вже було виділено явно — воно вже в _explicit_nested
all_nested = []
_nested_ids_seen = set()

for eid, host in _all_hosts_map.items():
    # Підсімейства виділені явно для цього хоста
    for nid, nel in _explicit_nested.items():
        try:
            if nel.SuperComponent and nel.SuperComponent.Id == eid:
                if nid not in _nested_ids_seen:
                    all_nested.append(nel)
                    _nested_ids_seen.add(nid)
        except Exception:
            pass
    # Підсімейства через GetSubComponentIds (якщо хост виділений прямо)
    if eid in _explicit_hosts:
        nested_via_sub = get_nested(host)
        for nel in nested_via_sub:
            if nel.Id not in _nested_ids_seen:
                all_nested.append(nel)
                _nested_ids_seen.add(nel.Id)

# Для збірок залишаємо як було
for asm in selected_assemblies:
    members = get_nested(asm)
    if members:
        all_nested.extend(members)

has_nested = len(all_nested) > 0

# host_elements = всі хости (прямо виділені + знайдені через SuperComponent)
host_elements = list(_all_hosts_map.values()) + selected_assemblies

# selected_instances оновлюємо щоб включати і хости і підсімейства для інших вкладок
# (вкладки Копіювати, Умови, Заміна тексту — працюють з all_selected)

# Всі елементи разом для збору параметрів
_all_elements = selected_instances + selected_assemblies + selected_generic

elem_src_params = collect_text_params(_all_elements, writable_only=False)
elem_tgt_params = collect_text_params(_all_elements, writable_only=True)
room_src_params = collect_room_params(selected_instances)
nested_params   = collect_text_params(all_nested, writable_only=False)
nested_w_params = collect_text_params(all_nested, writable_only=True)
host_w_params   = collect_text_params(selected_instances + selected_assemblies, writable_only=True)

# Параметри збірок
_direct_assemblies = selected_assemblies if selected_assemblies else []
_member_assemblies = get_all_assemblies_for_members(selected_instances) if selected_instances else []
_all_assemblies_for_tab = list({a.Id: a for a in _direct_assemblies + _member_assemblies}.values())

asm_type_params_all  = collect_assembly_type_params(_all_assemblies_for_tab, writable_only=False)
asm_type_params_w    = collect_assembly_type_params(_all_assemblies_for_tab, writable_only=True)
asm_inst_params_all  = collect_assembly_instance_params(_all_assemblies_for_tab, writable_only=False)
asm_inst_params_w    = collect_assembly_instance_params(_all_assemblies_for_tab, writable_only=True)
asm_all_src_params   = asm_type_params_all + asm_inst_params_all
asm_all_tgt_params   = asm_type_params_w   + asm_inst_params_w

_all_members = []
for asm in _all_assemblies_for_tab:
    _all_members.extend(get_nested(asm))
member_src_params = collect_text_params(_all_members, writable_only=False)
member_tgt_params = collect_text_params(_all_members, writable_only=True)


def _numeric_suffix(p):
    """Додає позначку якщо параметр числовий (буде конвертовано у рядок)."""
    st = p.get('storage_type')
    if st is None:
        return u""
    try:
        st_int = int(st)
    except Exception:
        return u""
    if st_int == int(StorageType.Double):
        return u" #"
    if st_int == int(StorageType.Integer):
        return u" #int"
    return u""


def elem_src_label(p):
    if p.get('source') == 'room':
        return u"{} [приміщення]".format(p['name'])
    level = p['level']
    suffix = _numeric_suffix(p)
    if level == 'sys_inst':
        return u"{}{} [сист. екземпляр]".format(p['name'], suffix)
    if level == 'sys_type':
        return u"{}{} [сист. тип]".format(p['name'], suffix)
    lbl = u"тип" if level == 'type' else u"екземпляр"
    return u"{}{} [{}]".format(p['name'], suffix, lbl)

def elem_tgt_label(p):
    level  = p['level']
    suffix = _numeric_suffix(p)
    if level == 'sys_inst':
        return u"{}{} [сист. екземпляр]".format(p['name'], suffix)
    if level == 'sys_type':
        return u"{}{} [сист. тип]".format(p['name'], suffix)
    lbl = u"тип" if level == 'type' else u"екземпляр"
    return u"{}{} [{}]".format(p['name'], suffix, lbl)

def asm_src_label(p):
    if p['level'] == 'asm_type':
        return u"{} [тип збірки]".format(p['name'])
    return u"{} [екз. збірки]".format(p['name'])

def asm_tgt_label(p):
    return asm_src_label(p)

def member_label(p):
    level = p['level']
    if level == 'sys_inst':
        return u"{} [сист. екземпляр]".format(p['name'])
    if level == 'sys_type':
        return u"{} [сист. тип]".format(p['name'])
    lbl = u"тип" if level == 'type' else u"екземпляр"
    return u"{} [{}]".format(p['name'], lbl)


copy_src_params          = elem_src_params + room_src_params
copy_src_labels          = [elem_src_label(p) for p in copy_src_params]
copy_tgt_labels          = [elem_tgt_label(p) for p in elem_tgt_params]
all_elem_labels          = [elem_tgt_label(p) for p in elem_src_params]
tgt_labels_all           = [elem_tgt_label(p) for p in elem_tgt_params]
nested_src_labels_host   = [elem_tgt_label(p) for p in elem_src_params]
nested_src_labels_nested = [elem_tgt_label(p) for p in nested_params]
nested_tgt_labels_host   = [elem_tgt_label(p) for p in host_w_params]
nested_tgt_labels_nested = [elem_tgt_label(p) for p in nested_w_params]

asm_src_labels    = [asm_src_label(p) for p in asm_all_src_params]
asm_tgt_labels    = [asm_tgt_label(p) for p in asm_all_tgt_params]
member_src_labels = [member_label(p) for p in member_src_params]
member_tgt_labels = [member_label(p) for p in member_tgt_params]

OPERATORS = [
    u"равно", u"не равно", u"выше", u"ровно или выше",
    u"ниже", u"ровно или ниже", u"имеет значение", u"без значения",
]

# Інфо-рядок про виділені елементи
_sys_count = len(selected_generic)
_fam_count = len(selected_instances)
_asm_count = len(selected_assemblies)

_info_parts = []
if _fam_count:
    _info_parts.append(u"Сімейств: {}".format(_fam_count))
if _asm_count:
    _info_parts.append(u"Збірок: {}".format(_asm_count))
if _sys_count:
    _info_parts.append(u"Системних: {}".format(_sys_count))
SELECTION_INFO = u"   |   ".join(_info_parts) if _info_parts else u""


# ════════════════════════════════════════════════════════════════════════════
# КРОК 4: FilteredComboBox
# ════════════════════════════════════════════════════════════════════════════
class FilteredComboBox(object):
    def __init__(self, all_labels, width):
        self._all    = list(all_labels)
        self._active = list(all_labels)
        self.combo = ComboBox()
        self.combo.Size = Size(width, 24)
        self.combo.DropDownStyle = ComboBoxStyle.DropDown
        self.combo.AutoCompleteMode = 0
        self._fill(all_labels)
        if self.combo.Items.Count > 0:
            self.combo.SelectedIndex = 0
        self.combo.TextChanged += self._on_text_changed
        self.combo.DropDown    += self._on_dropdown

    def _fill(self, labels):
        self.combo.Items.Clear()
        for lbl in labels:
            self.combo.Items.Add(lbl)
        self._active = list(labels)

    def _on_text_changed(self, sender, e):
        query = self.combo.Text.strip().lower()
        filtered = [l for l in self._all if query in l.lower()] if query else list(self._all)
        if filtered != self._active:
            cur = self.combo.Text
            self._fill(filtered)
            self.combo.Text = cur
            try:
                self.combo.SelectionStart = len(cur)
            except Exception:
                pass
            if filtered:
                self.combo.DroppedDown = True

    def _on_dropdown(self, sender, e):
        if not self.combo.Text.strip():
            self._fill(list(self._all))

    def update_labels(self, new_labels):
        self._all    = list(new_labels)
        self._active = list(new_labels)
        self._fill(new_labels)
        if self.combo.Items.Count > 0:
            self.combo.SelectedIndex = 0


# ════════════════════════════════════════════════════════════════════════════
# КРОК 5: Рядки для вкладок
# ════════════════════════════════════════════════════════════════════════════
class CopyPairRow(object):
    def __init__(self):
        self.panel = Panel()
        self.panel.Size = Size(680, 36)
        self.panel.BorderStyle = getattr(BorderStyle, 'None')
        self.src = FilteredComboBox(copy_src_labels, 295)
        self.src.combo.Location = Point(0, 6)
        lbl = Label()
        lbl.Text = u"→"
        lbl.Location = Point(302, 10)
        lbl.Size = Size(18, 20)
        self.tgt = FilteredComboBox(copy_tgt_labels, 295)
        self.tgt.combo.Location = Point(324, 6)
        self.btn_del = Button()
        self.btn_del.Text = u"✕"
        self.btn_del.Location = Point(628, 6)
        self.btn_del.Size = Size(36, 24)
        self.btn_del.Tag = self
        self.panel.Controls.Add(self.src.combo)
        self.panel.Controls.Add(lbl)
        self.panel.Controls.Add(self.tgt.combo)
        self.panel.Controls.Add(self.btn_del)

    def get_pair(self):
        src_text = self.src.combo.Text.strip()
        tgt_text = self.tgt.combo.Text.strip()
        src_idx  = next((i for i, l in enumerate(copy_src_labels) if l == src_text), 0)
        tgt_idx  = next((i for i, l in enumerate(copy_tgt_labels) if l == tgt_text), 0)
        return copy_src_params[src_idx], elem_tgt_params[tgt_idx]


class ConditionRow(object):
    def __init__(self):
        self.panel = Panel()
        self.panel.Size = Size(690, 78)
        self.panel.BorderStyle = BorderStyle.FixedSingle

        lbl_if = Label()
        lbl_if.Text = u"ЯКЩО"
        lbl_if.Location = Point(4, 6)
        lbl_if.Size = Size(40, 20)

        self.cond_param = FilteredComboBox(all_elem_labels, 175)
        self.cond_param.combo.Location = Point(48, 4)

        self.cond_op = ComboBox()
        self.cond_op.Location = Point(228, 4)
        self.cond_op.Size = Size(130, 24)
        self.cond_op.DropDownStyle = ComboBoxStyle.DropDownList
        for op in OPERATORS:
            self.cond_op.Items.Add(op)
        self.cond_op.SelectedIndex = 0
        self.cond_op.SelectedIndexChanged += self._on_op_changed

        self.rb_cond_val = RadioButton()
        self.rb_cond_val.Text = u""
        self.rb_cond_val.Location = Point(364, 6)
        self.rb_cond_val.Size = Size(16, 20)
        self.rb_cond_val.Checked = True
        self.rb_cond_val.CheckedChanged += self._on_cond_rb_changed

        self.txt_cond_val = TextBox()
        self.txt_cond_val.Location = Point(382, 4)
        self.txt_cond_val.Size = Size(130, 24)

        self.rb_cond_par = RadioButton()
        self.rb_cond_par.Text = u""
        self.rb_cond_par.Location = Point(518, 6)
        self.rb_cond_par.Size = Size(16, 20)

        self.cond_param2 = FilteredComboBox(all_elem_labels, 130)
        self.cond_param2.combo.Location = Point(536, 4)
        self.cond_param2.combo.Enabled = False

        lbl_then = Label()
        lbl_then.Text = u"ТО"
        lbl_then.Location = Point(4, 40)
        lbl_then.Size = Size(40, 20)

        self.then_param = FilteredComboBox(tgt_labels_all, 175)
        self.then_param.combo.Location = Point(48, 38)

        lbl_arrow = Label()
        lbl_arrow.Text = u"←"
        lbl_arrow.Location = Point(228, 40)
        lbl_arrow.Size = Size(20, 20)

        self.rb_then_val = RadioButton()
        self.rb_then_val.Text = u""
        self.rb_then_val.Location = Point(252, 40)
        self.rb_then_val.Size = Size(16, 20)
        self.rb_then_val.Checked = True
        self.rb_then_val.CheckedChanged += self._on_then_rb_changed

        self.txt_then_val = TextBox()
        self.txt_then_val.Location = Point(270, 38)
        self.txt_then_val.Size = Size(175, 24)

        self.rb_then_par = RadioButton()
        self.rb_then_par.Text = u""
        self.rb_then_par.Location = Point(452, 40)
        self.rb_then_par.Size = Size(16, 20)

        self.then_param2 = FilteredComboBox(all_elem_labels, 175)
        self.then_param2.combo.Location = Point(470, 38)
        self.then_param2.combo.Enabled = False

        self.btn_del = Button()
        self.btn_del.Text = u"✕"
        self.btn_del.Location = Point(652, 22)
        self.btn_del.Size = Size(30, 24)
        self.btn_del.Tag = self

        for ctrl in [lbl_if, self.cond_param.combo, self.cond_op,
                     self.rb_cond_val, self.txt_cond_val,
                     self.rb_cond_par, self.cond_param2.combo,
                     lbl_then, self.then_param.combo, lbl_arrow,
                     self.rb_then_val, self.txt_then_val,
                     self.rb_then_par, self.then_param2.combo,
                     self.btn_del]:
            self.panel.Controls.Add(ctrl)

    def _on_op_changed(self, sender, e):
        op = OPERATORS[self.cond_op.SelectedIndex]
        no_value = op in [u"имеет значение", u"без значения"]
        self.rb_cond_val.Enabled       = not no_value
        self.txt_cond_val.Enabled      = not no_value
        self.rb_cond_par.Enabled       = not no_value
        self.cond_param2.combo.Enabled = not no_value

    def _on_cond_rb_changed(self, sender, e):
        self.txt_cond_val.Enabled      = self.rb_cond_val.Checked
        self.cond_param2.combo.Enabled = not self.rb_cond_val.Checked

    def _on_then_rb_changed(self, sender, e):
        self.txt_then_val.Enabled      = self.rb_then_val.Checked
        self.then_param2.combo.Enabled = not self.rb_then_val.Checked

    def get_condition(self):
        cond_p_text = self.cond_param.combo.Text.strip()
        cond_p_idx  = next((i for i, l in enumerate(all_elem_labels) if l == cond_p_text), 0)
        cond_param  = elem_src_params[cond_p_idx] if elem_src_params else None
        op = OPERATORS[self.cond_op.SelectedIndex]
        if self.rb_cond_val.Checked:
            cond_value = {'type': 'text', 'value': self.txt_cond_val.Text.strip()}
        else:
            cp2_text = self.cond_param2.combo.Text.strip()
            cp2_idx  = next((i for i, l in enumerate(all_elem_labels) if l == cp2_text), 0)
            cond_value = {'type': 'param', 'param': elem_src_params[cp2_idx] if elem_src_params else None}
        then_p_text = self.then_param.combo.Text.strip()
        then_p_idx  = next((i for i, l in enumerate(tgt_labels_all) if l == then_p_text), 0)
        then_param  = elem_tgt_params[then_p_idx] if elem_tgt_params else None
        if self.rb_then_val.Checked:
            then_value = {'type': 'text', 'value': self.txt_then_val.Text.strip()}
        else:
            tp2_text = self.then_param2.combo.Text.strip()
            tp2_idx  = next((i for i, l in enumerate(all_elem_labels) if l == tp2_text), 0)
            then_value = {'type': 'param', 'param': elem_src_params[tp2_idx] if elem_src_params else None}
        return {'cond_param': cond_param, 'operator': op,
                'cond_value': cond_value, 'then_param': then_param, 'then_value': then_value}


# ════════════════════════════════════════════════════════════════════════════
# Рядок пари для вкладки Збірки
# ════════════════════════════════════════════════════════════════════════════
ASM_DIRECTION_OPTIONS = [u"Збірка → Вкладення", u"Вкладення → Збірка"]
ASM_MULTI_OPTIONS     = [u"Кожен окремо", u"Всі через кому"]

class AssemblyPairRow(object):
    def __init__(self):
        self.panel = Panel()
        self.panel.Size = Size(726, 64)
        self.panel.BorderStyle = BorderStyle.FixedSingle

        self.combo_dir = ComboBox()
        self.combo_dir.Location = Point(4, 6)
        self.combo_dir.Size = Size(160, 24)
        self.combo_dir.DropDownStyle = ComboBoxStyle.DropDownList
        for opt in ASM_DIRECTION_OPTIONS:
            self.combo_dir.Items.Add(opt)
        self.combo_dir.SelectedIndex = 0
        self.combo_dir.SelectedIndexChanged += self._on_dir_changed

        lbl_src = Label()
        lbl_src.Text = u"Джерело:"
        lbl_src.Location = Point(170, 9)
        lbl_src.Size = Size(56, 18)

        self.src = FilteredComboBox(asm_src_labels, 220)
        self.src.combo.Location = Point(228, 6)

        lbl_arr = Label()
        lbl_arr.Text = u"→"
        lbl_arr.Location = Point(454, 10)
        lbl_arr.Size = Size(16, 18)

        lbl_tgt = Label()
        lbl_tgt.Text = u"Ціль:"
        lbl_tgt.Location = Point(474, 9)
        lbl_tgt.Size = Size(36, 18)

        self.tgt = FilteredComboBox(member_tgt_labels, 170)
        self.tgt.combo.Location = Point(512, 6)

        self.btn_del = Button()
        self.btn_del.Text = u"✕"
        self.btn_del.Location = Point(690, 6)
        self.btn_del.Size = Size(30, 24)
        self.btn_del.Tag = self

        lbl_multi = Label()
        lbl_multi.Text = u"Якщо один тип у кількох збірках:"
        lbl_multi.Location = Point(4, 38)
        lbl_multi.Size = Size(220, 18)
        lbl_multi.Font = Font(u"Segoe UI", 8)

        self.combo_multi = ComboBox()
        self.combo_multi.Location = Point(228, 36)
        self.combo_multi.Size = Size(160, 22)
        self.combo_multi.DropDownStyle = ComboBoxStyle.DropDownList
        for opt in ASM_MULTI_OPTIONS:
            self.combo_multi.Items.Add(opt)
        self.combo_multi.SelectedIndex = 1

        lbl_sep = Label()
        lbl_sep.Text = u"Роздільник:"
        lbl_sep.Location = Point(396, 38)
        lbl_sep.Size = Size(72, 18)
        lbl_sep.Font = Font(u"Segoe UI", 8)

        self.txt_sep = TextBox()
        self.txt_sep.Location = Point(470, 36)
        self.txt_sep.Size = Size(60, 22)
        self.txt_sep.Text = u", "
        self.txt_sep.Font = Font(u"Segoe UI", 8)

        self._lbl_multi = lbl_multi
        self._lbl_sep   = lbl_sep

        for ctrl in [self.combo_dir, lbl_src, self.src.combo, lbl_arr,
                     lbl_tgt, self.tgt.combo, self.btn_del,
                     lbl_multi, self.combo_multi, lbl_sep, self.txt_sep]:
            self.panel.Controls.Add(ctrl)

        self._update_for_direction()

    def _on_dir_changed(self, sender, e):
        self._update_for_direction()

    def _update_for_direction(self):
        is_asm_to_mbr = (self.combo_dir.SelectedIndex == 0)
        if is_asm_to_mbr:
            self.src.update_labels(asm_src_labels)
            self.tgt.update_labels(member_tgt_labels)
        else:
            self.src.update_labels(member_src_labels)
            self.tgt.update_labels(asm_tgt_labels)
        show_multi = is_asm_to_mbr
        self._lbl_multi.Visible  = show_multi
        self.combo_multi.Visible = show_multi
        self._lbl_sep.Visible    = show_multi
        self.txt_sep.Visible     = show_multi

    def get_config(self):
        is_asm_to_mbr = (self.combo_dir.SelectedIndex == 0)
        src_text = self.src.combo.Text.strip()
        tgt_text = self.tgt.combo.Text.strip()

        if is_asm_to_mbr:
            src_idx = next((i for i, l in enumerate(asm_src_labels)    if l == src_text), 0)
            tgt_idx = next((i for i, l in enumerate(member_tgt_labels) if l == tgt_text), 0)
            src_param = asm_all_src_params[src_idx] if asm_all_src_params else None
            tgt_param = member_tgt_params[tgt_idx]  if member_tgt_params  else None
        else:
            src_idx = next((i for i, l in enumerate(member_src_labels) if l == src_text), 0)
            tgt_idx = next((i for i, l in enumerate(asm_tgt_labels)    if l == tgt_text), 0)
            src_param = member_src_params[src_idx]  if member_src_params  else None
            tgt_param = asm_all_tgt_params[tgt_idx] if asm_all_tgt_params else None

        multi_all = (self.combo_multi.SelectedIndex == 1)
        separator = self.txt_sep.Text if self.txt_sep.Text else u", "

        return {
            'is_asm_to_mbr': is_asm_to_mbr,
            'src_param':     src_param,
            'tgt_param':     tgt_param,
            'multi_all':     multi_all,
            'separator':     separator,
        }


# ════════════════════════════════════════════════════════════════════════════
# КРОК 6: Шаблони для підсімейств
# ════════════════════════════════════════════════════════════════════════════
import System as _System
NESTED_TEMPLATES_PATH = os.path.join(
    _System.Environment.GetFolderPath(_System.Environment.SpecialFolder.ApplicationData),
    "pyRevit", "Extensions", "MyTools.extension", "nested_templates.json"
)

def load_nested_templates():
    try:
        import codecs
        if os.path.exists(NESTED_TEMPLATES_PATH):
            with codecs.open(NESTED_TEMPLATES_PATH, 'r', encoding='utf-8') as f:
                return json.loads(f.read())
    except Exception:
        pass
    return {}

def save_nested_templates(templates):
    try:
        import codecs
        folder = os.path.dirname(NESTED_TEMPLATES_PATH)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with codecs.open(NESTED_TEMPLATES_PATH, 'w', encoding='utf-8') as f:
            f.write(json.dumps(templates, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════════
# Рядок пари для вкладки Підсімейства
# ════════════════════════════════════════════════════════════════════════════
if selected_assemblies and not selected_instances:
    SOURCE_OPTIONS = [u"Збірка", u"Вкладення збірки"]
else:
    SOURCE_OPTIONS = [u"Хост-сімейство", u"Підсімейства"]

class NestedPairRow(object):
    def __init__(self):
        self.panel = Panel()
        self.panel.Size = Size(700, 36)
        self.panel.BorderStyle = getattr(BorderStyle, 'None')

        self.combo_src_el = ComboBox()
        self.combo_src_el.Location = Point(0, 6)
        self.combo_src_el.Size = Size(100, 24)
        self.combo_src_el.DropDownStyle = ComboBoxStyle.DropDownList
        for opt in SOURCE_OPTIONS:
            self.combo_src_el.Items.Add(opt)
        self.combo_src_el.SelectedIndex = 0
        self.combo_src_el.SelectedIndexChanged += self._on_src_el_changed

        self.src = FilteredComboBox(nested_src_labels_host, 190)
        self.src.combo.Location = Point(106, 6)

        lbl = Label()
        lbl.Text = u"→"
        lbl.Location = Point(302, 10)
        lbl.Size = Size(18, 20)

        self.combo_tgt_el = ComboBox()
        self.combo_tgt_el.Location = Point(324, 6)
        self.combo_tgt_el.Size = Size(100, 24)
        self.combo_tgt_el.DropDownStyle = ComboBoxStyle.DropDownList
        for opt in SOURCE_OPTIONS:
            self.combo_tgt_el.Items.Add(opt)
        self.combo_tgt_el.SelectedIndex = 1
        self.combo_tgt_el.SelectedIndexChanged += self._on_tgt_el_changed

        self.tgt = FilteredComboBox(nested_tgt_labels_nested, 190)
        self.tgt.combo.Location = Point(430, 6)

        self.btn_del = Button()
        self.btn_del.Text = u"✕"
        self.btn_del.Location = Point(628, 6)
        self.btn_del.Size = Size(36, 24)
        self.btn_del.Tag = self

        self.panel.Controls.Add(self.combo_src_el)
        self.panel.Controls.Add(self.src.combo)
        self.panel.Controls.Add(lbl)
        self.panel.Controls.Add(self.combo_tgt_el)
        self.panel.Controls.Add(self.tgt.combo)
        self.panel.Controls.Add(self.btn_del)

    def _on_src_el_changed(self, sender, e):
        if self.combo_src_el.SelectedIndex == 0:
            self.src.update_labels(nested_src_labels_host)
        else:
            self.src.update_labels(nested_src_labels_nested)

    def _on_tgt_el_changed(self, sender, e):
        if self.combo_tgt_el.SelectedIndex == 0:
            self.tgt.update_labels(nested_tgt_labels_host)
        else:
            self.tgt.update_labels(nested_tgt_labels_nested)

    def get_pair(self):
        src_is_host = self.combo_src_el.SelectedIndex == 0
        tgt_is_host = self.combo_tgt_el.SelectedIndex == 0
        src_params_used = elem_src_params if src_is_host else nested_params
        tgt_params_used = host_w_params   if tgt_is_host else nested_w_params
        src_text = self.src.combo.Text.strip()
        tgt_text = self.tgt.combo.Text.strip()
        src_idx  = next((i for i, p in enumerate(src_params_used)
                         if elem_tgt_label(p) == src_text or elem_src_label(p) == src_text), 0)
        tgt_idx  = next((i for i, p in enumerate(tgt_params_used)
                         if elem_tgt_label(p) == tgt_text), 0)
        src_param = src_params_used[src_idx] if src_params_used else None
        tgt_param = tgt_params_used[tgt_idx] if tgt_params_used else None
        return src_is_host, tgt_is_host, src_param, tgt_param

    def set_from_template(self, tpl_pair):
        src_is_host = tpl_pair.get('src_is_host', True)
        tgt_is_host = tpl_pair.get('tgt_is_host', False)
        self.combo_src_el.SelectedIndex = 0 if src_is_host else 1
        self.combo_tgt_el.SelectedIndex = 0 if tgt_is_host else 1
        self.src.combo.Text = tpl_pair.get('src_param', u'')
        self.tgt.combo.Text = tpl_pair.get('tgt_param', u'')


# ════════════════════════════════════════════════════════════════════════════
# КРОК 7: Головна форма
# ════════════════════════════════════════════════════════════════════════════
class MainForm(Form):
    def __init__(self):
        super(MainForm, self).__init__()

        BG = Color.FromArgb(245, 245, 248)

        self.Text            = u"Параметри"
        self.Width           = 800
        self.StartPosition   = FormStartPosition.CenterScreen
        self.FormBorderStyle = WinForms.FormBorderStyle.FixedDialog
        self.MaximizeBox     = False
        self.MinimizeBox     = False
        self.BackColor       = BG

        # Інфо-рядок про виділення
        if SELECTION_INFO:
            lbl_sel = Label()
            lbl_sel.Text      = SELECTION_INFO
            lbl_sel.Font      = Font(u"Segoe UI", 8)
            lbl_sel.ForeColor = Color.FromArgb(0, 112, 200)
            lbl_sel.SetBounds(12, 4, 760, 16)
            lbl_sel.BackColor = BG
            self.Controls.Add(lbl_sel)
            tabs_top = 22
        else:
            tabs_top = 10

        self.tabs = TabControl()
        self.tabs.SetBounds(10, tabs_top, 768, 440)
        self.tabs.Font = Font(u"Segoe UI", 9)

        self.tab_copy      = TabPage(); self.tab_copy.Text      = u"Копіювати"
        self.tab_nested    = TabPage(); self.tab_nested.Text    = u"Підсімейства"
        self.tab_cond      = TabPage(); self.tab_cond.Text      = u"Умови"
        self.tab_replace   = TabPage(); self.tab_replace.Text   = u"Заміна тексту"
        self.tab_assembly  = TabPage(); self.tab_assembly.Text  = u"Збірки"

        self._build_copy_tab()
        self._build_nested_tab()
        self._build_cond_tab()
        self._build_replace_tab()
        self._build_assembly_tab()

        self.tabs.TabPages.Add(self.tab_copy)
        self.tabs.TabPages.Add(self.tab_nested)
        self.tabs.TabPages.Add(self.tab_cond)
        self.tabs.TabPages.Add(self.tab_replace)
        self.tabs.TabPages.Add(self.tab_assembly)
        self.Controls.Add(self.tabs)

        btn_y = tabs_top + 450

        self.chk_replace = CheckBox()
        self.chk_replace.Text      = u"Замінювати існуючі значення"
        self.chk_replace.Font      = Font(u"Segoe UI", 9)
        self.chk_replace.ForeColor = Color.FromArgb(160, 70, 0)
        self.chk_replace.SetBounds(12, btn_y, 340, 20)
        self.chk_replace.BackColor = BG
        self.chk_replace.Checked   = False
        self.Controls.Add(self.chk_replace)

        btn_ok = Button()
        btn_ok.Text      = u"Запустити"
        btn_ok.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        btn_ok.SetBounds(12, btn_y + 28, 220, 32)
        btn_ok.BackColor = Color.FromArgb(0, 112, 200)
        btn_ok.ForeColor = Color.White
        btn_ok.FlatStyle = WinForms.FlatStyle.Flat
        btn_ok.FlatAppearance.BorderSize = 0
        btn_ok.DialogResult = DialogResult.OK
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text         = u"Скасувати"
        btn_cancel.Font         = Font(u"Segoe UI", 9)
        btn_cancel.SetBounds(634, btn_y + 28, 136, 32)
        btn_cancel.FlatStyle    = WinForms.FlatStyle.Flat
        btn_cancel.DialogResult = DialogResult.Cancel
        self.Controls.Add(btn_cancel)

        self.AcceptButton = btn_ok
        self.CancelButton = btn_cancel
        self.Height = btn_y + 100

    # ── Вкладка Копіювати ─────────────────────────────────────────────────
    def _build_copy_tab(self):
        self.copy_rows = []

        lbl_s = Label()
        lbl_s.Text      = u"Джерело"
        lbl_s.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_s.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_s.SetBounds(8, 10, 295, 18)

        lbl_t = Label()
        lbl_t.Text      = u"Ціль"
        lbl_t.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_t.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_t.SetBounds(334, 10, 295, 18)

        self.copy_flow = FlowLayoutPanel()
        self.copy_flow.SetBounds(8, 32, 740, 310)
        self.copy_flow.FlowDirection = FlowDirection.TopDown
        self.copy_flow.WrapContents  = False
        self.copy_flow.AutoScroll    = True

        self.btn_add_copy = Button()
        self.btn_add_copy.Text      = u"+ Додати пару"
        self.btn_add_copy.Font      = Font(u"Segoe UI", 9)
        self.btn_add_copy.SetBounds(8, 348, 120, 28)
        self.btn_add_copy.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_add_copy.Click    += self._on_add_copy

        for ctrl in [lbl_s, lbl_t, self.copy_flow, self.btn_add_copy]:
            self.tab_copy.Controls.Add(ctrl)
        self._add_copy_row()

    def _add_copy_row(self):
        if len(self.copy_rows) >= MAX_PAIRS:
            return
        row = CopyPairRow()
        row.btn_del.Click += self._on_del_copy
        self.copy_rows.append(row)
        self.copy_flow.Controls.Add(row.panel)
        self.btn_add_copy.Enabled = len(self.copy_rows) < MAX_PAIRS

    def _on_add_copy(self, sender, e):
        self._add_copy_row()

    def _on_del_copy(self, sender, e):
        row = sender.Tag
        if len(self.copy_rows) <= 1:
            return
        self.copy_rows.remove(row)
        self.copy_flow.Controls.Remove(row.panel)
        self.btn_add_copy.Enabled = len(self.copy_rows) < MAX_PAIRS

    # ── Вкладка Підсімейства ──────────────────────────────────────────────
    def _build_nested_tab(self):
        self.nested_rows = []
        self._nested_templates = load_nested_templates()

        asm_count   = len(selected_assemblies)
        asm_members = sum(len(get_nested(a)) for a in selected_assemblies)
        host_count  = len(_all_hosts_map)
        fam_nested  = len(all_nested) - asm_members
        sys_count   = len(selected_generic)
        # Скільки знайдено через SuperComponent
        auto_found  = len(_auto_hosts)

        info_parts = []
        if asm_count > 0:
            info_parts.append(u"Збірок: {} ({} вкладень)".format(asm_count, asm_members))
        if host_count > 0:
            extra = u" +{} через SuperComponent".format(auto_found) if auto_found else u""
            info_parts.append(u"Хостів: {}{} ({} вкладених)".format(host_count, extra, fam_nested))
        if sys_count > 0:
            info_parts.append(u"Системних: {}".format(sys_count))
        info_text = u"   |   ".join(info_parts) if info_parts else u"Нічого не виділено"

        lbl_info = Label()
        lbl_info.Text      = info_text
        lbl_info.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_info.ForeColor = Color.FromArgb(0, 112, 200)
        lbl_info.SetBounds(8, 10, 740, 18)

        self.nested_combo_tpl = ComboBox()
        self.nested_combo_tpl.Font          = Font(u"Segoe UI", 9)
        self.nested_combo_tpl.SetBounds(8, 34, 200, 24)
        self.nested_combo_tpl.DropDownStyle = ComboBoxStyle.DropDownList
        self._fill_nested_templates()
        self.nested_combo_tpl.SelectedIndexChanged += self._on_nested_tpl_changed

        btn_load_tpl = Button()
        btn_load_tpl.Text      = u"Завантажити"
        btn_load_tpl.Font      = Font(u"Segoe UI", 9)
        btn_load_tpl.SetBounds(214, 33, 90, 26)
        btn_load_tpl.FlatStyle = WinForms.FlatStyle.Flat
        btn_load_tpl.Click    += self._on_nested_tpl_changed

        btn_save_tpl = Button()
        btn_save_tpl.Text      = u"Зберегти"
        btn_save_tpl.Font      = Font(u"Segoe UI", 9)
        btn_save_tpl.SetBounds(310, 33, 80, 26)
        btn_save_tpl.FlatStyle = WinForms.FlatStyle.Flat
        btn_save_tpl.Click    += self._on_save_nested_tpl

        btn_del_tpl = Button()
        btn_del_tpl.Text       = u"Видалити"
        btn_del_tpl.Font       = Font(u"Segoe UI", 9)
        btn_del_tpl.ForeColor  = Color.FromArgb(180, 40, 40)
        btn_del_tpl.SetBounds(396, 33, 74, 26)
        btn_del_tpl.FlatStyle  = WinForms.FlatStyle.Flat
        btn_del_tpl.Click     += self._on_del_nested_tpl

        self.nested_txt_tpl_name = TextBox()
        self.nested_txt_tpl_name.Font         = Font(u"Segoe UI", 9)
        self.nested_txt_tpl_name.SetBounds(476, 34, 270, 24)
        self.nested_txt_tpl_name.PlaceholderText = u"Назва шаблону"

        lbl_src_h = Label()
        lbl_src_h.Text      = u"Джерело [хост/підсім]  →  Параметр"
        lbl_src_h.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_src_h.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_src_h.SetBounds(8, 66, 310, 18)

        lbl_tgt_h = Label()
        lbl_tgt_h.Text      = u"Ціль [хост/підсім]  →  Параметр"
        lbl_tgt_h.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_tgt_h.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_tgt_h.SetBounds(330, 66, 310, 18)

        self.nested_flow = FlowLayoutPanel()
        self.nested_flow.SetBounds(8, 88, 740, 240)
        self.nested_flow.FlowDirection = FlowDirection.TopDown
        self.nested_flow.WrapContents  = False
        self.nested_flow.AutoScroll    = True

        self.btn_add_nested = Button()
        self.btn_add_nested.Text      = u"+ Додати пару"
        self.btn_add_nested.Font      = Font(u"Segoe UI", 9)
        self.btn_add_nested.SetBounds(8, 334, 120, 28)
        self.btn_add_nested.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_add_nested.Click    += self._on_add_nested

        for ctrl in [lbl_info, self.nested_combo_tpl, btn_load_tpl, btn_save_tpl,
                     btn_del_tpl, self.nested_txt_tpl_name,
                     lbl_src_h, lbl_tgt_h, self.nested_flow, self.btn_add_nested]:
            self.tab_nested.Controls.Add(ctrl)

        self._add_nested_row()

    def _fill_nested_templates(self):
        self.nested_combo_tpl.Items.Clear()
        self.nested_combo_tpl.Items.Add(u"— без шаблону —")
        for name in sorted(self._nested_templates.keys()):
            self.nested_combo_tpl.Items.Add(name)
        self.nested_combo_tpl.SelectedIndex = 0

    def _on_nested_tpl_changed(self, sender, e):
        idx  = self.nested_combo_tpl.SelectedIndex
        name = self.nested_combo_tpl.Items[idx] if idx >= 0 and idx < self.nested_combo_tpl.Items.Count else u""
        if not name:
            return
        tpl = self._nested_templates.get(name, {})
        if not tpl:
            return
        pairs = tpl.get('pairs', [])
        for row in list(self.nested_rows):
            self.nested_flow.Controls.Remove(row.panel)
        self.nested_rows = []
        for pair_data in pairs:
            self._add_nested_row()
            self.nested_rows[-1].set_from_template(pair_data)
        self.nested_txt_tpl_name.Text = name

    def _on_save_nested_tpl(self, sender, e):
        name = self.nested_txt_tpl_name.Text.strip()
        if not name:
            MessageBox.Show(u"Введіть назву шаблону.", u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return
        pairs = []
        for row in self.nested_rows:
            src_is_host, tgt_is_host, src_p, tgt_p = row.get_pair()
            pairs.append({
                'src_is_host': src_is_host,
                'tgt_is_host': tgt_is_host,
                'src_param':   row.src.combo.Text.strip(),
                'tgt_param':   row.tgt.combo.Text.strip(),
            })
        self._nested_templates[name] = {'pairs': pairs}
        if save_nested_templates(self._nested_templates):
            self._fill_nested_templates()
            for i in range(self.nested_combo_tpl.Items.Count):
                if self.nested_combo_tpl.Items[i] == name:
                    self.nested_combo_tpl.SelectedIndex = i
                    break
            MessageBox.Show(u"Шаблон '{}' збережено.".format(name), u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
        else:
            MessageBox.Show(u"Помилка збереження.", u"Шаблон",
                            MessageBoxButtons.OK, MessageBoxIcon.Error)

    def _on_del_nested_tpl(self, sender, e):
        idx = self.nested_combo_tpl.SelectedIndex
        if idx <= 0:
            return
        name = self.nested_combo_tpl.Items[idx]
        res  = MessageBox.Show(u"Видалити шаблон '{}'?".format(name), u"Шаблон",
                               MessageBoxButtons.YesNo, MessageBoxIcon.Question)
        if res == DialogResult.Yes:
            del self._nested_templates[name]
            save_nested_templates(self._nested_templates)
            self._fill_nested_templates()

    def _add_nested_row(self):
        if len(self.nested_rows) >= MAX_PAIRS:
            return
        row = NestedPairRow()
        row.btn_del.Click += self._on_del_nested
        self.nested_rows.append(row)
        self.nested_flow.Controls.Add(row.panel)
        self.btn_add_nested.Enabled = len(self.nested_rows) < MAX_PAIRS

    def _on_add_nested(self, sender, e):
        self._add_nested_row()

    def _on_del_nested(self, sender, e):
        row = sender.Tag
        if len(self.nested_rows) <= 1:
            return
        self.nested_rows.remove(row)
        self.nested_flow.Controls.Remove(row.panel)
        self.btn_add_nested.Enabled = len(self.nested_rows) < MAX_PAIRS

    # ── Вкладка Умови ─────────────────────────────────────────────────────
    def _build_cond_tab(self):
        self.cond_rows = []

        lbl_hint = Label()
        lbl_hint.Text      = u"Перемикачі праворуч від оператора і стрілки: вручну  /  параметр"
        lbl_hint.Font      = Font(u"Segoe UI", 8)
        lbl_hint.ForeColor = Color.FromArgb(100, 100, 120)
        lbl_hint.SetBounds(8, 8, 740, 16)

        self.cond_flow = FlowLayoutPanel()
        self.cond_flow.SetBounds(8, 28, 740, 310)
        self.cond_flow.FlowDirection = FlowDirection.TopDown
        self.cond_flow.WrapContents  = False
        self.cond_flow.AutoScroll    = True

        self.btn_add_cond = Button()
        self.btn_add_cond.Text      = u"+ Додати умову"
        self.btn_add_cond.Font      = Font(u"Segoe UI", 9)
        self.btn_add_cond.SetBounds(8, 344, 130, 28)
        self.btn_add_cond.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_add_cond.Click    += self._on_add_cond

        for ctrl in [lbl_hint, self.cond_flow, self.btn_add_cond]:
            self.tab_cond.Controls.Add(ctrl)
        self._add_cond_row()

    def _add_cond_row(self):
        if len(self.cond_rows) >= MAX_PAIRS:
            return
        row = ConditionRow()
        row.btn_del.Click += self._on_del_cond
        self.cond_rows.append(row)
        self.cond_flow.Controls.Add(row.panel)
        self.btn_add_cond.Enabled = len(self.cond_rows) < MAX_PAIRS

    def _on_add_cond(self, sender, e):
        self._add_cond_row()

    def _on_del_cond(self, sender, e):
        row = sender.Tag
        if len(self.cond_rows) <= 1:
            return
        self.cond_rows.remove(row)
        self.cond_flow.Controls.Remove(row.panel)
        self.btn_add_cond.Enabled = len(self.cond_rows) < MAX_PAIRS

    # ── Вкладка Заміна тексту ─────────────────────────────────────────────
    def _build_replace_tab(self):
        import datetime

        lbl_p = Label()
        lbl_p.Text      = u"Параметр для пошуку і заміни:"
        lbl_p.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_p.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_p.SetBounds(8, 12, 740, 18)

        self.replace_param = FilteredComboBox(tgt_labels_all, 740)
        self.replace_param.combo.SetBounds(8, 34, 740, 24)

        lbl_new = Label()
        lbl_new.Text      = u"Замінити знайдену дату на:"
        lbl_new.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_new.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_new.SetBounds(8, 72, 240, 18)

        self.txt_new_date = TextBox()
        self.txt_new_date.Font = Font(u"Segoe UI", 9)
        self.txt_new_date.SetBounds(252, 70, 160, 24)
        self.txt_new_date.Text = datetime.datetime.now().strftime('%d.%m.%Y')

        btn_scan = Button()
        btn_scan.Text      = u"Знайти дати у виділених елементах"
        btn_scan.Font      = Font(u"Segoe UI", 9)
        btn_scan.SetBounds(8, 106, 260, 28)
        btn_scan.FlatStyle = WinForms.FlatStyle.Flat
        btn_scan.Click    += self._on_scan_dates

        lbl_found = Label()
        lbl_found.Text      = u"Знайдені дати (обери які замінити):"
        lbl_found.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_found.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_found.SetBounds(8, 146, 400, 18)

        self.dates_list = ListBox()
        self.dates_list.Font          = Font(u"Segoe UI", 9)
        self.dates_list.SetBounds(8, 168, 740, 180)
        self.dates_list.SelectionMode = SelectionMode.MultiExtended

        for ctrl in [lbl_p, self.replace_param.combo, lbl_new,
                     self.txt_new_date, btn_scan, lbl_found, self.dates_list]:
            self.tab_replace.Controls.Add(ctrl)

    def _on_scan_dates(self, sender, e):
        self.dates_list.Items.Clear()

        param_text = self.replace_param.combo.Text.strip()
        if not param_text:
            MessageBox.Show(u"Оберіть параметр.", u"Заміна тексту",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning)
            return

        param_name   = param_text.split(u' [')[0] if u' [' in param_text else param_text
        date_pattern = re.compile(r'\d{2}\.\d{2}\.\d{4}')
        found_dates  = set()

        # Сканує всі виділені елементи (включно з системними)
        for el in all_selected:
            for target in [el, doc.GetElement(el.GetTypeId()) if hasattr(el, 'GetTypeId') else None]:
                if not target:
                    continue
                try:
                    p = target.LookupParameter(param_name)
                    if p and p.StorageType == StorageType.String:
                        val = p.AsString()
                        if val:
                            for date in date_pattern.findall(val):
                                found_dates.add(date)
                except Exception:
                    pass

        if not found_dates:
            MessageBox.Show(u"Дат у форматі DD.MM.YYYY не знайдено.", u"Заміна тексту",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)
            return

        for date in sorted(found_dates):
            self.dates_list.Items.Add(date)

        for i in range(self.dates_list.Items.Count):
            self.dates_list.SetSelected(i, True)

    # ── Вкладка Збірки ────────────────────────────────────────────────────
    def _build_assembly_tab(self):
        self.assembly_rows = []

        asm_count = len(_all_assemblies_for_tab)
        mbr_count = len(_all_members)

        if asm_count == 0:
            info_color = Color.FromArgb(180, 50, 50)
            info_text  = u"⚠  Не знайдено збірок у виділених елементах"
        else:
            info_color = Color.FromArgb(0, 112, 200)
            info_text  = u"Збірок: {}   |   Вкладень: {}".format(asm_count, mbr_count)

        lbl_info = Label()
        lbl_info.Text      = info_text
        lbl_info.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_info.ForeColor = info_color
        lbl_info.SetBounds(8, 8, 740, 18)

        lbl_hint = Label()
        lbl_hint.Text = (
            u"Збірка → Вкладення: зчитує параметр типу/екземпляра збірки і записує у вкладення.   "
            u"Вкладення → Збірка: зчитує з вкладень і записує в параметр збірки."
        )
        lbl_hint.Font      = Font(u"Segoe UI", 8)
        lbl_hint.ForeColor = Color.FromArgb(100, 100, 120)
        lbl_hint.SetBounds(8, 28, 740, 28)

        lbl_h_dir = Label()
        lbl_h_dir.Text      = u"Напрямок"
        lbl_h_dir.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_h_dir.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_h_dir.SetBounds(8, 60, 160, 18)

        lbl_h_src = Label()
        lbl_h_src.Text      = u"Джерело (параметр)"
        lbl_h_src.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_h_src.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_h_src.SetBounds(170, 60, 230, 18)

        lbl_h_tgt = Label()
        lbl_h_tgt.Text      = u"Ціль (параметр)"
        lbl_h_tgt.Font      = Font(u"Segoe UI", 9, FontStyle.Bold)
        lbl_h_tgt.ForeColor = Color.FromArgb(40, 40, 40)
        lbl_h_tgt.SetBounds(472, 60, 200, 18)

        self.asm_flow = FlowLayoutPanel()
        self.asm_flow.SetBounds(8, 82, 750, 280)
        self.asm_flow.FlowDirection = FlowDirection.TopDown
        self.asm_flow.WrapContents  = False
        self.asm_flow.AutoScroll    = True

        self.btn_add_asm = Button()
        self.btn_add_asm.Text      = u"+ Додати пару"
        self.btn_add_asm.Font      = Font(u"Segoe UI", 9)
        self.btn_add_asm.SetBounds(8, 368, 120, 28)
        self.btn_add_asm.FlatStyle = WinForms.FlatStyle.Flat
        self.btn_add_asm.Click    += self._on_add_asm
        self.btn_add_asm.Enabled   = asm_count > 0

        for ctrl in [lbl_info, lbl_hint, lbl_h_dir, lbl_h_src, lbl_h_tgt,
                     self.asm_flow, self.btn_add_asm]:
            self.tab_assembly.Controls.Add(ctrl)

        if asm_count > 0:
            self._add_asm_row()

    def _add_asm_row(self):
        if len(self.assembly_rows) >= MAX_PAIRS:
            return
        row = AssemblyPairRow()
        row.btn_del.Click += self._on_del_asm
        self.assembly_rows.append(row)
        self.asm_flow.Controls.Add(row.panel)
        self.btn_add_asm.Enabled = len(self.assembly_rows) < MAX_PAIRS

    def _on_add_asm(self, sender, e):
        self._add_asm_row()

    def _on_del_asm(self, sender, e):
        row = sender.Tag
        if len(self.assembly_rows) <= 1:
            return
        self.assembly_rows.remove(row)
        self.asm_flow.Controls.Remove(row.panel)
        self.btn_add_asm.Enabled = len(self.assembly_rows) < MAX_PAIRS

    # ── Геттери ───────────────────────────────────────────────────────────
    def get_copy_pairs(self):
        return [row.get_pair() for row in self.copy_rows]

    def get_nested_pairs(self):
        pairs = []
        for row in self.nested_rows:
            src_is_host, tgt_is_host, src_param, tgt_param = row.get_pair()
            if src_param and tgt_param:
                pairs.append((src_is_host, tgt_is_host, src_param, tgt_param))
        return pairs

    def get_conditions(self):
        return [row.get_condition() for row in self.cond_rows]

    def get_assembly_configs(self):
        configs = []
        for row in self.assembly_rows:
            cfg = row.get_config()
            if cfg['src_param'] and cfg['tgt_param']:
                configs.append(cfg)
        return configs

    def get_replace_config(self):
        param_text  = self.replace_param.combo.Text.strip()
        param_name  = param_text.split(u' [')[0] if u' [' in param_text else param_text
        param_level = 'instance'
        for p in elem_tgt_params:
            if p['name'] == param_name:
                param_level = p['level']
                break

        dates_to_replace = []
        for i in range(self.dates_list.Items.Count):
            if self.dates_list.GetSelected(i):
                dates_to_replace.append(self.dates_list.Items[i])

        return {
            'param_name':       param_name,
            'param_level':      param_level,
            'dates_to_replace': dates_to_replace,
            'new_date':         self.txt_new_date.Text.strip(),
        }


# ════════════════════════════════════════════════════════════════════════════
# КРОК 8: Показуємо форму
# ════════════════════════════════════════════════════════════════════════════
main_form = MainForm()
if main_form.ShowDialog() != DialogResult.OK:
    script.exit()

active_tab       = main_form.tabs.SelectedIndex
replace_existing = main_form.chk_replace.Checked


# ════════════════════════════════════════════════════════════════════════════
# КРОК 9: Функція перевірки умови
# ════════════════════════════════════════════════════════════════════════════
def check_condition(element, cond):
    op     = cond['operator']
    cond_p = cond['cond_param']
    cond_v = cond['cond_value']
    inst_val = get_param_val(element, cond_p) if cond_p else None

    if op == u"имеет значение":
        return inst_val is not None and inst_val != u""
    if op == u"без значения":
        return inst_val is None or inst_val == u""

    if cond_v['type'] == 'text':
        right = cond_v['value']
    else:
        right = get_param_val(element, cond_v['param']) if cond_v.get('param') else None

    if inst_val is None or right is None:
        return False

    try:
        l_num = float(inst_val.replace(',', '.'))
        r_num = float(right.replace(',', '.'))
        if op == u"равно":          return l_num == r_num
        if op == u"не равно":       return l_num != r_num
        if op == u"выше":           return l_num > r_num
        if op == u"ровно или выше": return l_num >= r_num
        if op == u"ниже":           return l_num < r_num
        if op == u"ровно или ниже": return l_num <= r_num
    except Exception:
        if op == u"равно":          return inst_val == right
        if op == u"не равно":       return inst_val != right
        if op == u"выше":           return inst_val > right
        if op == u"ровно или выше": return inst_val >= right
        if op == u"ниже":           return inst_val < right
        if op == u"ровно или ниже": return inst_val <= right
    return False


# ════════════════════════════════════════════════════════════════════════════
# КРОК 10: Виконання
# ════════════════════════════════════════════════════════════════════════════
success_count   = 0
skipped_ids     = []
already_ids     = []
no_room_ids     = []
no_nested_ids   = []
processed_types = set()

tx = Transaction(doc, u"Параметри")
tx.Start()

# ── Вкладка 0: Копіювати ─────────────────────────────────────────────
if active_tab == 0:
    pairs = main_form.get_copy_pairs()
    # Обробляємо ВСІ елементи (FamilyInstance + AssemblyInstance + системні)
    for el in all_selected:
        for src_param, tgt_param in pairs:
            # Параметр приміщення — тільки для FamilyInstance
            if src_param.get('source') == 'room':
                if is_system_element(el):
                    if el.Id not in no_room_ids:
                        no_room_ids.append(el.Id)
                    continue
                if not get_room(el):
                    if el.Id not in no_room_ids:
                        no_room_ids.append(el.Id)
                    continue

            src_value = get_value(el, src_param)
            if not src_value:
                if el.Id not in skipped_ids:
                    skipped_ids.append(el.Id)
                continue

            # Дедублікація запису в тип
            try:
                type_id = el.GetTypeId()
            except Exception:
                type_id = None
            pair_key = (type_id, tgt_param['name'], tgt_param['level'])
            is_type_level = tgt_param['level'] in ('type', 'sys_type')
            if is_type_level and pair_key in processed_types:
                success_count += 1
                continue

            current = get_value(el, tgt_param)
            if current and not replace_existing:
                if el.Id not in already_ids:
                    already_ids.append(el.Id)
                continue

            if set_value(el, tgt_param, src_value):
                success_count += 1
                if is_type_level:
                    processed_types.add(pair_key)
            else:
                if el.Id not in skipped_ids:
                    skipped_ids.append(el.Id)

# ── Вкладка 1: Підсімейства ──────────────────────────────────────────
elif active_tab == 1:
    nested_pairs = main_form.get_nested_pairs()
    if not nested_pairs:
        forms.alert(u"Не вказано жодної пари параметрів.", title=u"Підсімейства", warn_icon=True)
        tx.RollBack()
        script.exit()
    else:
        # Хост-елементи: FamilyInstance + AssemblyInstance + системні
        _all_hosts = host_elements + selected_generic
        for host in _all_hosts:
            nested = get_nested(host)
            for src_is_host, tgt_is_host, src_param, tgt_param in nested_pairs:
                if src_is_host and tgt_is_host:
                    pairs_el = [(host, host)]
                elif src_is_host and not tgt_is_host:
                    if not nested:
                        if host.Id not in no_nested_ids:
                            no_nested_ids.append(host.Id)
                        continue
                    pairs_el = [(host, n) for n in nested]
                elif not src_is_host and tgt_is_host:
                    if not nested:
                        if host.Id not in no_nested_ids:
                            no_nested_ids.append(host.Id)
                        continue
                    pairs_el = [(n, host) for n in nested]
                else:
                    if not nested:
                        if host.Id not in no_nested_ids:
                            no_nested_ids.append(host.Id)
                        continue
                    pairs_el = [(n, n) for n in nested]

                for src_el, tgt_el in pairs_el:
                    value = get_value(src_el, src_param)
                    if not value:
                        if src_el.Id not in skipped_ids:
                            skipped_ids.append(src_el.Id)
                        continue
                    try:
                        type_id = tgt_el.GetTypeId()
                    except Exception:
                        type_id = None
                    pair_key = (type_id, tgt_param['name'], tgt_param['level'])
                    is_type_level = tgt_param['level'] in ('type', 'sys_type')
                    if is_type_level and pair_key in processed_types:
                        success_count += 1
                        continue
                    current = get_param_val(tgt_el, tgt_param)
                    if current and not replace_existing:
                        if tgt_el.Id not in already_ids:
                            already_ids.append(tgt_el.Id)
                        continue
                    if set_value(tgt_el, tgt_param, value):
                        success_count += 1
                        if is_type_level:
                            processed_types.add(pair_key)
                    else:
                        if tgt_el.Id not in skipped_ids:
                            skipped_ids.append(tgt_el.Id)

# ── Вкладка 2: Умови ─────────────────────────────────────────────────
elif active_tab == 2:
    conditions = main_form.get_conditions()
    # Обробляємо ВСІ елементи (включно з системними)
    for el in all_selected:
        el_failed = False
        for cond in conditions:
            if not cond['cond_param'] or not cond['then_param']:
                continue
            if not check_condition(el, cond):
                el_failed = True
                continue
            then_v = cond['then_value']
            write_val = (then_v['value'] if then_v['type'] == 'text'
                         else get_param_val(el, then_v['param']) if then_v.get('param') else None)
            if not write_val:
                el_failed = True
                continue
            then_p = cond['then_param']
            try:
                type_id = el.GetTypeId()
            except Exception:
                type_id = None
            pair_key = (type_id, then_p['name'], then_p['level'])
            is_type_level = then_p['level'] in ('type', 'sys_type')
            if is_type_level and pair_key in processed_types:
                success_count += 1
                continue
            current = get_param_val(el, then_p)
            if current and not replace_existing:
                if el.Id not in already_ids:
                    already_ids.append(el.Id)
                continue
            if set_value(el, then_p, write_val):
                success_count += 1
                if is_type_level:
                    processed_types.add(pair_key)
            else:
                el_failed = True
        if el_failed and el.Id not in skipped_ids:
            skipped_ids.append(el.Id)

# ── Вкладка 3: Заміна тексту ─────────────────────────────────────────
elif active_tab == 3:
    cfg         = main_form.get_replace_config()
    param_name  = cfg['param_name']
    param_level = cfg['param_level']
    new_date    = cfg['new_date']
    old_dates   = cfg['dates_to_replace']

    if not param_name:
        forms.alert(u"Оберіть параметр.", title=u"Заміна тексту", warn_icon=True)
        tx.RollBack()
        script.exit()
    elif not new_date:
        forms.alert(u"Введіть нову дату.", title=u"Заміна тексту", warn_icon=True)
        tx.RollBack()
        script.exit()
    elif not old_dates:
        forms.alert(u"Оберіть хоча б одну дату для заміни.", title=u"Заміна тексту", warn_icon=True)
        tx.RollBack()
        script.exit()
    else:
        processed_type_ids = set()
        is_type_level = param_level in ('type', 'sys_type')
        # Обробляємо ВСІ елементи
        for el in all_selected:
            if is_type_level:
                try:
                    type_id = el.GetTypeId()
                except Exception:
                    type_id = None
                if type_id and type_id in processed_type_ids:
                    continue
                target_el = doc.GetElement(type_id) if type_id else None
            else:
                target_el = el
                type_id   = None

            if not target_el:
                continue

            p = target_el.LookupParameter(param_name)
            if not p or p.IsReadOnly or p.StorageType != StorageType.String:
                skipped_ids.append(el.Id)
                continue

            val = p.AsString()
            if not val:
                skipped_ids.append(el.Id)
                continue

            new_val = val
            for old_date in old_dates:
                new_val = new_val.replace(old_date, new_date)

            if new_val != val:
                p.Set(new_val)
                success_count += 1
                if is_type_level and type_id:
                    processed_type_ids.add(type_id)
            else:
                skipped_ids.append(el.Id)

# ── Вкладка 4: Збірки ────────────────────────────────────────────────
elif active_tab == 4:
    asm_configs = main_form.get_assembly_configs()
    if not asm_configs:
        forms.alert(u"Не вказано жодної пари параметрів.", title=u"Збірки", warn_icon=True)
        tx.RollBack()
        script.exit()
    elif not _all_assemblies_for_tab:
        forms.alert(u"Не знайдено збірок серед виділених елементів.", title=u"Збірки", warn_icon=True)
        tx.RollBack()
        script.exit()
    else:
        for cfg in asm_configs:
            is_asm_to_mbr = cfg['is_asm_to_mbr']
            src_param     = cfg['src_param']
            tgt_param     = cfg['tgt_param']
            multi_all     = cfg['multi_all']
            separator     = cfg['separator']

            if is_asm_to_mbr:
                if multi_all:
                    from collections import defaultdict
                    member_type_to_values  = defaultdict(set)
                    member_type_to_members = defaultdict(list)

                    for asm in _all_assemblies_for_tab:
                        asm_val = get_assembly_param_value(asm, src_param)
                        if not asm_val:
                            continue
                        members = get_nested(asm)
                        for mbr in members:
                            try:
                                fam_type_id = mbr.GetTypeId()
                                member_type_to_values[fam_type_id].add(asm_val)
                                member_type_to_members[fam_type_id].append(mbr)
                            except Exception:
                                pass

                    for fam_type_id, values in member_type_to_values.items():
                        combined = separator.join(sorted(values))
                        for mbr in member_type_to_members[fam_type_id]:
                            current = get_member_param_value(mbr, tgt_param)
                            if current and not replace_existing:
                                if mbr.Id not in already_ids:
                                    already_ids.append(mbr.Id)
                                continue
                            if set_member_param_value(mbr, tgt_param, combined):
                                success_count += 1
                            else:
                                if mbr.Id not in skipped_ids:
                                    skipped_ids.append(mbr.Id)
                else:
                    for asm in _all_assemblies_for_tab:
                        asm_val = get_assembly_param_value(asm, src_param)
                        if not asm_val:
                            skipped_ids.append(asm.Id)
                            continue
                        members = get_nested(asm)
                        if not members:
                            skipped_ids.append(asm.Id)
                            continue
                        for mbr in members:
                            current = get_member_param_value(mbr, tgt_param)
                            if current and not replace_existing:
                                if mbr.Id not in already_ids:
                                    already_ids.append(mbr.Id)
                                continue
                            if set_member_param_value(mbr, tgt_param, asm_val):
                                success_count += 1
                            else:
                                if mbr.Id not in skipped_ids:
                                    skipped_ids.append(mbr.Id)
            else:
                for asm in _all_assemblies_for_tab:
                    members = get_nested(asm)
                    if not members:
                        skipped_ids.append(asm.Id)
                        continue

                    values = set()
                    for mbr in members:
                        v = get_member_param_value(mbr, src_param)
                        if v:
                            values.add(v)

                    if not values:
                        skipped_ids.append(asm.Id)
                        continue

                    combined = separator.join(sorted(values)) if len(values) > 1 else next(iter(values))

                    current = get_assembly_param_value(asm, tgt_param)
                    if current and not replace_existing:
                        if asm.Id not in already_ids:
                            already_ids.append(asm.Id)
                        continue

                    if set_assembly_param_value(asm, tgt_param, combined):
                        success_count += 1
                    else:
                        if asm.Id not in skipped_ids:
                            skipped_ids.append(asm.Id)

tx.Commit()


# ════════════════════════════════════════════════════════════════════════════
# КРОК 11: Звіт
# ════════════════════════════════════════════════════════════════════════════
all_skipped = list(set(skipped_ids + no_room_ids))
if all_skipped:
    id_list = List[ElementId]()
    for eid in all_skipped:
        id_list.Add(eid)
    uidoc.Selection.SetElementIds(id_list)

report = []
report.append(u"Успішно: {}".format(success_count))
if no_room_ids:
    report.append(u"Не знайдено приміщення: {} (виділено в моделі)".format(len(set(no_room_ids))))
if no_nested_ids:
    report.append(u"Без підсімейств — пропущено: {}".format(len(set(no_nested_ids))))
if skipped_ids:
    report.append(u"Немає значення в джерелі: {}".format(len(set(skipped_ids))))
if already_ids:
    report.append(u"Пропущено (вже заповнено): {}".format(len(set(already_ids))))

forms.alert(u"\n".join(report), title=u"Результат")
