# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリについて

VectorWorks のプラグインスクリプト（`main.py` 単一ファイル）です。IFC（Industry Foundation Classes）形式の構造グリッドデータを読み込み、VectorWorks 上に通り芯オブジェクトとして描画します。日本の建築プロジェクト向けのユースケースを想定しています。

## スクリプトの実行方法

このスクリプトは単独の Python プログラムとして動作しません。**VectorWorks 内でプラグインスクリプトとして実行する必要があります**。`vs` モジュールは VectorWorks 独自の Python スクリプト API であり、pip でインストールすることはできません。

ビルド手順、テストスイート、リンター設定はいずれも存在しません。

## スクリプトの処理フロー

単一の関数 `import_ifc_grid_with_layers_and_classes()` が以下の 5 フェーズで実行されます。

1. **ファイル選択** — `vs.GetFileN()` でネイティブのファイルダイアログを開き、ユーザーが `.ifc` ファイルを選択します。
2. **IFC 解析** — ファイルをプレーンテキストとして読み込み、改行をすべて除去してから `;` でステートメントに分割します。3 種類の正規表現で以下を抽出します。
   - `IFCCARTESIANPOINT` → `points` 辞書（id → (x, y)）
   - `IFCPOLYLINE` → `polylines` 辞書（id → ポイント id のリスト）
   - `IFCGRIDAXIS` → `grid_axes` 辞書（id → {name, poly_id}）
3. **線の解決** — 各 `IFCGRIDAXIS` を `IFCPOLYLINE` 経由でエンドポイント座標に解決します。ソート済みタプルキーを使い、同一ジオメトリの重複線を除去します。座標センタリング用のバウンディングボックス中心も計算します。
4. **座標センタリング** — 全座標を `(center_x, center_y)` だけオフセットし、描画が VectorWorks の原点付近に収まるようにします。
5. **描画** — 各線を `vs.CreateCustomObjectPath()` で `GridAxis` カスタムオブジェクトとして生成します。生成に失敗した場合はフォールバックとして通常の線を描画します。

## VectorWorks のレイヤとクラスの規則

- **レイヤ**: すべてのオブジェクトを `共通` レイヤに配置します。存在しない場合はスクリプトが自動作成します。
- **クラス**（X 通り・Y 通りの判定）:
  - 名前が `X` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-X通り`
  - 名前が `Y` で始まる（大文字小文字不問）→ クラス `01作図-01線-01基準線-01通り芯-Y通り`
  - それ以外: `|Δx| < |Δy|` の線（垂直に近い）を X 通り、それ以外を Y 通りとして扱います
- **GridAxis レコードフィールド**: `Label`（IFC から取得した軸名）、`ShowBubbleAt` = `"Start Point"`

## 重要な設計上の制約：正規表現による IFC 解析

専用の IFC パーサー（`ifcopenshell` など）は**使用していません**。生の STEP 形式テキストに対して正規表現を適用しています。これにより以下の制限があります。

- 改行をすべて除去してから処理するため、複数行の IFC ステートメントにも対応しています。
- 抽出対象は `IFCCARTESIANPOINT`、`IFCPOLYLINE`、`IFCGRIDAXIS` の 3 エンティティのみです。その他の IFC ジオメトリは無視されます。
- `IFCCARTESIANPOINT` の正規表現は最初の 2 座標（x, y）のみを取得します。Z 値は無視されます。
- IFC ファイルが UTF-8 以外のエンコーディングの場合、`open(..., encoding='utf-8')` が例外を送出し、外側の `try/except` に捕捉されます。
