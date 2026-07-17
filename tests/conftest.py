from __future__ import annotations

import functools
import os
import sys

import ifcopenshell

# VectorWorks 公式スタブ (vs.py) を tests/ ディレクトリからインポートできるようにする。
# CI 環境では GitHub Actions ワークフローが curl でダウンロードする。
sys.path.insert(0, os.path.dirname(__file__))

# クラッシュ診断用トレース (tracing.py) はテスト中は無効化する(ホームディレクトリへ
# ログを書き込まないようにする)。トレース自体の動作は tests/test_trace.py が
# 一時ディレクトリに切り替えた上で検証する。
from vectorworks_plugin_import_ifc_homeskz import tracing as _trace  # noqa: E402
from vectorworks_plugin_import_ifc_homeskz.ifc import open_ifc as _open_ifc  # noqa: E402

_trace.TRACE_ENABLED = False

# フィクスチャ IFC の格納ディレクトリ。各テストモジュールはここを個別に定義せず
# 下記の共有ローダーを使う。
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@functools.lru_cache(maxsize=None)
def load_fixture_ifc(filename: str) -> ifcopenshell.file:
    """フィクスチャ IFC を解析して返す(セッション内で 1 回だけ解析しキャッシュ共有)。

    フィクスチャ IFC (~2MB) の解析 (``open_ifc``) はテスト時間の支配的なコストで、
    同じファイルがテスト間で何十回も再解析されている。``build_document`` /
    ``build_*_commands`` は IFC を読み取るだけで変更しないため、解析結果を
    ワーカープロセス内で共有しても安全。これによりファイルごとの解析は 1 回で済む
    (pytest-xdist の各ワーカーはそれぞれ自身のキャッシュを持つ)。

    ``open_ifc`` 自体のバージョン別サニタイズ挙動を検証する ``test_ifc_loader`` は
    このキャッシュを経由せず ``open_ifc`` を直接呼ぶため影響を受けない。
    """
    return _open_ifc(os.path.join(FIXTURES_DIR, filename))
