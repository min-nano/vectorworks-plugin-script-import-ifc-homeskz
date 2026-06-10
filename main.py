"""VectorWorks に登録するラッパースクリプト。

実行のたびに GitHub 上の最新バージョンを確認し、新しいバージョンが公開
されていれば pip で VectorWorks 設定フォルダ内の Python Externals
フォルダへ更新インストールしてから、プラグイン本体を実行する。
インターネットに接続できない等で更新を確認できない場合は、
アップグレードをスキップしてインストール済みのバージョンを実行する。
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import urllib.request

PACKAGE_NAME = "vectorworks-plugin-import-ifc-homeskz"
MODULE_NAME = "vectorworks_plugin_import_ifc_homeskz"
REPOSITORY = "h-ikeda/vectorworks_plugin_import_ifc_homeskz"
PYPROJECT_URL = (
    f"https://raw.githubusercontent.com/{REPOSITORY}/main/pyproject.toml"
)
ARCHIVE_URL = f"https://github.com/{REPOSITORY}/archive/refs/heads/main.tar.gz"
EXTERNALS_FOLDER_NAME = "Python Externals"
# vs.GetFolderPath の負数はユーザフォルダ系を指し、-15 は設定フォルダ
# (ユーザデータフォルダ) を返す
USER_FOLDER_SPECIFIER = -15
NETWORK_TIMEOUT_SECONDS = 10.0
INSTALL_TIMEOUT_SECONDS = 600.0


def _find_python_externals() -> str | None:
    """VectorWorks 設定フォルダ内の Python Externals フォルダを検出する。

    VectorWorks は設定フォルダ内の Python Externals を sys.path に自動で
    追加するため、まず sys.path から実在するフォルダを探す。見つからない
    場合は vs API で設定フォルダを取得し、その直下を探す。誤った場所への
    インストールを避けるため、実在を確認できたフォルダだけを返す。
    """
    for entry in sys.path:
        name = os.path.basename(os.path.normpath(entry))
        if name == EXTERNALS_FOLDER_NAME and os.path.isdir(entry):
            return entry
    try:
        import vs
    except ImportError:
        return None
    user_folder = vs.GetFolderPath(USER_FOLDER_SPECIFIER)
    candidate = os.path.join(user_folder, EXTERNALS_FOLDER_NAME)
    if os.path.isdir(candidate):
        return candidate
    return None


def _installed_version() -> str | None:
    """インストール済みパッケージのバージョンを返す。未導入なら None。"""
    try:
        from importlib import metadata

        return metadata.version(PACKAGE_NAME)
    except Exception:
        return None


def _latest_version() -> str | None:
    """GitHub 上の pyproject.toml から最新バージョンを取得する。

    インターネットに接続できない等で取得に失敗した場合は None を返す。
    """
    try:
        with urllib.request.urlopen(
            PYPROJECT_URL, timeout=NETWORK_TIMEOUT_SECONDS
        ) as response:
            text = response.read().decode("utf-8")
    except Exception:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _parse_version(version: str) -> tuple[int, ...]:
    """"1.2.3" 形式のバージョン文字列を比較可能な数値タプルへ変換する。"""
    parts: list[int] = []
    for part in version.split("."):
        digits = re.match(r"\d+", part)
        parts.append(int(digits.group()) if digits else 0)
    return tuple(parts)


def _is_newer(latest: str, installed: str | None) -> bool:
    """最新バージョンがインストール済みより新しいか判定する。"""
    if installed is None:
        return True
    return _parse_version(latest) > _parse_version(installed)


def _find_python_interpreter() -> str | None:
    """VectorWorks 同梱の Python インタプリタ実行ファイルを探す。

    VectorWorks 内蔵 Python では sys.executable が VectorWorks 本体を指す
    ことがあるため、pip をサブプロセスで実行できるインタプリタ本体を
    sys.prefix 系のパスから探す。
    """
    executable = sys.executable
    if executable and os.path.basename(executable).lower().startswith("python"):
        return executable
    for prefix in {sys.base_prefix, sys.exec_prefix, sys.prefix}:
        for relative in (
            "python.exe",
            os.path.join("bin", "python3"),
            os.path.join("bin", "python"),
        ):
            candidate = os.path.join(prefix, relative)
            if os.path.isfile(candidate):
                return candidate
    return None


def _run_pip(args: list[str]) -> bool:
    """pip を実行し、成功したかどうかを返す。

    サブプロセスで実行できるインタプリタが見つからない場合は、
    VectorWorks 内蔵 Python 上でインプロセス実行にフォールバックする。
    """
    interpreter = _find_python_interpreter()
    if interpreter is not None:
        completed = subprocess.run(
            [interpreter, "-m", "pip", *args],
            capture_output=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
            # Windows でコンソールウィンドウを表示させない (他 OS では 0)
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0
    try:
        pip_main = importlib.import_module("pip._internal.cli.main").main
    except (ImportError, AttributeError):
        try:
            pip_main = importlib.import_module("pip").main
        except (ImportError, AttributeError):
            return False
    return bool(pip_main(args) == 0)


def _upgrade_if_available() -> None:
    """GitHub に新しいバージョンがあれば Python Externals へ更新する。

    最新バージョンの確認に失敗した場合 (オフライン等) や Python
    Externals フォルダを検出できない場合は何もしない。
    """
    latest = _latest_version()
    if latest is None or not _is_newer(latest, _installed_version()):
        return
    externals = _find_python_externals()
    if externals is None:
        return
    if not _run_pip(["install", "--upgrade", "--target", externals, ARCHIVE_URL]):
        return
    if externals not in sys.path:
        sys.path.insert(0, externals)
    # VectorWorks はスクリプト実行間で Python インタプリタを保持するため、
    # 旧バージョンのキャッシュ済みモジュールを破棄して再読込させる
    for name in [
        n
        for n in sys.modules
        if n == MODULE_NAME or n.startswith(MODULE_NAME + ".")
    ]:
        del sys.modules[name]
    importlib.invalidate_caches()


def _main() -> None:
    try:
        _upgrade_if_available()
    except Exception:
        # 更新の失敗がプラグイン本体の実行を妨げてはならない
        pass
    module = importlib.import_module(MODULE_NAME)
    module.run()


_main()
