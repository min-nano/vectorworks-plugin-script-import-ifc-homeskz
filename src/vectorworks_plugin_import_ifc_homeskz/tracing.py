"""クラッシュ診断用のトレースログ。vs / ifcopenshell 非依存。

VectorWorks 本体が Python 例外を伴わずにクラッシュ(強制終了)する問題の切り分けの
ため、インポート処理の各ステップを即時フラッシュ + fsync でファイルに記録する。
クラッシュ直前までの行がファイルに残るため、**ログの最後に記録された行の直後の
処理がクラッシュ箇所**として特定できる(Python 例外なら ``run()`` の except が
ダイアログを出すので、無言のクラッシュ = native クラッシュの切り分け専用)。

ログはホームディレクトリの ``import_ifc_homeskz_trace.log`` に追記する。
``TRACE_ENABLED`` を False にすると一切書き込まない(診断が終わったら False に
戻す)。書き込みエラーは握りつぶし、インポート処理を妨げない。
"""
from __future__ import annotations

import datetime
import os

# 診断が終わったら False に戻す(通常運用ではログを書かない)。
TRACE_ENABLED = True

# ログの出力先: ホームディレクトリ直下(VW の実行環境で確実に書ける場所)。
TRACE_PATH = os.path.join(os.path.expanduser('~'), 'import_ifc_homeskz_trace.log')


def trace(message: str) -> None:
    """トレース行を追記する。

    開く → 書く → フラッシュ → fsync → 閉じる を毎回行い、直後に VectorWorks
    本体がクラッシュしても行がファイルに残るようにする(クラッシュ耐性優先。
    書き込み回数は少ないため性能影響は無視できる)。
    """
    if not TRACE_ENABLED:
        return
    try:
        with open(TRACE_PATH, 'a', encoding='utf-8') as f:
            stamp = datetime.datetime.now().isoformat(timespec='milliseconds')
            f.write(f'{stamp} {message}\n')
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass
