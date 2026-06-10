"""VectorWorks に登録するラッパースクリプト。

実行のたびに GitHub の main ブランチの最新コミットを確認し、インストール
済みのコミットと異なれば pip で VectorWorks 設定フォルダ内の Python
Externals フォルダへ更新インストールしてから、プラグイン本体を実行する。
main ブランチは常にテスト済みのため、バージョン番号ではなくコミット SHA
の一致で最新かどうかを判定する。インターネットに接続できない等で確認
できない場合は、アップグレードをスキップしてインストール済みのバージョン
を実行する。
"""

from __future__ import annotations

import glob
import importlib
import os
import re
import subprocess
import sys
import urllib.request

PACKAGE_NAME = "vectorworks-plugin-import-ifc-homeskz"
MODULE_NAME = "vectorworks_plugin_import_ifc_homeskz"
REPOSITORY = "h-ikeda/vectorworks_plugin_import_ifc_homeskz"
COMMITS_API_URL = f"https://api.github.com/repos/{REPOSITORY}/commits/main"
ARCHIVE_URL_TEMPLATE = f"https://github.com/{REPOSITORY}/archive/{{sha}}.tar.gz"
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


def _installed_commit(externals: str) -> str | None:
    """Python Externals 内のパッケージの取得元コミット SHA を返す。

    pip が dist-info に記録する direct_url.json (PEP 610) のアーカイブ URL
    から SHA を取り出す。sys.path 上の別環境にある同名パッケージを誤って
    参照しないよう、更新先である Python Externals フォルダ直下の dist-info
    だけを読む。ローカルフォルダからの手動インストール等で SHA が記録
    されていない場合や一意に定まらない場合は None を返す (= 次回オンライン
    時に main の最新コミットで再インストールされる)。
    """
    pattern = os.path.join(
        externals, f"{MODULE_NAME}-*.dist-info", "direct_url.json"
    )
    shas: set[str] = set()
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as stream:
                text = stream.read()
        except OSError:
            continue
        match = re.search(r"/archive/([0-9a-f]{40})\.tar\.gz", text)
        if match is None:
            return None
        shas.add(match.group(1))
    if len(shas) == 1:
        return shas.pop()
    return None


def _latest_commit() -> str | None:
    """GitHub API から main ブランチの最新コミット SHA を取得する。

    インターネットに接続できない等で取得に失敗した場合は None を返す。
    """
    request = urllib.request.Request(
        COMMITS_API_URL,
        # SHA 文字列だけをプレーンテキストで受け取るメディアタイプ
        headers={"Accept": "application/vnd.github.sha"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=NETWORK_TIMEOUT_SECONDS
        ) as response:
            sha = response.read().decode("utf-8").strip()
    except Exception:
        return None
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None


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
    """main の最新コミットと異なるバージョンなら Python Externals へ更新する。

    最新コミットの確認に失敗した場合 (オフライン等) や Python Externals
    フォルダを検出できない場合は何もしない。
    """
    externals = _find_python_externals()
    if externals is None:
        return
    latest = _latest_commit()
    if latest is None or latest == _installed_commit(externals):
        return
    archive_url = ARCHIVE_URL_TEMPLATE.format(sha=latest)
    # コミットが変わってもバージョン番号は変わらないことがあるため、
    # 同一バージョン扱いで pip がインストールをスキップしないよう
    # --force-reinstall を付ける
    pip_args = [
        "install",
        "--upgrade",
        "--force-reinstall",
        "--target",
        externals,
        archive_url,
    ]
    if not _run_pip(pip_args):
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
