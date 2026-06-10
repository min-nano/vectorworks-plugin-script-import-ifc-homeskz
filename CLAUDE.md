# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリについて

**ホームズ君構造EX** から出力した木造軸組工法建築物の IFC ファイルをパースし、VectorWorks のオブジェクトに変換して配置することに特化した VectorWorks プラグインスクリプトです。

現在実装済みの機能は以下の通りです。

- グリッド線（通り芯）のインポート
- ストーリ・ストーリレベル・デザインレイヤの自動生成
- 横架材（土台・梁・桁）のインポート

今後以下の要素のインポートも追加する予定です。

- 柱
- 筋交い・面材

## アーキテクチャ: 2 フェーズ分離

処理は **IFC 解析フェーズ** と **VectorWorks 描画フェーズ** に完全分離されている。両フェーズは JSON 直列化可能な**命令セット（ドキュメント）**だけで接続され、`vs` との密結合を避けることで検証や VectorWorks バージョンアップ対応を容易にしている。

1. **IFC 解析フェーズ（`ifc` サブパッケージ）** — `vs` に一切依存しない。ifcopenshell で IFC を解析し、描くべきオブジェクトを命令セット（dict）として組み立てる。通常の Python 環境で単体実行・検証できる。
2. **描画フェーズ（`vw` サブパッケージ）** — `vs` だけに依存し、IFC・ifcopenshell の知識を持たない。命令セットを検証（`validate_document`）してから vs API で描画する。

命令セットのスキーマ（version・stories/grids/members 各命令の形式）は `document.py` の docstring に定義されている。スキーマを変更するときは `DOCUMENT_VERSION` の互換性に注意し、`validate_document()` とテストも併せて更新すること。`run()` は両フェーズの間で `json.dumps`/`json.loads` を通すため、命令セットに直列化不能なオブジェクト（ifcopenshell エンティティや vs ハンドル等）を入れてはならない。

## パッケージ構造

```
src/
    vectorworks_plugin_import_ifc_homeskz/   # pip インストール可能なパッケージ本体
        __init__.py           # run() を公開 (ファイル選択 → 解析 → JSON 命令セット → 描画)
        document.py           # 命令セットのスキーマ定義・検証 (vs / ifcopenshell 非依存)
        ifc/                  # フェーズ1: IFC 解析 (vs 非依存)
            __init__.py       # build_document(ifc_file) -> dict
            grid.py           # 通り芯 (IfcGridAxis) → grid 命令
            story.py          # ストーリ (IfcBuildingStorey) → story 命令
            member.py         # 横架材 (IfcBeam/IfcMember) → member 命令
        vw/                   # フェーズ2: VectorWorks 描画 (vs 依存)
            __init__.py       # execute_document(document) -> 実行数 dict
            grid.py           # grid 命令 → GridAxis オブジェクト
            story.py          # story 命令 → ストーリ・レベル・レイヤ
            member.py         # member 命令 → 構造材オブジェクト
main.py                      # VectorWorks から呼び出すラッパースクリプト
tests/                       # pytest 用テスト (CI は vs.py スタブを GitHub からダウンロード)
pyproject.toml               # パッケージメタデータ
```

`vs` を import してよいのは `vw` サブパッケージ内と `run()` 関数内（遅延 import）だけ。`ifc` サブパッケージや `document.py` に `vs` への依存を持ち込まないこと。テストもこの分離に従う: `tests/test_ifc_*.py`・`tests/test_document.py` は vs モック不要、`tests/test_vw_*.py` は手書きの命令セットを vs モックで実行して検証する。

## コーディング規約: 型注釈

すべての関数・メソッド（テストコード・モック用クロージャ含む）に引数と戻り値の型注釈を付ける。型検査は mypy で行い、CI で `mypy` を実行する（設定は `pyproject.toml` の `[tool.mypy]`、`disallow_untyped_defs` 有効）。

- 各モジュール先頭に `from __future__ import annotations` を置く。Python 3.9 互換を保ちつつ `list[str]` / `X | None` 構文を使うため。
- 命令セットの型は `document.py` の `TypedDict`（`Document` / `StoryCommand` / `GridCommand` / `MemberCommand` / `LevelCommand`）を使う。`GridCommand` は `class` キーが予約語のため functional 構文で定義している。スキーマ変更時は `TypedDict` 定義・docstring・`validate_document()` を同時に更新すること。
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

## スクリプトの処理フロー

`vectorworks_plugin_import_ifc_homeskz.run()` は以下の順で処理を行います。

1. **ファイル選択** — `vs.GetFileN()` でファイルダイアログを開き `.ifc` を選択。
2. **IFC オープン** — `ifcopenshell.open(filepath)` でファイルを読み込む。
3. **解析（フェーズ1）** — `ifc.build_document(ifc_file)` で JSON 命令セットを組み立てる。
4. **JSON 経由の受け渡し** — `json.dumps` → `json.loads` を通し直列化可能性を保証。
5. **描画（フェーズ2）** — `vw.execute_document(document)` が検証後、ストーリ → 通り芯 → 構造材の順で描画し実行数を返す。
6. **完了ダイアログ** — `vs.AlrtDialog` で結果を表示。

### 通り芯（ifc/grid.py → vw/grid.py）

- 解析: `IfcGridAxis` を走査し `AxisCurve`（`IfcPolyline`）の端点を取得。ソート済みタプルキーで同一ジオメトリの重複線を除去し、バウンディングボックスの中心 `(center_x, center_y)` でセンタリングした座標・レイヤ名・クラス名を grid 命令に格納。
- 描画: 各命令を `vs.CreateCustomObjectPath('GridAxis', ...)` で生成。失敗時は通常の線にフォールバック。レイヤ（`共通`）は存在しなければ作成。

### 横架材（ifc/member.py → vw/member.py）

- 解析: `IfcBeam` / `IfcMember` を走査し、配置・断面寸法・材種から member 命令（座標は通り芯と同じ中心オフセットで補正、構造材 ID は `{幅}×{背} - {材種}`）を組み立てる。一般階は `横架材天端` レイヤ、最上階は `軒高` レイヤを指定。
- 描画: 構造材ツール `vs.CreateCustomObjectPath('StructuralMember', ...)` で配置（パスはローカル原点から作成し `Move3D` で絶対位置へ移動）。配置先レイヤが存在しない命令はスキップし、プラグインが使えない場合は通常線にフォールバック。

### ストーリ（ifc/story.py → vw/story.py）

ホームズ君 IFC の高さ表現ルールを利用してストーリを構築します。

- 名前が `FL` で終わる `IfcBuildingStorey` のみを対象とする（`設計GL` 等の参照高は除外）。`IfcBuildingStorey.Elevation` がそのまま VectorWorks の**ストーリ高さ**になる（例: `1FL=473.0`, `2FL=3273.0`, `RFL=5973.0`）。
- 最上階以外の階では、`IfcRelContainedInSpatialStructure` を辿って `IfcColumn`・`IfcSlab` のローカル配置 Z 座標（負値、例: `-48.0`, `-36.0`）を集め、その**最小値**を**横架材天端**の相対オフセットとして使用します（エンティティ列挙順に依存しない決定的な結果にするため）。
- ストーリ名は `1階`, `2階`, ..., `屋根`（最上階は常に `屋根`）。
- ストーリ suffix（前/後 記号）は `"1"`, `"2"`, ..., `"R"`（最上階は `R`）。空文字 suffix は VW 2026 で 2 回目以降の `CreateStory` が失敗するため不可。
- デザインレイヤ名は `1-FL`, `1-横架材天端`, ..., `R-軒高`（接頭辞はストーリ suffix と一致）。
- ストーリレベル: 一般階は `FL`(0) と `横架材天端`(負値)、最上階は `軒高`(0) のみ。

上記はすべて解析フェーズで決定され story 命令（`name`/`suffix`/`elevation`/`levels`）に格納される。描画フェーズはそれを実行するだけで判断ロジックを持たない。

VW 2026 でレイヤをストーリレベルに正しくバインドするには、`AddStoryLevelN` + `AssociateLayerWithStory` ではなく `CreateLevelTemplateN` + `AddLevelFromTemplate` の組み合わせを使う必要がある（前者ではバインドが UI 上 `<なし>` になる）。`create_story_level_via_template()` の処理順:

1. `vs.CreateLevelTemplateN(desired_layer_name, 1.0, level_type, elevation, 2400.0)` — テンプレート登録（戻り値の index を保持）
2. `vs.AddLevelFromTemplate(story_handle, index)` — ストーリにレベル追加 & レイヤ自動生成 & バインド
3. `vs.GetLayerForStory(story_handle, level_type)` — 生成されたレイヤのハンドル取得
4. `vs.SetName(layer_h, desired_layer_name)` — `AddLevelFromTemplate` が末尾に付ける suffix（例: `1-FL-1`）を取り除いて意図した名前にリネーム

ストーリ作成順序: `CreateStory` → `SetStoryElevationN` を 1 ストーリ毎に実行してから次のストーリへ。`SetStoryElevation` を後回しにすると全ストーリが既定高さ 0 で衝突して 2 階以降の `CreateStory` が失敗する。

## VectorWorks のレイヤとクラスの規則

- **通り芯のレイヤ**: すべて `共通` レイヤに配置。存在しない場合はスクリプトが自動作成。
- **通り芯のクラス**（X 通り・Y 通りの判定）:
  - 名前が `X` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-X通り`
  - 名前が `Y` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-Y通り`
  - それ以外: `|Δx| < |Δy|` の線（垂直に近い）を X 通り、それ以外を Y 通りとして扱う
- **GridAxis レコードフィールド**: `Label`（IFC から取得した軸名）、`ShowBubbleAt` = `"Start Point"`
