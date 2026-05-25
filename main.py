import sys
import os

# Python Externals フォルダへのパスを sys.path に追加
# （パスは OS・VectorWorks のバージョンに合わせて変更してください）
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
