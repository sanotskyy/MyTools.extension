# -*- coding: utf-8 -*-
"""
mytools_templates.py — спільний менеджер шаблонів для MyTools.extension
"""

import os
import json
import codecs

import System
from System import Environment
from System.Environment import SpecialFolder

# Базова папка для зберігання всіх шаблонів
_BASE_DIR = os.path.join(
    Environment.GetFolderPath(SpecialFolder.ApplicationData),
    u"pyRevit", u"Extensions", u"MyTools.extension"
)


def _get_path(filename):
    return os.path.join(_BASE_DIR, filename)


def load_json(filename):
    path = _get_path(filename)
    try:
        if os.path.exists(path):
            with codecs.open(path, u"r", encoding=u"utf-8") as f:
                data = json.loads(f.read())
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def save_json(filename, data):
    path = _get_path(filename)
    try:
        folder = os.path.dirname(path)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with codecs.open(path, u"w", encoding=u"utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False


# Файли шаблонів для кожного інструменту
QR_TEMPLATES_FILE     = u"qr_templates.json"
PHOTO_TEMPLATES_FILE  = u"photo_templates.json"
NESTED_TEMPLATES_FILE = u"nested_templates.json"
