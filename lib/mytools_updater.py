# -*- coding: utf-8 -*-
"""
mytools_updater.py — логіка перевірки та встановлення оновлень з GitHub
"""

import os
import json
import codecs
import System
from System import Environment
from System.Environment import SpecialFolder

_APPDATA = Environment.GetFolderPath(SpecialFolder.ApplicationData)
_SETTINGS_PATH = os.path.join(_APPDATA, u"pyRevit", u"Extensions",
                              u"MyTools.extension", u"settings.json")

DEFAULT_SETTINGS = {
    u"auto_update": False,
    u"repo_url": u"https://github.com/sanotskyy/MyTools.extension",
}


def load_settings():
    try:
        if os.path.exists(_SETTINGS_PATH):
            with codecs.open(_SETTINGS_PATH, u"r", encoding=u"utf-8") as f:
                data = json.loads(f.read())
                s = dict(DEFAULT_SETTINGS)
                s.update(data)
                return s
    except Exception:
        pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    try:
        folder = os.path.dirname(_SETTINGS_PATH)
        if not os.path.exists(folder):
            os.makedirs(folder)
        with codecs.open(_SETTINGS_PATH, u"w", encoding=u"utf-8") as f:
            f.write(json.dumps(settings, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False


def get_repo_url():
    """Повертає URL тільки з settings.json. Якщо не вказано — None."""
    try:
        s = load_settings()
        url = s.get(u'repo_url', u'').strip()
        if url and url.startswith(u'https://'):
            return url.rstrip(u'/')
    except Exception:
        pass
    return None


def save_repo_url(url):
    s = load_settings()
    s[u'repo_url'] = url.strip().rstrip(u'/')
    save_settings(s)


def get_raw_base_url(repo_url):
    if not repo_url:
        return None
    repo_url = repo_url.rstrip(u'/')
    parts = repo_url.replace(u'https://github.com/', u'')
    return u'https://raw.githubusercontent.com/' + parts + u'/main'


def parse_version(v):
    try:
        return tuple(int(x) for x in str(v).strip().split(u'.'))
    except Exception:
        return (0, 0, 0)


def is_newer(remote_ver, local_ver):
    return parse_version(remote_ver) > parse_version(local_ver)


def fetch_remote_info(raw_base_url):
    """Завантажує extension.json з GitHub через System.Net.Http.HttpClient."""
    import clr
    clr.AddReference(u"System.Net.Http")
    from System.Net.Http import HttpClient, HttpClientHandler
    from System.Threading.Tasks import Task

    url = raw_base_url.rstrip(u'/') + u'/extension.json'

    handler = HttpClientHandler()
    client  = HttpClient(handler)
    client.DefaultRequestHeaders.Add(u"User-Agent", u"MyTools-pyRevit/1.0")

    task = client.GetStringAsync(url)
    task.Wait(15000)

    if task.IsFaulted:
        raise Exception(str(task.Exception))

    raw = task.Result
    client.Dispose()
    return json.loads(raw)


def download_and_install_zip(raw_base_url, ext_dir):
    """Завантажує ZIP з GitHub і розпаковує."""
    import clr
    clr.AddReference(u"System.Net")
    clr.AddReference(u"System.IO.Compression.FileSystem")
    from System.Net import WebClient
    from System.IO.Compression import ZipFile
    import System.IO as IO

    try:
        repo_url   = raw_base_url.replace(u'raw.githubusercontent.com', u'github.com')
        repo_url   = repo_url.replace(u'/main', u'')
        zip_url    = repo_url + u'/archive/refs/heads/main.zip'
        tmp_zip    = IO.Path.Combine(IO.Path.GetTempPath(), u'mytools_update.zip')
        tmp_folder = IO.Path.Combine(IO.Path.GetTempPath(), u'mytools_update_ext')

        wc = WebClient()
        wc.DownloadFile(zip_url, tmp_zip)

        if IO.Directory.Exists(tmp_folder):
            IO.Directory.Delete(tmp_folder, True)
        ZipFile.ExtractToDirectory(tmp_zip, tmp_folder)
        IO.File.Delete(tmp_zip)

        subdirs = list(IO.Directory.GetDirectories(tmp_folder))
        if not subdirs:
            return False, u"Не вдалось знайти вміст архіву"
        src_dir = subdirs[0]

        _copy_tree(src_dir, ext_dir)
        IO.Directory.Delete(tmp_folder, True)
        return True, u"Оновлено успішно через ZIP"

    except Exception as e:
        return False, u"Помилка завантаження: " + str(e)


def _copy_tree(src, dst):
    import System.IO as IO
    if not IO.Directory.Exists(dst):
        IO.Directory.CreateDirectory(dst)
    for file in IO.Directory.GetFiles(src):
        fname = IO.Path.GetFileName(file)
        IO.File.Copy(file, IO.Path.Combine(dst, fname), True)
    for d in IO.Directory.GetDirectories(src):
        dname = IO.Path.GetFileName(d)
        if dname == u'.git':
            continue
        _copy_tree(d, IO.Path.Combine(dst, dname))


def run_git_pull(ext_dir):
    try:
        import subprocess
        result = subprocess.run(
            [u'git', u'-C', ext_dir, u'pull', u'--ff-only'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or u"Оновлено успішно"
        else:
            return False, result.stderr.strip() or u"git pull помилка"
    except Exception as e:
        return False, u"git не знайдено: " + str(e)


def check_for_updates():
    ext_dir    = os.path.join(_APPDATA, u"pyRevit", u"Extensions", u"MyTools.extension")
    local_json = os.path.join(ext_dir, u"extension.json")

    result = {
        u'has_update': False,
        u'local':      u'невідомо',
        u'remote':     u'невідомо',
        u'repo_url':   None,
        u'raw_url':    None,
        u'error':      None,
        u'ext_dir':    ext_dir,
    }

    try:
        with codecs.open(local_json, u"r", encoding=u"utf-8") as f:
            local_data = json.loads(f.read())
        result[u'local'] = local_data.get(u'version', u'0.0.0')
    except Exception as e:
        result[u'error'] = u"Не вдалось прочитати локальну версію: " + str(e)
        return result

    repo_url = get_repo_url()
    if not repo_url:
        result[u'error'] = u"Репозиторій не знайдено. Вкажіть URL у Налаштуваннях."
        return result

    raw_url = get_raw_base_url(repo_url)
    result[u'repo_url'] = repo_url
    result[u'raw_url']  = raw_url

    try:
        remote_data = fetch_remote_info(raw_url)
    except Exception as e:
        result[u'error'] = u"Помилка з'єднання: " + str(e)
        return result

    if remote_data is None:
        result[u'error'] = u"Не вдалось отримати дані з GitHub."
        return result

    result[u'remote']     = remote_data.get(u'version', u'0.0.0')
    result[u'has_update'] = is_newer(result[u'remote'], result[u'local'])
    return result


def install_update(check_result):
    ext_dir = check_result.get(u'ext_dir', u'')
    raw_url = check_result.get(u'raw_url', u'')

    # Спроба 1: git pull
    ok, msg = run_git_pull(ext_dir)
    if ok:
        return True, msg

    # Спроба 2: ZIP — спочатку повністю видаляємо стару версію
    if raw_url:
        ok, msg = download_and_install_zip_clean(raw_url, ext_dir)
        return ok, msg

    return False, u"Не вдалось встановити оновлення"


def download_and_install_zip_clean(raw_base_url, ext_dir):
    """
    Завантажує ZIP з GitHub, повністю видаляє стару папку і встановлює заново.
    Перед видаленням зберігає: settings.json, ie_config.json, nested_templates.json
    """
    import clr
    clr.AddReference(u"System.Net.Http")
    clr.AddReference(u"System.IO.Compression.FileSystem")
    from System.Net.Http import HttpClient
    from System.IO.Compression import ZipFile
    import System.IO as IO

    # Файли які зберігаємо між оновленнями
    PRESERVE_FILES = [
        u"settings.json",
        u"ie_config.json",
        u"nested_templates.json",
    ]

    try:
        # Крок 1: Зберігаємо користувацькі файли в пам'яті
        preserved = {}
        for fname in PRESERVE_FILES:
            fpath = IO.Path.Combine(ext_dir, fname)
            if IO.File.Exists(fpath):
                preserved[fname] = IO.File.ReadAllText(fpath)

        # Крок 2: Завантажуємо ZIP з GitHub
        repo_url = raw_base_url.replace(u'raw.githubusercontent.com', u'github.com')
        repo_url = repo_url.replace(u'/main', u'')
        zip_url  = repo_url + u'/archive/refs/heads/main.zip'

        tmp_zip    = IO.Path.Combine(IO.Path.GetTempPath(), u'mytools_update.zip')
        tmp_folder = IO.Path.Combine(IO.Path.GetTempPath(), u'mytools_update_tmp')

        client = HttpClient()
        client.DefaultRequestHeaders.Add(u"User-Agent", u"MyTools-pyRevit/1.0")
        task = client.GetByteArrayAsync(zip_url)
        task.Wait(30000)
        if task.IsFaulted:
            raise Exception(str(task.Exception))
        IO.File.WriteAllBytes(tmp_zip, task.Result)
        client.Dispose()

        # Крок 3: Розпаковуємо в temp
        if IO.Directory.Exists(tmp_folder):
            IO.Directory.Delete(tmp_folder, True)
        ZipFile.ExtractToDirectory(tmp_zip, tmp_folder)
        IO.File.Delete(tmp_zip)

        subdirs = list(IO.Directory.GetDirectories(tmp_folder))
        if not subdirs:
            IO.Directory.Delete(tmp_folder, True)
            return False, u"Не вдалось знайти вміст архіву"
        src_dir = subdirs[0]

        # Крок 4: Повністю видаляємо стару папку (крім .git)
        if IO.Directory.Exists(ext_dir):
            for item in IO.Directory.GetDirectories(ext_dir):
                if IO.Path.GetFileName(item) != u'.git':
                    IO.Directory.Delete(item, True)
            for item in IO.Directory.GetFiles(ext_dir):
                IO.File.Delete(item)

        # Крок 5: Копіюємо нову версію
        _copy_tree(src_dir, ext_dir)
        IO.Directory.Delete(tmp_folder, True)

        # Крок 6: Відновлюємо збережені файли
        for fname, content in preserved.items():
            fpath = IO.Path.Combine(ext_dir, fname)
            IO.File.WriteAllText(fpath, content)

        return True, u"Оновлено успішно"

    except Exception as e:
        return False, u"Помилка оновлення: " + str(e)
