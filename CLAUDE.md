# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリについて

**ホームズ君構造EX** から出力した木造軸組工法建築物の IFC ファイルをパースし、VectorWorks のオブジェクトに変換して配置することに特化した VectorWorks プラグインスクリプトです。

現在実装済みの機能は以下の通りです。

- グリッド線（通り芯）のインポート
- ストーリ・ストーリレベル・デザインレイヤの自動生成
- 横架材（土台・梁・桁）のインポート
- 柱（管柱・小屋束等）のインポート
- 柱・横架材への構造クラス（`04構造-02木造-…`）の自動割り当て
- 基礎（立上り＝壁オブジェクト・底盤/地中梁＝スラブオブジェクト）のインポートと基礎ストーリの自動生成

今後以下の要素のインポートも追加する予定です。

- 筋交い・面材

## アーキテクチャ: 2 フェーズ分離

処理は **IFC 解析フェーズ** と **VectorWorks 描画フェーズ** に完全分離されている。両フェーズは JSON 直列化可能な**命令セット（ドキュメント）**だけで接続され、`vs` との密結合を避けることで検証や VectorWorks バージョンアップ対応を容易にしている。

1. **IFC 解析フェーズ（`ifc` サブパッケージ）** — `vs` に一切依存しない。ifcopenshell で IFC を解析し、描くべきオブジェクトを命令セット（dict）として組み立てる。通常の Python 環境で単体実行・検証できる。
2. **描画フェーズ（`vw` サブパッケージ）** — `vs` だけに依存し、IFC・ifcopenshell の知識を持たない。命令セットを検証（`validate_document`）してから vs API で描画する。

命令セットのスキーマ（version・stories/grids/members/columns/walls/slabs 各命令の形式）は `document.py` の docstring に定義されている。スキーマを変更するときは `DOCUMENT_VERSION` の互換性に注意し、`validate_document()` とテストも併せて更新すること。`run()` は両フェーズの間で `json.dumps`/`json.loads` を通すため、命令セットに直列化不能なオブジェクト（ifcopenshell エンティティや vs ハンドル等）を入れてはならない。

## パッケージ構造

```
src/
    vectorworks_plugin_import_ifc_homeskz/   # pip インストール可能なパッケージ本体
        __init__.py           # run() を公開 (ファイル選択 → 解析 → JSON 命令セット → 描画)
        document.py           # 命令セットのスキーマ定義・検証 (vs / ifcopenshell 非依存)
        ifc/                  # フェーズ1: IFC 解析 (vs 非依存)
            __init__.py       # build_document(ifc_file) -> dict
            loader.py         # open_ifc(path): 解析前にスキーマ非適合エンティティを除去して開く
            grid.py           # 通り芯 (IfcGridAxis) → grid 命令
            story.py          # ストーリ (IfcBuildingStorey) → story 命令
            member.py         # 横架材 (IfcBeam/IfcMember) → member 命令
            column.py         # 柱 (IfcColumn) → column 命令
            footing.py        # 基礎 (IfcFooting/IfcSlab) → wall/slab 命令・基礎ストーリ
            structural_class.py  # 柱・横架材の構造クラス判定 (クラス名定義・割り当てロジック)
        vw/                   # フェーズ2: VectorWorks 描画 (vs 依存)
            __init__.py       # execute_document(document) -> 実行数 dict
            grid.py           # grid 命令 → GridAxis オブジェクト
            story.py          # story 命令 → ストーリ・レベル・レイヤ
            member.py         # member 命令 → 構造材オブジェクト
            column.py         # column 命令 → 柱(構造材オブジェクト)
            footing.py        # wall 命令 → 壁オブジェクト・slab 命令 → スラブオブジェクト
main.py                      # VectorWorks から呼び出すラッパースクリプト (実行時に自動インストール・更新)
tests/                       # pytest 用テスト (CI は vs.py スタブを GitHub からダウンロード)
pyproject.toml               # パッケージメタデータ
```

`vs` を import してよいのは `vw` サブパッケージ内・`run()` 関数内・`main.py` の設定フォルダ検出（いずれも関数内の遅延 import）だけ。`ifc` サブパッケージや `document.py` に `vs` への依存を持ち込まないこと。テストもこの分離に従う: `tests/test_ifc_*.py`・`tests/test_document.py` は vs モック不要、`tests/test_vw_*.py` は手書きの命令セットを vs モックで実行して検証する。

## コーディング規約: 型注釈

すべての関数・メソッド（テストコード・モック用クロージャ含む）に引数と戻り値の型注釈を付ける。型検査は mypy で行い、CI で `mypy` を実行する（設定は `pyproject.toml` の `[tool.mypy]`、`disallow_untyped_defs` 有効）。

- 各モジュール先頭に `from __future__ import annotations` を置く。Python 3.9 互換を保ちつつ `list[str]` / `X | None` 構文を使うため。
- 命令セットの型は `document.py` の `TypedDict`（`Document` / `StoryCommand` / `GridCommand` / `MemberCommand` / `ColumnCommand` / `WallCommand` / `SlabCommand` / `LevelCommand` / `StoryBoundCommand`）を使う。`GridCommand` / `MemberCommand` / `ColumnCommand` / `WallCommand` / `SlabCommand` は `class` キー（構造クラス名）が予約語のため functional 構文で定義している。スキーマ変更時は `TypedDict` 定義・docstring・`validate_document()` を同時に更新すること。
- `ifc` サブパッケージでは ifcopenshell の型（`ifcopenshell.file` / `ifcopenshell.entity_instance`）を注釈にのみ使う場合 `if TYPE_CHECKING:` ブロックで import する。
- `vs` モジュールは型スタブが存在しないため `ignore_missing_imports` で許容し、vs ハンドルは `Any` で扱う。VectorWorks 公式 `vs.py` スタブ（`tests/vs.py`）は型検査対象から除外している。
- 検証前の命令セット（JSON 由来の信頼できない入力）を受ける関数（`validate_document()` / `execute_document()`）の引数は `Any` とし、検証済みの値だけを `Document` 型として扱う。

## スクリプトの実行方法

このスクリプトは単独の Python プログラムとして動作しません。**VectorWorks 内でプラグインスクリプトとして実行する必要があります**。`vs` モジュールは VectorWorks 独自の Python スクリプト API であり、pip でインストールすることはできません。

テストは VectorWorks の公式 `vs.py` スタブをモック対象として `pytest` で実行します（`.github/workflows/test.yml` 参照）。

## 外部ライブラリの利用方法

VectorWorks の組み込み Python は pip パッケージを標準では参照しませんが、Python Externals フォルダは VectorWorks が自動的に `sys.path` に追加します。このため以下の手順だけで外部ライブラリを利用できます。

1. `pip install --target <Python Externals フォルダ> .` でパッケージ（および依存ライブラリ）を Python Externals フォルダにインストールする。
2. VectorWorks から呼び出される `main.py`（ラッパー）が `vectorworks_plugin_import_ifc_homeskz.run()` を呼び出す。

Python Externals フォルダのパスは OS・VectorWorks のバージョンによって異なります（詳細は `README.md` 参照）。新しい外部ライブラリへの依存を追加するときは `pyproject.toml` の `[project] dependencies` に記載してください。

## IFC 解析の方針

IFC の解析には **`ifcopenshell`** を利用します。生の STEP テキストの正規表現マッチではなく、エンティティと属性を辿る形でデータを抽出します。

ただし**読み込み時のサニタイズ**は例外的にテキスト処理を行います（`ifc/loader.py` の `open_ifc`）。ホームズ君 EX の IFC2X3 出力には IFC4 でのみ定義される `IfcFootingType`（STEP の `IFCFOOTINGTYPE`）が混入しており、Python 3.9 で唯一解決される `ifcopenshell==0.8.4.post1` はこの不正エンティティにつまずいて周辺の正常な `IfcFooting`・`IfcSlab` まで取りこぼす（基礎が 1 件しか読めない）。`open_ifc` は**サニタイズが必要な古い ifcopenshell（バージョン < 0.8.5）の場合のみ**、解析前にスキーマ非適合のエンティティ行を除去してから `ifcopenshell.file.from_string` で開く。不具合が解消された 0.8.5 以降（Python 3.10+）では余計なテキスト処理を避け `ifcopenshell.open` に委ねる（バージョン判定は `_needs_sanitize`）。除去対象は基礎の型エンティティのみで、本スクリプトは `IfcFooting` の型を参照しないため抽出結果に影響しない。`run()` とテストのフィクスチャ読込はこの `open_ifc` を経由する。

## スクリプトの処理フロー

`vectorworks_plugin_import_ifc_homeskz.run()` は以下の順で処理を行います。

1. **ファイル選択** — `vs.GetFileN()` でファイルダイアログを開き `.ifc` を選択。
2. **IFC オープン** — `open_ifc(filepath)`（`ifc/loader.py`）でファイルを読み込む。解析前にスキーマ非適合のエンティティを除去する（基礎の取りこぼし防止、下記「IFC 解析の方針」参照）。
3. **解析（フェーズ1）** — `ifc.build_document(ifc_file)` で JSON 命令セットを組み立てる。
4. **JSON 経由の受け渡し** — `json.dumps` → `json.loads` を通し直列化可能性を保証。
5. **描画（フェーズ2）** — `vw.execute_document(document)` が検証後、ストーリ → 通り芯 → 構造材 → 柱 → 立上り（壁）→ 底盤/地中梁（スラブ）の順で描画し、最後にデザインレイヤのスタック順を `reorder_story_layers` で整えて実行数を返す。
6. **完了ダイアログ** — `vs.AlrtDialog` で結果を表示。

### 通り芯（ifc/grid.py → vw/grid.py）

- 解析: `IfcGridAxis` を走査し `AxisCurve`（`IfcPolyline`）の端点を取得。ソート済みタプルキーで同一ジオメトリの重複線を除去し、バウンディングボックスの中心 `(center_x, center_y)` でセンタリングした座標・レイヤ名・クラス名を grid 命令に格納。
- 描画: 各命令を `vs.CreateCustomObjectPath('GridAxis', ...)` で生成。失敗時は通常の線にフォールバック。レイヤ（`共通`）は存在しなければ作成。

### 横架材（ifc/member.py → vw/member.py）

- 解析: `IfcBeam` / `IfcMember` を走査し、配置・断面寸法・材種から member 命令（座標は通り芯と同じ中心オフセットで補正、構造材 ID は `{幅}×{背} - {材種}`）を組み立てる。一般階は `横架材天端` レイヤ、最上階は `軒高` レイヤを指定。軸（`Axis`）が鉛直な材は横架材でないためスキップする。
  - 基準点補正: ホームズ君 IFC の配置点（ローカル配置 Z）は**断面中心**だが、VW 構造材ツールの断面基準点は**左右中央・上端（天端中央）**。このため断面中心線を軸に直交し軸を含む鉛直面内で上向きの単位ベクトル方向に `背/2` 持ち上げた**天端中央線**を命令に格納する（水平梁では単純に Z + 背/2）。`elevation`／`end_elevation` は始端／終端の天端 Z（絶対値、`ストーリ高さ + ローカル Z + 補正`）。レイヤの基準高さに固定しないため、基準高さにない梁（段差のある梁等）も正しい高さに描画される。Z を取得できない梁のみレイヤ基準高さ（`ストーリ高さ + resolve_beam_top_offset`、最上階はストーリ高さ。いずれも既に天端なので背/2 補正なし）にフォールバックする。
  - 高さ基準のバインド（`start_bound`／`end_bound`）: 柱と同じく構造材ツールの始端／終端の高さ基準を配置先レイヤのストーリレベル（一般階は `横架材天端`、最上階は `軒高`）に `SetObjectStoryBound` でバインドする。横架材は自階のレベルに乗るため `story_offset=0`。`offset` は**バインド先レベルの絶対 Z から天端 Z（`elevation`／`end_elevation`）までの距離**（平らな梁は ≈0、段差梁は一定値、傾斜梁は始端／終端で異なる値）。これをしないと構造材ツールの高さ基準が `レイヤの高さ`・オフセット 0 のまま `Move3D` で動かした実ジオメトリと矛盾し、オブジェクト編集時に高さが 0 にリセットされてしまう。
  - 傾斜梁（登り梁・隅木・谷木等）: `Axis` 属性の Z 成分から始端・終端の高さ差を求め、`elevation ≠ end_elevation` の傾斜した命令にする。平面座標は軸の XY 成分 × 全長（= 平面投影長）で求める。
  - 食い込み調整（`resolve_member_interferences`）: 命令組み立て後、横架材同士が食い込んでいる箇所（甲乙梁の T 字や出隅の L 字の取り合い等）の端部を相手梁の面まで詰めて干渉を解消する。ある梁の端点が別の梁の矩形に入り（端部も含む）、配置レイヤが一致し Z 範囲（`[天端 - 背, 天端]`）が重なる場合が対象。**勝ち負けの判定**: 自分の端点が相手に食い込む量 `sAB` と、相手の端点が自分に食い込む量 `sBA` を比べ、`sAB > sBA + _SYMMETRY_TOL`（自分の方が深く食い込む＝相手が通し材で勝ち）のときだけ自分を詰める。相手梁の形状は変えず負け側だけを短くする。相互の食い込み量が同等な**対称の角**（同寸の出隅・火打等で端点が一致するケース）は勝ち負けが付かないため触らない。平行（同一直線上の継ぎ手）・Z が離れた段差梁・面ちょうどで止まる端部（既に勝ち負けが入った角）・傾斜梁（高さが一定でなく水平面内の矩形モデルが成り立たないため、詰める側にも相手側にもしない）は対象外。判定は入力時点のジオメトリに対して行い命令の並び順に依存しない。
- 描画: 構造材ツール `vs.CreateCustomObjectPath('StructuralMember', ...)` で配置（パスはローカル原点から作成し `Move3D` で始端天端の絶対位置へ移動）。傾斜梁は `elevation`/`end_elevation` の差分を Z 成分に持つ 3D パスとして描画する。配置後 `SetObjectStoryBound(obj, 0, 2, …)`（始端）・`SetObjectStoryBound(obj, 1, 2, …)`（終端、`boundType=2`=Story）で高さ基準を `start_bound`／`end_bound` のストーリレベルにバインドする（柱と同じ規約）。配置先レイヤが存在しない命令はスキップし、プラグインが使えない場合は通常線にフォールバック。

### 柱（ifc/column.py → vw/column.py）

**柱は梁と同じ構造材ツール（`StructuralMember`）で鉛直材として描く。** 拡張パッケージの柱・間柱ツール（`柱・間柱` / AAPillarS）はスクリプト操作に対して不安定なため、標準の構造材ツールに置き換えている。これにより伏図記号・柱頭/柱脚金物専用フィールドといった柱・間柱ツール固有機能は使えなくなるため、後述の通り扱いを変えている。構造材ツールの**構造用途は柱**（`StructuralUse='4'`）とし、高さ基準（柱頭/柱脚）は `SetObjectStoryBound` で**ストーリレベルにバインドする**。

- 解析: `IfcColumn` を走査し、配置・断面寸法（`IfcRectangleProfileDef` の `XDim`/`YDim`）・柱高さ（`IfcExtrudedAreaSolid.Depth`）から column 命令を組み立てる。XY 座標は通り芯と同じ中心オフセットで補正。柱は各階の柱レイヤ `n-柱`（命令の `layer`）に配置する。
- 高さ（上下端）: **ストーリレベルへのバインド**で描く（`resolve_height_bounds` が `start_bound`/`end_bound` を決定し、描画フェーズが `SetObjectStoryBound` を呼ぶ）。各 bound は `story_offset`（柱が乗るストーリ=レイヤのストーリからの相対階数、0=自階・1=上階）・`level`（そのストーリのレベル名）・`offset`（レベルからの距離 mm）を持つ。**`offset` は IFC の実ジオメトリから求める**: 柱端の絶対 Z（下端 `elevation`／上端 `elevation + height`）とバインド先レベルの絶対 Z（`beam_top_abs_z` = `ストーリ高さ + 横架材天端オフセット`、最上階は軒高＝ストーリ高さ）の差。これにより、ストーリ高さを VW 側で変えても柱端はレベルから一定距離を保ちつつ、インポート時は IFC 通りの長さで描かれる。一般階は**始端=自階の `横架材天端`**（`story_offset=0`）、**終端=上階の `横架材天端`**（`story_offset=1`）。最上階直下の階は上階が屋根で `横架材天端` が無いため終端=上階の `軒高`。標準的な柱は下端が自階天端に一致するため**始端 `offset≈0`**、上端は上階梁の下端（上階天端から**梁背分下**）になるため**終端 `offset≈ -梁背`（負値）**。最上階（屋根）の柱（小屋束等）は上階が無いため**始端・終端とも自階の `軒高`**（`story_offset=0`）を基準とし、終端は `軒高` から柱上端まで（おおむね柱高さ分）持ち上げる。`elevation`（柱下端の絶対 Z = `ストーリ高さ + ローカル配置 Z`）・`height`（柱高さ）・`position` はパスのジオメトリ（鉛直パスを `Move3D` で配置）に使い、最終的な上下端はストーリレベルのバインドで決まる。
- 構造材 ID（`member_id`）: `{幅}×{成} - {種別}` を基本とし、柱頭・柱脚金物の仕様（空でないもの）を ` / ` 区切りで連結する（`make_column_member_id`）。構造材ツールには金物専用フィールドが無いため、金物仕様は `MemberID` に含めて保持する。種別は `IfcColumn.ObjectType`（`None` または `STANDCOLUMN`）を `resolve_column_type` で変換した名前（`None`→`管柱`、`STANDCOLUMN`→`小屋束`、未知の値は `管柱`）。断面は現状すべて矩形。
- 柱頭・柱脚金物: ホームズ君 IFC では柱頭・柱脚金物が柱と同じストーリに含まれる `IfcMechanicalFastener`（柱頭/柱脚付近の立方体）として表現される。名前に `柱頭金物`／`柱脚金物` を含む金物を、柱と**同じ平面座標**（XY を丸めたキー）で柱に対応付け、金物の型 `IfcMechanicalFastenerType` の名前（例: `柱頭金物:(ろ)`・`柱頭金物:C12`）を**加工せずそのまま**仕様文字列として `top_hardware`／`bottom_hardware` に格納する（該当金物が無ければ空文字）。これらは構造化した記録として命令に個別保持しつつ、`member_id` にも連結して `MemberID` で保持する。ホームズ君側で金物定義をカスタマイズしている場合、型名が想定形式とは限らないため、コロン分割等の加工で文字列が失われる（空欄になる）のを避けて型名全体を登録する。型は IfcRelDefinesByType 経由で辿り、逆方向属性名がスキーマで異なる（IFC2X3=`IsDefinedBy`／IFC4=`IsTypedBy`）ため両方を走査する。
- 描画: 構造材ツール `vs.CreateCustomObjectPath('StructuralMember', path, profile)` で配置（梁の描画と同じ規約）。鉛直パスはローカル原点 `(0,0,0)` から `(0,0,height)` で作り、`Move3D` で柱下端の絶対位置（XY + `elevation`）へ移動する。続いて `SetObjectStoryBound(obj, 0, 2, …)`（始端）・`SetObjectStoryBound(obj, 1, 2, …)`（終端）で高さ基準をストーリレベルにバインドする（`boundType=2`=Story）。断面は `width`×`depth` の矩形プロファイル。構造用途は `StructuralUse='4'`（柱）。`MemberID` に `member_id` を格納し、その他のレコードフィールド（`ProfileShape`/`MajorBreadth`/`MajorDepth`/`B`/`D`/`MemberType` 等）は梁の構造材と同じ値を設定する。配置先レイヤが存在しない命令はスキップし、プラグインが使えない場合は断面の矩形にフォールバック。

### ストーリ（ifc/story.py → vw/story.py）

ホームズ君 IFC の高さ表現ルールを利用してストーリを構築します。

- 名前が `FL` で終わる `IfcBuildingStorey` のみを対象とする（`設計GL` 等の参照高は除外）。`IfcBuildingStorey.Elevation` がそのまま VectorWorks の**ストーリ高さ**になる（例: `1FL=473.0`, `2FL=3273.0`, `RFL=5973.0`）。
- 最上階以外の階では、`IfcRelContainedInSpatialStructure` を辿って `IfcColumn`・`IfcSlab` のローカル配置 Z 座標（負値、例: `-48.0`, `-36.0`）を集め、その**最大値**（床に最も近接した 0 以下の値）を**横架材天端**の相対オフセットとして使用します（エンティティ列挙順に依存しない決定的な結果にしつつ、床に最も近い横架材天端を採用するため）。
- ストーリ名は `1階`, `2階`, ..., `屋根`（最上階は常に `屋根`）。
- ストーリ suffix（前/後 記号）は `"1"`, `"2"`, ..., `"R"`（最上階は `R`）。空文字 suffix は VW 2026 で 2 回目以降の `CreateStory` が失敗するため不可。
- デザインレイヤ名は `1-FL`, `1-横架材天端`, `1-柱`, ..., `R-軒高`, `R-柱`（接頭辞はストーリ suffix と一致）。
- ストーリレベル: 一般階は `FL`(0) と `横架材天端`(負値)、最上階は `軒高`(0)。加えて全階に柱配置用の `柱` レベル（高さは `横架材天端`＝最上階は `軒高` に揃える）を持つ。柱は `n-柱` レイヤに梁と同じ構造材ツールで配置する（柱の上下端はバインド先レベル名で決まり、`柱` レベルのオフセットには依存しない）。`levels` の並び順は**希望するデザインレイヤのスタック順（上→下）**を表し、`n-柱` レイヤを `n-FL`（最上階は `R-軒高`）レイヤの直上に積むため `柱` レベルを先頭に置く。
  - レイヤのスタック順はレベルの高さに縛られず作成後に並べ替えできる（VW のナビゲーションで `#` 列をドラッグするのと同じ）。`AddLevelFromTemplate` はレイヤをレベルの高さ順に挿入するため、放置すると `柱`(横架材天端の高さ)が `FL` の下に入り、さらにストーリ間の並びも入り乱れる。これを描画フェーズ（`vw/story.py` の `reorder_story_layers`）が `HMoveForward(layer, False)` の 1 段ずつの移動で**全レイヤを 1 本の希望スタック順**（`desired_layer_order`）に揃える。希望順（ナビゲーション上→下）は **`共通`（通り芯）を最上段**に、続いて**最上階→最下階**の順に各ストーリのレイヤ（各階内は `levels` 順 = `柱` → `FL`/`軒高` → `横架材天端`）を並べたもの（例: `共通, R-柱, R-軒高, 2-柱, 2-FL, 2-横架材天端, 1-柱, 1-FL, 1-横架材天端`）。命令は Elevation 昇順（最下階→最上階）なので逆順に辿る。隣接ペアを末尾（下）から先頭（上）へ処理し、確定済みの下のペアを崩さずに上のペアを揃える。`共通` レイヤは通り芯描画フェーズで生成されるため、`reorder_story_layers` は `execute_stories` 内ではなく `execute_document` が**全描画（ストーリ→通り芯→構造材→柱）の後**に呼ぶ。まだ生成されていないレイヤ（通り芯が無い場合の `共通` 等）は `GetLayerByName` が NIL を返すため自動的にスキップされる。`HMoveForward`／`HMoveBackward` の第 2 引数 `toFront`／`toBack` を `True` にすると**レイヤが削除される**（公式ドキュメントの注意書き）ため、必ず `False` で 1 段ずつ移動する。レイヤ走査（`FLayer`→`NextLayer`）は下→上の順で、`NextLayer(anchor)` が対象レイヤになった時点（対象が anchor の直上）で停止する。

上記はすべて解析フェーズで決定され story 命令（`name`/`suffix`/`elevation`/`levels`）に格納される。描画フェーズはそれを実行するだけで判断ロジックを持たない。

VW 2026 でレイヤをストーリレベルに正しくバインドするには、`AddStoryLevelN` + `AssociateLayerWithStory` ではなく `CreateLevelTemplateN` + `AddLevelFromTemplate` の組み合わせを使う必要がある（前者ではバインドが UI 上 `<なし>` になる）。`create_story_level_via_template()` の処理順:

1. `vs.CreateLevelTemplateN(desired_layer_name, 1.0, level_type, elevation, wall_height)` — テンプレート登録（戻り値の index を保持）。第 5 引数の壁高さは生成されるデザインレイヤの壁高さ（壁オブジェクトの既定高さ）で、命令の `level['wall_height']`（無ければ `DEFAULT_WALL_HEIGHT=2400.0`）を渡す。基礎の立上りは壁オブジェクトのためこの値が実際の壁高に影響する（後述）。
2. `vs.AddLevelFromTemplate(story_handle, index)` — ストーリにレベル追加 & レイヤ自動生成 & バインド
3. `vs.GetLayerForStory(story_handle, level_type)` — 生成されたレイヤのハンドル取得
4. `vs.SetName(layer_h, desired_layer_name)` — `AddLevelFromTemplate` が末尾に付ける suffix（例: `1-FL-1`）を取り除いて意図した名前にリネーム

ストーリ作成順序: `CreateStory` → `SetStoryElevationN` を 1 ストーリ毎に実行してから次のストーリへ。`SetStoryElevation` を後回しにすると全ストーリが既定高さ 0 で衝突して 2 階以降の `CreateStory` が失敗する。

基礎要素が存在する場合、`build_document` は `ifc/footing.py` の `build_foundation_story_command` が返す **基礎ストーリ** を stories の**先頭**（最下層）に追加する（`build_story_commands` が返す FL 階は変更しない）。基礎ストーリは `name=基礎`・`suffix=F`・`elevation=0`（GL は常に 0）で、レベルは `GL`(0、`F-立上り` レイヤ) と `底盤天端`（底盤天端の絶対 Z、`F-底盤` レイヤ）の 2 つ。`levels` の並びは立上りを底盤の上に積むため `GL` を先頭にする。Elevation=0 で最下層になり、`reorder_story_layers` の希望スタック順（最上階→最下階）でも最下段に積まれるため、`1-横架材天端` の下に `F-立上り`・`F-底盤` が並ぶ。立上りは壁オブジェクトで描かれ、その配置先レイヤ（`F-立上り`）の壁高さが実際の壁高に影響するため、`GL` レベルには `wall_height`＝**底盤天端から 1 階床（1FL の Elevation）までの高さ**（`1FL Elevation − 底盤天端の絶対 Z`）を設定する。

### 基礎（ifc/footing.py → vw/footing.py）

ホームズ君 IFC の基礎要素（`IfcFooting` と基礎底盤の `IfcSlab`）を `Name` で 3 種に分類し、別オブジェクトに変換する。座標は通り芯・横架材と同じグリッド中心オフセットで補正する。配置先レイヤが存在しない命令はスキップする。

- **立上り（基礎梁、`Name` が `基礎梁` 始まり）→ 壁オブジェクト（wall 命令、`F-立上り` レイヤ）**。矩形断面の幅を壁厚、背を壁高とし、壁芯は配置原点から押し出し方向の線。下端は基礎（自階）の `GL`(`story_offset=0`)、上端は 1 階（上階）の `横架材天端`(`story_offset=1`)にバインドする。`offset` は実形状の下端/上端の絶対 Z とバインド先レベルの絶対 Z（1 階横架材天端 = `1FL Elevation + resolve_beam_top_offset(1FL)`）の差。描画は `vs.DoubLines`(壁厚)→`vs.Wall`(壁芯)→`SetObjectStoryBound`(下端=0/上端=1、`boundType=2`=Story)。壁が作れない場合は壁芯の直線にフォールバック。
- **底盤（基礎底盤・布基礎底盤・独立基礎底盤、`Name` に `底盤` を含む）→ スラブオブジェクト（slab 命令、`F-底盤` レイヤ）**。平面外形を底盤天端レベルにバインドし、`offset` は実天端 Z と底盤天端の絶対 Z の差（主たる底盤は ≈0）。
- **地中梁（地中梁・部分地中梁、`Name` に `地中梁` を含む）→ スラブオブジェクト（slab 命令、`F-底盤` レイヤ）**。底盤の下にぶら下がるため実形状どおり底盤天端より低い天端にバインドする（`offset` が負値）。これにより底盤スラブと噛み合う。
- 描画は外形ポリゴンを作り `vs.CreateSlab`(profile)→`vs.SetSlabHeight`(厚み)→`SetObjectStoryBound`(天端=0、`底盤天端`)。スラブが作れない場合は外形ポリゴンにフォールバック。
- **構造クラス**: 立上り=`04構造-01基礎-03立ち上がり`、底盤・地中梁=`04構造-01基礎-02基礎スラブ`。`SetClass` で設定する（存在しないクラスは VW が自動生成）。

**底盤天端レベルの高さ**（`resolve_slab_top_elevation`）は、底盤（`底盤` を含む要素）の天端 Z ごとに平面面積を合計し、合計面積が最大の天端 Z を採用する（例: 大半の基礎底盤の天端 50.0、独立基礎底盤など少数の異なる高さは採用されない）。エンティティ列挙順に依存しない決定的な高さにするため最初に見つかった値ではなく面積最大の Z を使う。

**押し出しソリッドのワールド変換**: 底盤は鉛直押し出し（プロファイルがそのまま平面外形）だが、立上り・地中梁・布基礎底盤は水平押し出し（プロファイルが鉛直面内）。`_world_solid` が要素配置とアイテム配置（`IfcExtrudedAreaSolid.Position`）を合成した行列でワールド座標に変換し、押し出し方向の Z 成分が鉛直か水平かで平面外形の求め方を分ける（鉛直＝プロファイル多角形、水平＝断面の水平幅を押し出し方向に掃引した矩形）。端部が他材で削られた要素は `IfcBooleanResult`（差演算）で表されるため、第 1 オペランドの素のソリッドを辿る（削り分だけ長めになるが取り逃すよりは妥当）。非矩形断面の立上りは壁厚が定まらないためスキップする。

## VectorWorks のレイヤとクラスの規則

- **通り芯のレイヤ**: すべて `共通` レイヤに配置。存在しない場合はスクリプトが自動作成。
- **通り芯のクラス**（X 通り・Y 通りの判定）:
  - 名前が `X` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-X通り`
  - 名前が `Y` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-Y通り`
  - それ以外: `|Δx| < |Δy|` の線（垂直に近い）を X 通り、それ以外を Y 通りとして扱う
- **GridAxis レコードフィールド**: `Label`（IFC から取得した軸名）、`ShowBubbleAt` = `"Start Point"`
- **構造材（柱・横架材）のクラス**（`ifc/structural_class.py`）: `04構造-02木造-…` 階層の葉クラス（番号 + 半角スペース + 名称を `-` で連結。例 `04構造-02木造-01土台-01土台`）を割り当てる。命令の `class` に格納し、描画フェーズ（`vw/member.py`・`vw/column.py`）が構造材オブジェクトに `vs.SetClass` で設定する（存在しないクラスは VW が自動生成）。判定方針:
  - **IFC 記録を信用する**: ホームズ君 IFC の `Name` には種別が埋め込まれる（`木梁:{種別}:{連番}` / `小屋束:…`、`STANDCOLUMN`）。横架材は `Name` 中央の種別トークンを `_MEMBER_CLASS_BY_TYPE` で直接クラスに対応付ける（`土台`→土台、`大引`→大引、`根太`→根太、`軒桁`→軒桁、`胴差`→胴差、`床小梁`/`床大梁`/`甲乙梁`→床梁、`小屋梁`→小屋梁、`母屋`→母屋、`棟木`→棟木）。柱は `ObjectType=STANDCOLUMN` または `Name` が `小屋束` 始まりなら小屋束。
  - **判別できないときは状況で推定する**（火打・隅木谷木・無名等）。横架材: 最下階=土台、中間階=床梁、最上階の軒高付近=小屋梁、軒高より高い（`above_eaves`＝天端が配置レイヤ高さを超える）=母屋。柱: 最上階の柱=小屋束、一般階は上下端の高さで判断し**上階の床（次階 FL）を貫けば通し柱、1 階分で止まれば管柱**（`is_through_column`、貫通判定の許容値 `THROUGH_COLUMN_TOL`）。
  - クラスは構造種別のみを表し、`member_id` の種別表記（柱の `管柱`/`小屋束` 等）とは独立。`member_id` は従来どおり `resolve_column_type`（通し柱を区別しない）で組み立てる。
- **基礎のクラス**（`ifc/footing.py`）: 立上り（壁）=`04構造-01基礎-03立ち上がり`、底盤・地中梁（スラブ）=`04構造-01基礎-02基礎スラブ`。命令の `class` に格納し、描画フェーズ（`vw/footing.py`）が `vs.SetClass` で設定する。

## 開発プロセス: PR 作成と監視

コード修正を実施する際は以下のプロセスに従う:

1. **PR作成の判断基準**:
   - コード編集後、ユーザーに確認すべき疑義が特にない場合は**自動的に PR を作成する**。
   - 迷いや未確定事項がある場合（変更方針をユーザーに確認中など）は、PR 作成を保留し先にユーザーに確認する。

2. **PR 作成後の対応**:
   - PR を作成したら `subscribe_pr_activity` で CI 結果とレビューコメントを監視する。
   - CI 失敗は原因を診断して修正コミットを自動的に push する。
   - レビューコメントは内容を確認し、軽微な修正は自動で追加コミットする。大きな変更・設計判断が必要な指摘はユーザーに確認してから対応する。
   - CI が全て green でレビュー上の問題もなければ**自動的にマージする**。

3. **コミットメッセージ**:
   - Claude セッション URL を追加する形式: `https://claude.ai/code/session_<SESSION_ID>`
