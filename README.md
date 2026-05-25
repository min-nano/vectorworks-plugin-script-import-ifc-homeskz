# vw-import-ifc-homeskz

**ホームズ君構造EX** から出力した木造軸組工法建築物の IFC ファイルを VectorWorks にインポートするプラグインスクリプトです。

## インストール

### 1. パッケージを Python Externals フォルダにインストール

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

### 2. VectorWorks にラッパースクリプトを登録

VectorWorks のプラグインスクリプトとして以下のコードを登録してください。  
`main.py` の内容と同じです。

```python
import sys
import os

if sys.platform == 'darwin':
    _externals = os.path.join(
        os.path.expanduser('~'),
        'Library', 'Application Support', 'Vectorworks', '2025',
        'Python Externals',
    )
else:
    _externals = os.path.join(
        os.environ.get('APPDATA', ''),
        'Nemetschek', 'Vectorworks', '2025',
        'Python Externals',
    )

if _externals not in sys.path:
    sys.path.insert(0, _externals)

import vw_import_ifc_homeskz
vw_import_ifc_homeskz.run()
```

## 使い方

スクリプトを実行するとファイルダイアログが開きます。ホームズ君構造EX から出力した `.ifc` ファイルを選択すると、通り芯が VectorWorks の `共通` レイヤに配置されます。

## 現在対応している要素

- グリッド線（通り芯）

## 今後対応予定の要素

- 柱・梁
- 筋交い・面材
