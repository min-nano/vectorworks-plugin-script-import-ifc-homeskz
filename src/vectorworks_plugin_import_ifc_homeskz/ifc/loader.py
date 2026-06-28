"""IFC ファイルの読み込み(解析前のサニタイズを含む)。vs 非依存。

ホームズ君 EX が出力する IFC2X3 ファイルには、IFC4 でのみ定義され IFC2X3 スキーマ
には存在しない ``IfcFootingType``(STEP では ``IFCFOOTINGTYPE``)が混入している。
新しい ifcopenshell(0.8.5+ / Python 3.10+)はこの不正エンティティを読み飛ばすが、
Python 3.9 で唯一解決される ``ifcopenshell==0.8.4.post1`` はこれにつまずいて周辺の
正常な ``IfcFooting``・``IfcSlab`` まで取りこぼす(基礎が 1 件しか読めなくなる)。

このモジュールは解析前にスキーマ非適合のエンティティをテキストから除去してから
ifcopenshell に渡すことで、どの ifcopenshell / Python バージョンでも基礎要素が
正しく読まれるようにする。除去対象は基礎の型エンティティのみで、本スクリプトは
``IfcFooting`` の型(``IfcRelDefinesByType`` 経由)を参照しないため、除去しても
抽出結果に影響しない。
"""
from __future__ import annotations

import re

import ifcopenshell

# IFC4 でのみ定義され IFC2X3 スキーマに存在しない型エンティティ(STEP の型名)。
# これらが IFC2X3 ファイルに混入していると古い ifcopenshell が解析に失敗する。
_INVALID_IFC2X3_TYPE_ENTITIES = ('IFCFOOTINGTYPE',)

# STEP のインスタンス行 "#<id>= IFCFOOTINGTYPE(...);" にマッチする。
# 引数中にセミコロンは現れない(非 ASCII 文字は \X2\..\X0\ 形式でエンコードされ、
# 生のセミコロンを含まない)ため [^;]* で 1 インスタンスを安全に取り出せる。
_INSTANCE_RE = re.compile(
    r'#\d+\s*=\s*(?:' + '|'.join(_INVALID_IFC2X3_TYPE_ENTITIES) + r')\s*\([^;]*\)\s*;',
    re.IGNORECASE,
)


def _is_ifc2x3(text: str) -> bool:
    """STEP ヘッダの FILE_SCHEMA が IFC2X3 を宣言していれば True。"""
    header = text[:4096].upper()
    return 'FILE_SCHEMA' in header and 'IFC2X3' in header


def _sanitize(text: str) -> str | None:
    """IFC2X3 で不正な型エンティティを除去したテキストを返す。

    除去対象が無い、または IFC2X3 でない場合は None(サニタイズ不要)。
    """
    if not _is_ifc2x3(text):
        return None
    sanitized, count = _INSTANCE_RE.subn('', text)
    return sanitized if count > 0 else None


def open_ifc(filepath: str) -> ifcopenshell.file:
    """IFC ファイルを開く。解析前にスキーマ非適合のエンティティを除去する。

    サニタイズが不要(または読み込み/サニタイズに失敗)した場合は通常どおり
    ``ifcopenshell.open`` で開く。
    """
    try:
        # SPF は X エンコードにより実体は ASCII なので latin-1 で無損失に読める。
        with open(filepath, encoding='latin-1') as fh:
            text = fh.read()
        sanitized = _sanitize(text)
    except OSError:
        sanitized = None
    if sanitized is None:
        return ifcopenshell.open(filepath)
    return ifcopenshell.file.from_string(sanitized)
