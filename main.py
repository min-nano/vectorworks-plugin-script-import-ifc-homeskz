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
# タイムアウトで pip を kill するとコピー途中の部分的なファイルが残り
# インストールが破損するため、遅いフォルダ (iCloud 同期下の設定フォルダ等)
# でも完了できる長さにする
INSTALL_TIMEOUT_SECONDS = 1800.0


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


# 直近のサブプロセス失敗出力 (復旧失敗ダイアログでの診断用)
_last_subprocess_output: list[str] = []


def _run_interpreter(interpreter: str, args: list[str]) -> bool:
    """同梱インタプリタをサブプロセス実行し、成功したかどうかを返す。

    失敗した場合は出力の末尾を _last_subprocess_output に記録する。
    """
    try:
        completed = subprocess.run(
            [interpreter, *args],
            capture_output=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
            # Windows でコンソールウィンドウを表示させない (他 OS では 0)
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _last_subprocess_output.append(f"{type(error).__name__}: {error}")
        return False
    if completed.returncode == 0:
        return True
    output = (completed.stderr or completed.stdout or b"").decode(
        "utf-8", errors="replace"
    )
    _last_subprocess_output.append(output[-500:])
    return False


def _run_pip(args: list[str]) -> bool:
    """pip を実行し、成功したかどうかを返す。

    VectorWorks 同梱の Python に pip が含まれていない場合は ensurepip で
    ユーザサイトへブートストラップする。サブプロセスで実行できる
    インタプリタが見つからない場合や pip を用意できない場合は、
    VectorWorks 内蔵 Python 上でのインプロセス実行にフォールバックする。
    """
    interpreter = _find_python_interpreter()
    if interpreter is not None:
        has_pip = _run_interpreter(interpreter, ["-m", "pip", "--version"])
        if not has_pip:
            has_pip = _run_interpreter(
                interpreter, ["-m", "ensurepip", "--user"]
            ) and _run_interpreter(interpreter, ["-m", "pip", "--version"])
        if has_pip and _run_interpreter(interpreter, ["-m", "pip", *args]):
            return True
    try:
        pip_main = importlib.import_module("pip._internal.cli.main").main
    except (ImportError, AttributeError):
        try:
            pip_main = importlib.import_module("pip").main
        except (ImportError, AttributeError):
            _last_subprocess_output.append(
                "pip がサブプロセスでもインプロセスでも利用できません"
            )
            return False
    return bool(pip_main(args) == 0)


def _purge_cached_modules(externals: str) -> None:
    """Python Externals 由来のキャッシュ済みモジュールを破棄する。

    VectorWorks はスクリプト実行間で Python インタプリタを保持するため、
    更新後も旧バージョンのモジュールが sys.modules に残る。pip は本体
    だけでなく ifcopenshell 等の依存も更新し得るので、本体パッケージに
    加えて Python Externals から読み込まれた全モジュールを破棄し、
    次回 import で新バージョンを読み込ませる。
    """
    prefix = os.path.normcase(os.path.abspath(externals)) + os.sep
    for name, module in list(sys.modules.items()):
        if name == MODULE_NAME or name.startswith(MODULE_NAME + "."):
            del sys.modules[name]
            continue
        file = getattr(module, "__file__", None)
        if file and os.path.normcase(os.path.abspath(file)).startswith(prefix):
            del sys.modules[name]


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
    # pip は --target の既存内容を「インストール済み」とみなさず依存も毎回
    # コピーし直すため、通常更新は --no-deps で本体だけ入れ替える。
    # ifcopenshell 等の大きな依存を毎回書き換えると、遅いフォルダ (iCloud
    # 同期下の設定フォルダ等) でタイムアウト kill による部分書き込みが残る
    # リスクがある。依存の不足・破損は import 失敗時に _repair_install()
    # が依存ごと再インストールして補う。
    pip_args = [
        "install",
        "--upgrade",
        # コミットが変わってもバージョン番号は変わらないことがあるため、
        # 同一バージョン扱いでスキップされないよう強制再インストールする
        "--force-reinstall",
        "--no-deps",
        "--target",
        externals,
        archive_url,
    ]
    if not _run_pip(pip_args):
        return
    _activate_externals(externals)


def _activate_externals(externals: str) -> None:
    """インストール直後の Python Externals を確実に参照させる。

    sys.path の後方や別の場所にある旧版より優先されるよう Python
    Externals を sys.path の先頭へ移動し、キャッシュ済みモジュールを
    破棄する。
    """
    if externals in sys.path:
        sys.path.remove(externals)
    sys.path.insert(0, externals)
    _purge_cached_modules(externals)
    importlib.invalidate_caches()


def _repair_install() -> str | None:
    """破損したインストールを依存ごと強制再インストールして復旧する。

    タイムアウト kill 等で部分的に書き込まれたパッケージが Python
    Externals に残ると import が失敗し続けるため、main の最新コミットを
    依存ライブラリも含めてクリーンに入れ直す。復旧できた場合は None、
    できない場合は理由のメッセージを返す。
    """
    externals = _find_python_externals()
    if externals is None:
        return "Python Externals フォルダを検出できませんでした。"
    latest = _latest_commit()
    if latest is None:
        return (
            "GitHub から最新コミットを取得できませんでした"
            " (インターネット接続を確認してください)。"
        )
    archive_url = ARCHIVE_URL_TEMPLATE.format(sha=latest)
    pip_args = [
        "install",
        "--upgrade",
        "--force-reinstall",
        "--target",
        externals,
        archive_url,
    ]
    if not _run_pip(pip_args):
        detail = _last_subprocess_output[-1] if _last_subprocess_output else ""
        return "pip による再インストールに失敗しました。\n" + detail
    _activate_externals(externals)
    return None


def _alert(message: str) -> None:
    """vs.AlrtDialog でメッセージを表示する (vs が無い環境では何もしない)。"""
    try:
        import vs

        vs.AlrtDialog(message)
    except Exception:
        pass


def _main() -> None:
    try:
        _upgrade_if_available()
    except Exception:
        # 更新の失敗がプラグイン本体の実行を妨げてはならない
        pass
    try:
        module = importlib.import_module(MODULE_NAME)
    except Exception:
        # 部分書き込み等でインストールが破損していると import が失敗し
        # 続けるため、依存ごと強制再インストールして復旧を試みる
        try:
            failure = _repair_install()
        except Exception as error:
            failure = f"再インストール中にエラーが発生しました: {error}"
        if failure is not None:
            _alert(
                "プラグインの読み込みに失敗し、自動復旧もできませんでした。\n"
                + failure
            )
            raise
        module = importlib.import_module(MODULE_NAME)
    module.run()


_main()
