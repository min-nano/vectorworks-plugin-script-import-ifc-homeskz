# vectorworks_import_ifc_homeskz

**ホームズ君構造EX** から出力した木造軸組工法建築物の IFC ファイルを VectorWorks にインポートするプラグインスクリプトです。

## インストール

このリポジトリをクローンまたはダウンロードし、リポジトリのルートで以下を実行します。

**macOS**
```bash
pip install --target "$HOME/Library/Application Support/Vectorworks/2025/Python Externals" .
```

**Windows（コマンドプロンプト）**
```bat
pip install --target "%APPDATA%\Nemetschek\Vectorworks\2025\Python Externals" .
```

> VectorWorks のバージョンが異なる場合は `2025` の部分を実際のバージョン番号に置き換えてください。

Python Externals フォルダは VectorWorks が自動的に `sys.path` に追加するため、インストール後は追加の設定なしにパッケージを参照できます。

## VectorWorks へのスクリプト登録

VectorWorks のプラグインスクリプトとして以下のコードを登録してください（`inside_vsm.py` と同じ内容です）。

```python
import vw_import_ifc_homeskz
vw_import_ifc_homeskz.run()
```

## 使い方

スクリプトを実行するとファイルダイアログが開きます。ホームズ君構造EX から出力した `.ifc` ファイルを選択すると、通り芯が VectorWorks の `共同線` にインポートされます。

## 現在対応している要素

- グリッド線（通り芯）

## 今後対応予定の要素

- 柱・梁
- 筋交い・面材
