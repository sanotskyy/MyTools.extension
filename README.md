# MyTools для pyRevit

Набір інструментів для Autodesk Revit на базі pyRevit.

| Кнопка | Функція |
|--------|---------|
| **QR-код** | Генерує QR з URL-параметра → записує в Image-параметр елементів |
| **Фото** | Завантажує зображення з папки → записує в Image-параметр сімейства |
| **Листи** | Перенумерація листів проекту (всі / виділені / по колекції) |
| **Параметри** | Копіювання параметрів між елементами, приміщеннями та підсімействами |

---

## Встановлення через pyRevit

1. Відкрийте **pyRevit Settings** (вкладка pyRevit → Settings)
2. Перейдіть на вкладку **Extensions**
3. Натисніть **+** → **Add Extension from URL**
4. Вставте URL цього репозиторію:
   ```
   https://github.com/ВАШ_ЛОГІН/MyTools.extension
   ```
5. Натисніть **Save** → **Reload pyRevit**
6. З'явиться нова вкладка **MyTools**

---

## Оновлення

Після будь-яких змін у репозиторії достатньо в Revit виконати:

**pyRevit → Update** або **pyRevit → Reload**

pyRevit сам підтягне останню версію з GitHub.

---

## Структура репозиторію

```
MyTools.extension/          ← корінь репозиторію
├── extension.json
├── lib/
│   ├── mytools_ui.py       ← спільні UI-утиліти
│   └── mytools_templates.py
└── MyTools.tab/
    └── Зображення.panel/
        ├── GenerateQR.pushbutton/
        │   ├── script.py
        │   └── bundle.yaml
        ├── Фото.pushbutton/
        │   ├── script.py
        │   └── bundle.yaml
        ├── Листи.pushbutton/
        │   ├── script.py
        │   └── bundle.yaml
        └── Параметри.pushbutton/
            ├── script.py
            └── bundle.yaml
```

---

## Як змінити скрипт

1. Відкрийте потрібний `script.py` прямо на GitHub (кнопка ✏️ Edit)
2. Внесіть зміни → **Commit changes**
3. В Revit: **pyRevit → Update** → зміни одразу активні
