"""VectorWorks に登録するラッパースクリプト。

実行のたびに GitHub の main ブランチの最新コミットを確認し、インストール
済みのコミットと異なれば VectorWorks 設定フォルダ内の Python Externals
フォルダへ更新インストールしてから、プラグイン本体を実行する。
本体パッケージは純 Python のためアーカイブの直接展開でインストールし
(VectorWorks 同梱の Python では pip を実行できない場合があるため pip に
依存しない)、ifcopenshell 等の依存ライブラリだけを pip で揃える。
パッケージが未インストールの場合 (初回起動時) は依存ライブラリも含めて
自動的に新規インストールする。
main ブランチは常にテスト済みのため、バージョン番号ではなくコミット SHA
の一致で最新かどうかを判定する。インターネットに接続できない等で確認
できない場合は、アップグレードをスキップしてインストール済みのバージョン
を実行する。
"""

from __future__ import annotations

import glob
import importlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

PACKAGE_NAME = "vectorworks-plugin-import-ifc-homeskz"
MODULE_NAME = "vectorworks_plugin_import_ifc_homeskz"
# pip でインストールする依存ライブラリ (pyproject.toml の dependencies と
# 同期させること)
DEPENDENCIES = ("ifcopenshell", "certifi")
REPOSITORY = "h-ikeda/vectorworks_plugin_import_ifc_homeskz"
# GitHub REST API は匿名アクセスのレートリミットが厳しいため、制限のない
# git smart HTTP プロトコルの参照広告エンドポイントから SHA を取得する
REFS_URL = f"https://github.com/{REPOSITORY}.git/info/refs?service=git-upload-pack"
ARCHIVE_URL_TEMPLATE = f"https://github.com/{REPOSITORY}/archive/{{sha}}.tar.gz"
EXTERNALS_FOLDER_NAME = "Python Externals"
# vs.GetFolderPath の負数はユーザフォルダ系を指し、-15 は設定フォルダ
# (ユーザデータフォルダ) を返す
USER_FOLDER_SPECIFIER = -15
NETWORK_TIMEOUT_SECONDS = 10.0
# インタプリタ確認 (probe) 用の短いタイムアウト。誤って VectorWorks 等の
# アプリを起動してしまった場合も、この時間で kill される
PROBE_TIMEOUT_SECONDS = 15.0
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


def _is_installed(externals: str) -> bool:
    """本体パッケージが Python Externals にインストール済みか判定する。"""
    pattern = os.path.join(externals, f"{MODULE_NAME}-*.dist-info")
    return bool(glob.glob(pattern))


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


# 直近のネットワーク失敗の内容 (復旧失敗ダイアログでの診断用)
_last_network_error: list[str] = []


def _ssl_contexts() -> list[ssl.SSLContext]:
    """HTTPS 用の SSL コンテキストの候補を順に返す。

    システムの証明書設定に従う既定のコンテキストを優先しつつ、
    VectorWorks 同梱の Python に CA 証明書バンドルが含まれない場合に
    備えて、certifi (本パッケージの依存として Python Externals に入る)
    や pip 同梱の CA バンドルを使うコンテキストも候補に加える。
    """
    contexts: list[ssl.SSLContext] = []
    try:
        contexts.append(ssl.create_default_context())
    except Exception:
        pass
    for module_name in ("certifi", "pip._vendor.certifi"):
        try:
            certifi = importlib.import_module(module_name)
            contexts.append(ssl.create_default_context(cafile=certifi.where()))
        except Exception:
            continue
    return contexts


def _fetch(url: str) -> bytes | None:
    """URL の内容を取得する。失敗時は理由を記録して None を返す。

    証明書検証の失敗に備えて、SSL コンテキストの候補を順に試す。
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": PACKAGE_NAME}
    )
    for context in _ssl_contexts():
        try:
            with urllib.request.urlopen(
                request, timeout=NETWORK_TIMEOUT_SECONDS, context=context
            ) as response:
                return bytes(response.read())
        except Exception as error:
            _last_network_error.append(f"{type(error).__name__}: {error}")
    return None


def _latest_commit() -> str | None:
    """main ブランチの最新コミット SHA を取得する。

    インターネットに接続できない等で取得に失敗した場合は None を返す。
    """
    body = _fetch(REFS_URL)
    if body is None:
        return None
    text = body.decode("utf-8", errors="replace")
    match = re.search(r"([0-9a-f]{40}) refs/heads/main\b", text)
    return match.group(1) if match else None


def _subprocess_env() -> dict[str, str]:
    """サブプロセス用に Python 関連の環境変数を除いた環境を返す。

    VectorWorks は内蔵 Python 用に __PYVENV_LAUNCHER__ 等を設定して
    おり、これを子インタプリタが継承すると sys.executable が
    VectorWorks 本体を指す。pip はビルド時に sys.executable を子
    プロセスとして起動するため、そのままでは VectorWorks が多重起動
    してしまう。
    """
    env = dict(os.environ)
    for name in (
        "__PYVENV_LAUNCHER__",
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
    ):
        env.pop(name, None)
    return env


def _is_python_interpreter(candidate: str) -> bool:
    """候補の実行ファイルが pip 実行に使える Python か確認する。

    VectorWorks 内で見つかるパスを盲目的に pip 実行に使うと
    VectorWorks 本体の多重起動を招き得るため、短いタイムアウトで
    sys.executable の名前とバージョンを print させ、Python として
    応答しないプロセスは kill して棄却する。インストールされる
    ifcopenshell 等のバイナリ wheel が VectorWorks 内蔵 Python で
    使えるよう、バージョン (major.minor) の一致も要求する。
    """
    sentinel = "vw-plugin-python-probe"
    code = (
        "import os.path, sys; "
        f"print('{sentinel}', os.path.basename(sys.executable), "
        "'.'.join(map(str, sys.version_info[:2])))"
    )
    try:
        completed = subprocess.run(
            [candidate, "-c", code],
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            # Windows でコンソールウィンドウを表示させない (他 OS では 0)
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
            env=_subprocess_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    output = completed.stdout.decode("utf-8", errors="replace")
    match = re.search(sentinel + r" (\S+) (\S+)", output)
    if match is None or not match.group(1).lower().startswith("python"):
        return False
    expected_version = ".".join(map(str, sys.version_info[:2]))
    return match.group(2) == expected_version


# 確認済みインタプリタのキャッシュ (確認の二重実行を避けるため)
_interpreter_cache: list[str | None] = []


def _find_python_interpreter() -> str | None:
    """pip 実行に使える Python インタプリタ実行ファイルを探す。

    VectorWorks 内蔵 Python では sys.executable が VectorWorks 本体を指す
    ことがあるため、同梱 Python (sys.prefix 系) とシステムの Python から
    候補を集め、実際に Python として応答しバージョンが一致することを
    確認できたものだけを返す。
    """
    if _interpreter_cache:
        return _interpreter_cache[0]
    candidates: list[str] = []
    executable = sys.executable
    if executable and os.path.basename(executable).lower().startswith("python"):
        candidates.append(executable)
    for prefix in {sys.base_prefix, sys.exec_prefix, sys.prefix}:
        for relative in (
            "python.exe",
            os.path.join("bin", "python3"),
            os.path.join("bin", "python"),
        ):
            candidates.append(os.path.join(prefix, relative))
    # VectorWorks 同梱の Python に単体起動できる実体が無い場合に備えて
    # システムの Python も候補にする (バージョン一致は probe で確認する)
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    # macOS 標準の Python (GUI アプリの PATH に含まれない場合に備える)
    candidates.append("/usr/bin/python3")
    result: str | None = None
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen or not os.path.isfile(candidate):
            continue
        seen.add(candidate)
        if _is_python_interpreter(candidate):
            result = candidate
            break
    _interpreter_cache.append(result)
    return result


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
            env=_subprocess_env(),
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
    # インプロセス pip もビルド時に sys.executable を子プロセスとして
    # 起動するため、sys.executable が VectorWorks 本体を指す環境では
    # 多重起動を招く。Python を指している場合だけフォールバックする
    if not os.path.basename(sys.executable or "").lower().startswith("python"):
        _last_subprocess_output.append(
            "pip を安全に実行できる Python インタプリタが見つかりません"
        )
        return False
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


def _extract_package(archive: tarfile.TarFile, destination: str) -> None:
    """tarball 内の src/<パッケージ> 配下のファイルを destination へ展開する。"""
    marker = f"/src/{MODULE_NAME}/"
    for member in archive.getmembers():
        if not member.isfile():
            continue
        index = member.name.find(marker)
        if index < 0:
            continue
        relative = member.name[index + len("/src/"):]
        parts = relative.split("/")
        # パストラバーサルを防ぐ
        if any(part in ("", "..") for part in parts):
            continue
        target = os.path.join(destination, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            continue
        with source, open(target, "wb") as stream:
            shutil.copyfileobj(source, stream)


def _replace_package_dir(externals: str, staged: str) -> None:
    """展開済みの新しい本体パッケージで Python Externals 内を置き換える。

    旧バージョンをリネームして退避してからコピーし、失敗した場合は
    旧バージョンへ戻す。
    """
    target = os.path.join(externals, MODULE_NAME)
    backup = target + ".old"
    if os.path.isdir(backup):
        shutil.rmtree(backup)
    if os.path.isdir(target):
        os.rename(target, backup)
    try:
        shutil.copytree(staged, target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        if os.path.isdir(backup):
            os.rename(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _write_dist_info(externals: str, archive_url: str) -> None:
    """インストール元 (コミット SHA 入り URL) を dist-info に記録する。

    pip が記録する direct_url.json (PEP 610) と同じ場所・形式にして、
    _installed_commit() が pip でのインストールと区別なく読めるように
    する。既存の dist-info は古い情報のため置き換える。
    """
    pattern = os.path.join(externals, f"{MODULE_NAME}-*.dist-info")
    for stale in glob.glob(pattern):
        shutil.rmtree(stale, ignore_errors=True)
    dist_info = os.path.join(externals, f"{MODULE_NAME}-0.0.0.dist-info")
    os.makedirs(dist_info, exist_ok=True)
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {PACKAGE_NAME}\n"
        "Version: 0.0.0\n"
    )
    with open(
        os.path.join(dist_info, "METADATA"), "w", encoding="utf-8"
    ) as stream:
        stream.write(metadata)
    with open(
        os.path.join(dist_info, "direct_url.json"), "w", encoding="utf-8"
    ) as stream:
        json.dump({"url": archive_url, "archive_info": {}}, stream)
    with open(
        os.path.join(dist_info, "INSTALLER"), "w", encoding="utf-8"
    ) as stream:
        stream.write("main.py\n")


def _install_package_from_archive(externals: str, sha: str) -> str | None:
    """本体パッケージをアーカイブの直接展開でインストールする。

    本体は純 Python のためビルド不要で、tarball 内の src/<パッケージ> を
    Python Externals へ展開するだけでよい。VectorWorks 同梱の Python では
    pip を実行できる環境が無い場合があるため、本体のインストール・更新は
    pip に依存しない。成功時は None、失敗時は理由のメッセージを返す。
    """
    archive_url = ARCHIVE_URL_TEMPLATE.format(sha=sha)
    data = _fetch(archive_url)
    if data is None:
        detail = _last_network_error[-1] if _last_network_error else ""
        return "本体パッケージのダウンロードに失敗しました。\n" + detail
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                _extract_package(archive, temp_dir)
            staged = os.path.join(temp_dir, MODULE_NAME)
            if not os.path.isdir(staged):
                return "アーカイブに本体パッケージが見つかりませんでした。"
            _replace_package_dir(externals, staged)
    except Exception as error:
        return f"本体パッケージの展開に失敗しました: {error}"
    _write_dist_info(externals, archive_url)
    return None


def _install_dependencies(externals: str) -> bool:
    """依存ライブラリを pip で Python Externals へインストールする。"""
    return _run_pip(
        ["install", "--upgrade", "--target", externals, *DEPENDENCIES]
    )


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

    本体パッケージはアーカイブの直接展開で入れ替える (pip 不要)。
    未インストール (初回起動・手動削除後) の場合は依存ライブラリも pip で
    揃える。最新コミットの確認に失敗した場合 (オフライン等) や Python
    Externals フォルダを検出できない場合は何もしない。
    """
    externals = _find_python_externals()
    if externals is None:
        return
    latest = _latest_commit()
    if latest is None or latest == _installed_commit(externals):
        # 更新は不要でも、import が別の場所の同名パッケージを拾わないよう
        # sys.path の優先順位だけは毎回整える (キャッシュは破棄しない)
        _prioritize_externals(externals)
        return
    fresh = not _is_installed(externals)
    if _install_package_from_archive(externals, latest) is not None:
        return
    if fresh:
        # 初回は依存ライブラリも揃える。失敗しても本体は入っているため、
        # import 失敗を経て _repair_install() が改めて試み、それでも
        # ダメなら理由をダイアログで表示する
        _install_dependencies(externals)
    _activate_externals(externals)


def _prioritize_externals(externals: str) -> None:
    """Python Externals を sys.path の先頭へ移動する。

    更新判定は Python Externals 内のパッケージを基準にしているため、
    実行時の import でも sys.path の後方や別の場所にある同名パッケージ
    より Python Externals が優先されるようにする。
    """
    if externals in sys.path:
        sys.path.remove(externals)
    sys.path.insert(0, externals)


def _activate_externals(externals: str) -> None:
    """インストール直後の Python Externals を確実に参照させる。

    sys.path の優先順位を整えたうえで、キャッシュ済みの旧バージョンの
    モジュールを破棄する。
    """
    _prioritize_externals(externals)
    _purge_cached_modules(externals)
    importlib.invalidate_caches()


def _repair_install() -> str | None:
    """破損したインストールを丸ごと入れ直して復旧する。

    部分的に書き込まれたパッケージが Python Externals に残ると import が
    失敗し続けるため、main の最新コミットの本体を展開し直し、依存
    ライブラリも pip で入れ直す。復旧できた場合は None、できない場合は
    理由のメッセージを返す。
    """
    externals = _find_python_externals()
    if externals is None:
        return "Python Externals フォルダを検出できませんでした。"
    latest = _latest_commit()
    if latest is None:
        detail = _last_network_error[-1] if _last_network_error else ""
        return (
            "GitHub から最新コミットを取得できませんでした"
            " (インターネット接続を確認してください)。\n" + detail
        )
    failure = _install_package_from_archive(externals, latest)
    if failure is not None:
        return failure
    if not _install_dependencies(externals):
        detail = _last_subprocess_output[-1] if _last_subprocess_output else ""
        command = (
            f'python3 -m pip install --upgrade --target "{externals}" '
            + " ".join(DEPENDENCIES)
        )
        return (
            "依存ライブラリを自動インストールできませんでした。"
            "ターミナルで以下を実行してください:\n"
            f"{command}\n" + detail
        )
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
