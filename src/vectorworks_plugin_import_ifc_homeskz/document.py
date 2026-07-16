"""JSON 命令セット(ドキュメント)のスキーマ定義と検証。

命令セットは IFC 解析フェーズ(``ifc`` パッケージ)が生成し、
描画フェーズ(``vw`` パッケージ)が消費する JSON 直列化可能な dict。
このモジュールは vs にも ifcopenshell にも依存しない。

スキーマ (version 28):

    {
        "version": 27,
        "stories": [
            {
                "name": "1階",            # VectorWorks のストーリ名
                "suffix": "1",            # CreateStory の suffix(非空必須)
                "elevation": 473.0,       # ストーリ高さ (mm)
                "levels": [
                    {
                        "type": "FL",         # ストーリレベルタイプ名
                        "offset": 0.0,        # ストーリ基準からのオフセット (mm)
                        "layer": "1-FL"       # 生成するデザインレイヤ名
                    }
                ]
            }
        ],
        "grids": [
            {
                "label": "X1",            # 通り芯の軸名
                "layer": "共通",           # 配置先デザインレイヤ名
                "class": "01作図-...",     # 割り当てるクラス名
                "start": [x1, y1],        # 始点 (mm, センタリング済み)
                "end": [x2, y2]           # 終点 (mm, センタリング済み)
            }
        ],
        "members": [
            {
                "layer": "1-横架材天端",   # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "member_id": "120×180 - 杉...",  # 構造材 ID
                "class": "04構造-...-土台",  # 割り当てるクラス名(構造種別)
                # start/end・elevation/end_elevation は断面の基準点
                # (左右中央・上端 = 天端中央)が通る線を表す。構造材ツールの
                # 断面基準点(左右中央・上端)にそのまま渡せる座標。
                "start": [x1, y1],        # 始点 (mm, センタリング済み)
                "end": [x2, y2],          # 終点 (mm, センタリング済み)
                "width": 120.0,           # 断面幅 (mm)
                "height": 180.0,          # 断面背 (mm)
                "elevation": 425.0,       # 始点の天端 Z 高さ (mm, 絶対値)
                "end_elevation": 425.0,   # 終点の天端 Z 高さ (mm, 絶対値)。
                                          # 始点と異なる場合は傾斜梁(登り梁・隅木等)
                # 高さ基準(ストーリレベルへのバインド)。柱と同じ仕組みで、
                # 構造材ツールの始端/終端の高さ基準を配置先レイヤのストーリレベル
                # (横架材天端、最上階は軒高)にバインドする。これにより高さ基準が
                # "レイヤの高さ" のまま offset 0 で実ジオメトリと矛盾する状態を避け、
                # 再描画/編集時に高さがリセットされないようにする。
                # story_offset は配置先ストーリからの相対階数(横架材は常に 0=自階)、
                # level はレベル名、offset はレベル絶対 Z から天端 Z までの距離 (mm)。
                # 平らな梁は offset≈0、段差梁は一定の offset、傾斜梁は始端/終端で
                # 異なる offset になる(elevation/end_elevation から算出)。
                "start_bound": {"story_offset": 0, "level": "横架材天端", "offset": 0.0},
                "end_bound": {"story_offset": 0, "level": "横架材天端", "offset": 0.0}
            }
        ],
        "rafters": [
            {
                # 垂木。屋根版(IfcSlab の屋根面)の勾配・外形から導出し、軸組ツール
                # (FramingMember、type='rafter')で描く。IFC に垂木は出力されない
                # ため、屋根版 1 面ごとに勾配方向(母屋・棟木に直交する最急勾配方向)
                # へ 455mm 間隔で流し、面の外形(軒側〜棟側)でクリップした 1 本ずつを
                # 命令にする。断面は既定 45×45(IFC に垂木寸法が無いため決め打ち)。
                # 配置先は母屋レイヤの直上に独立させた 垂木 レイヤ(n-垂木)。
                "layer": "R-垂木",         # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "class": "04構造-02木造-05小屋組-05垂木",  # 割り当てるクラス名
                "width": 45.0,            # 断面幅 (mm)
                "height": 45.0,           # 断面せい (mm)
                # start=軒側(低い端)・end=棟側(高い端)の平面座標(mm・センタリング
                # 済み)。描画フェーズはこの 2 点と両端の天端 Z から水平投影長
                # (LineLength)・平面方位角・勾配(pitch)を求めて FramingMember に渡す。
                "start": [x1, y1],
                "end": [x2, y2],
                "elevation": 6060.0,      # 軒側(start)の天端 Z 高さ (mm, 絶対値)
                "end_elevation": 7756.0   # 棟側(end)の天端 Z 高さ (mm, 絶対値)
            }
        ],
        "columns": [
            {
                # 柱は梁と同じ構造材ツール (StructuralMember) で鉛直材として描く。
                "layer": "1-柱",          # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                # 構造材 ID。"{幅}×{成} - {種別}" に柱頭・柱脚金物の仕様を
                # 連結した文字列(StructuralMember の MemberID に格納する。
                # 構造材ツールには金物専用フィールドが無いため、金物仕様は
                # MemberID に含めて保持する)。
                "member_id": "105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(ろ)",
                "class": "04構造-...-管柱",  # 割り当てるクラス名(柱種別)
                # 構造材ツールの構造用途 (StructuralUse) 値。管柱・通し柱は柱
                # ("4")、小屋束は小屋束 ("5") を設定する。小屋束を柱として描くと
                # VW が柱の高さモデルを適用し、上端の高さオフセットと部材長が
                # 矛盾して上端高さが正しく描画されない。小屋束用途に切り替えると
                # 実ジオメトリどおりの高さで描かれる。
                "structural_use": "4",    # "4"=柱 / "5"=小屋束
                "position": [x, y],       # 配置 XY (mm, センタリング済み)
                "width": 105.0,           # 断面幅 (mm)
                "depth": 105.0,           # 断面成 (mm)
                # 柱の上端はパスのジオメトリ(elevation + height)で決まる。
                # 構造材ツールの高さバインド(SetObjectStoryBound)は鉛直材では
                # パス由来の部材長に加算され上端が二重になるため使わない。よって
                # 柱命令は高さ基準(start_bound/end_bound)を持たない。
                "height": 2844.0,         # 柱高さ (mm, 鉛直パス長 = 上端 − 下端)
                "elevation": 426.0,       # 柱下端の Z 高さ (mm, 絶対値)
                # 柱頭・柱脚金物の仕様文字列(該当金物が無ければ "")。member_id
                # にも連結されるが、構造化された記録として個別にも保持する。
                "top_hardware": "柱頭金物:(ろ)",    # 柱頭金物の仕様
                "bottom_hardware": "柱脚金物:(ろ)"  # 柱脚金物の仕様
            }
        ],
        "walls": [
            {
                # 基礎の立上り(基礎梁、IfcFooting)。壁オブジェクトで描く。
                "layer": "F-立上り",       # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "class": "04構造-01基礎-03立ち上がり",  # 割り当てるクラス名
                "start": [x1, y1],        # 壁芯の始点 (mm, センタリング済み)
                "end": [x2, y2],          # 壁芯の終点 (mm, センタリング済み)
                "thickness": 120.0,       # 壁厚 (mm)
                # 高さ基準(ストーリレベルへのバインド)。下端は基礎(自階)の GL、
                # 上端は 1 階(上階)の横架材天端にバインドする。offset は IFC 実形状
                # (壁の下端/上端の絶対 Z)とバインド先レベルの絶対 Z の差。
                # 描画フェーズは壁専用の SetWallOverallHeights でこれをバインドする
                # (汎用の SetObjectStoryBound では壁がレイヤの Default Wall Height に
                # 従ってしまうため)。
                "bottom_bound": {"story_offset": 0, "level": "GL", "offset": -100.0},
                "top_bound": {"story_offset": 1, "level": "横架材天端", "offset": -190.0}
            }
        ],
        "wall_joins": [
            {
                # 交差する立上り(壁)同士を VW の壁結合(JoinWalls)で結合する命令。
                # a・b は結合する 2 つの壁の walls 内インデックス。描画フェーズは
                # walls を描くときに命令インデックスをキーに壁ハンドルを記録し、
                # a・b でその壁を引いて JoinWalls に渡す。
                "a": 0,                   # 1 本目(T 結合ではこちらが延長される側=stem)
                "b": 1,                   # 2 本目(T 結合ではこちらが通し側=through)
                # 結合位置(2 壁の壁芯の交点、mm・センタリング済み)。参照用。
                "point": [0.0, 0.0],
                # JoinWalls に渡すピック点(a・b それぞれの壁上の点)。壁芯の交点
                # そのものではなく、各壁の「残す側」(交点から遠い端点方向)へ寄せた
                # 点にする(交点は相手壁の壁芯上にも乗り残す側が曖昧になるため。
                # これがないと VW が L 結合でコーナーを詰めず立上りが伸びたまま残る)。
                "pick_a": [30.0, 0.0],
                "pick_b": [0.0, 30.0],
                # 結合種別(JoinWalls の joinModifier)。1=T 結合・2=L 結合・
                # 3=X 結合。両壁の端点/内部のどちらで交わるかで解析フェーズが判定する
                # (両端点=L、片端点+片内部=T、両内部=X)。
                "join_type": 2,
                # JoinWalls の capped 引数(結合部を閉じるか)。天端高さの異なる
                # 立上りは低いほうを高いほうに結合して閉じる(capped=True)。同じ
                # 天端高さはコンクリート一体のため閉じない(capped=False)。
                "capped": False
            }
        ],
        "slabs": [
            {
                # 基礎の底盤・地中梁(IfcSlab/IfcFooting)。スラブオブジェクトで描く。
                "layer": "F-底盤",         # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "class": "04構造-01基礎-02基礎スラブ",  # 割り当てるクラス名
                # スラブ外形(平面ポリゴンの頂点列、mm・センタリング済み)。
                "boundary": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
                # スラブ天端の絶対 Z (mm)。描画フェーズが SetSlabHeight でスラブの
                # 天端高さとして設定する。SetSlabHeight は厚みではなく高さ
                # (Coordinate) を設定するため、厚みを渡すと天端が厚み分だけ高く
                # 描画される(柱・梁の高さ二重加算と同種の不具合)。
                "elevation": 50.0,
                # スラブスタイルのコンクリート厚 (mm)。底盤(基礎底盤系)にだけ
                # 設定し、描画フェーズが「基礎スラブ - コンクリート {厚}mm / …」の
                # スラブスタイルを適用する(既定=150mm はそのまま、それ以外は既定
                # スタイルを複製してコンクリート厚を変更する)。地中梁など、スラブ
                # スタイルを適用しないスラブは None(スタイル無し、実厚はスタイルの
                # コンポーネントには依存しない)。
                "thickness": 150.0,
                # 高さ基準(ストーリレベルへのバインド)。スラブ天端を基礎の底盤天端
                # レベルにバインドする。offset は天端の絶対 Z と底盤天端の絶対 Z の差
                # (主たる底盤は ≈0、地中梁は底盤天端より低いため負値)。
                "bound": {"story_offset": 0, "level": "底盤天端", "offset": 0.0}
            }
        ],
        "floors": [
            {
                # 床板(IfcSlab "床版")を床ツール(Floor オブジェクト)で描く命令。
                # 各階の FL レイヤに配置する。厚みは 24mm 固定、床下端が横架材天端に
                # なるようにする(高さは IFC に厚み情報しか無く、床下端=横架材天端の
                # 要件により決める)。
                "layer": "1-FL",          # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "class": "04構造-02木造-06耐力面材-02床",  # 割り当てるクラス名
                # 床の平面外形(平面ポリゴンの頂点列、mm・センタリング済み)。
                "boundary": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
                "thickness": 24.0,        # 床厚 (mm、固定値 24)
                # 床下端の絶対 Z (mm)。横架材天端(= ストーリ高さ + 横架材天端
                # オフセット)に一致する。描画フェーズはこの Z を床下端として床を
                # 配置する。
                "elevation": 425.0,
                # 高さ基準(ストーリレベルへのバインド)。床下端を配置先ストーリの
                # 横架材天端レベルにバインドする(構造材・スラブと同じ規約。offset は
                # 床下端が横架材天端ちょうどのため 0)。
                "bound": {"story_offset": 0, "level": "横架材天端", "offset": 0.0}
            }
        ],
        "anchor_bolts": [
            {
                # アンカーボルト (IfcMechanicalFastener) をハイブリッドシンボルに
                # 置換して配置する命令。座金付き (Z1/Z2 等) は アンカーボルト_M12、
                # 座金なしは アンカーボルト_M16 のシンボルにする。
                "layer": "F-アンカーボルト",   # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "symbol": "アンカーボルト_M12",  # 置換するハイブリッドシンボル名
                # 2D 基準位置はアンカーボルトの軸芯 (XY, mm・センタリング済み)。
                # 高さの基準は基礎天端で、配置先レイヤ (F-アンカーボルト) の
                # ストーリレベル (基礎天端) が担うため命令に高さ情報は持たせない。
                "position": [x, y]
            }
        ],
        "floor_posts": [
            {
                # 床束(IFC に出力されないため大引の下に 910mm 間隔で決め打ち配置)を
                # ハイブリッドシンボル "床束" に置換して基礎ストーリの F-床束 レイヤに
                # 配置する命令。
                "layer": "F-床束",         # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "symbol": "床束",          # 置換するハイブリッドシンボル名
                # 2D 基準位置は大引芯線に沿った床束位置(910mm 間隔、mm・センタリング
                # 済み)。高さの基準は基礎底盤上端(底盤天端)で、配置先レイヤ
                # (F-床束)のストーリレベル(床束=底盤天端に揃える)が担うため
                # 命令に高さ情報は持たせない。
                "position": [x, y]
            }
        ],
        "fire_braces": [
            {
                # 火打(火打梁、IfcBeam/IfcMember の "火打:…")をハイブリッド
                # シンボル "鋼製火打" に置換して横架材レイヤに配置する命令。
                "layer": "2-横架材天端",   # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                "symbol": "鋼製火打",       # 置換するハイブリッドシンボル名
                # 2D 基準位置は横架材接合部の内側面交点(火打が取り付く 2 梁の
                # 面が幾何学的に交わる内角の点、mm・センタリング済み)。高さの基準は
                # 配置先レイヤ(横架材天端 / 最上階は軒高)のストーリレベルが担う。
                "position": [x, y],
                # 火打の向きに合わせた回転角(度)。基準点(内角)から火打本体の
                # 重心へ向かう方向(内角の二等分方向)に、シンボルの基準姿勢の
                # ずれを補正する反時計方向 45 度を加えた値。
                "angle": 0.0
            }
        ],
        "sheets": [
            {
                # シートレイヤとビューポートを生成する命令。特定のデザインレイヤ群を
                # 表示するビューポートを配置した 1 枚のシートを作る(例: 基礎伏図)。
                "number": "1",           # シートレイヤ番号
                "title": "基礎伏図",      # シートレイヤタイトル
                "viewport": {
                    "drawing_title": "基礎伏図",  # ビューポートの図面タイトル
                    "drawing_number": "1",        # ビューポートの図番
                    # ビューポートに表示するデザインレイヤ名。ここに挙げたレイヤだけを
                    # 表示し、それ以外のデザインレイヤは非表示にする。
                    "layers": ["F-底盤", "F-立上り", "F-アンカーボルト", "共通"],
                    # このビューポートで非表示にするクラス名(省略可)。表示レイヤに
                    # 乗っていても、ここに挙げたクラスの図形だけは非表示にする
                    # (例: 基礎伏図では配筋クラスを隠し、断面でのみ表示する)。
                    "hidden_classes": ["04構造-01基礎-04配筋"]
                }
            }
        ],
        "tags": [
            {
                # 横架材の断面寸法を表示するデータタグを、床伏図・小屋伏図の
                # ビューポート注釈として配置する命令。VW の「断面寸法」データタグ
                # スタイルを関連付け、対象の横架材(members[member_index])に
                # 関連付けて断面寸法(120×180 等)を表示する。
                "style": "断面寸法",     # 適用するデータタグスタイル名
                "layer": "1-横架材天端",  # 関連付け先横架材の配置レイヤ。この
                                          # レイヤを表示するビューポート(=その階の
                                          # 床/小屋伏図)の注釈にタグを置く。
                "member_index": 0,        # 関連付け先横架材の members 内インデックス
                # タグの挿入位置(mm・センタリング済み)。横架材の軸中央から軸に
                # 直交する「上または左」方向へ断面幅/2 だけオフセットした部材の辺の
                # 中央(左右に伸びる梁は上辺中央、上下に伸びる梁は左辺中央)。
                # ここにデータタグの下端中央が来る。面ちょうどに置くため引き出し線は出ない。
                "position": [1500.0, 60.0],
                "angle": 0.0              # 横架材の軸方向に沿った文字角度 (度)
            }
        ],
        "column_marks": [
            {
                # 各階の伏図に直下階(N-1)の柱を記号化する「下階柱記号」。
                # カスタム PIO「柱束伏図記号」(姉妹プロジェクト
                # vectorworks-plugin-column-under-mark)を配置する命令。PIO は
                # リセット時に target_layer の構造用途 4/5 の構造材を検索し、柱は ×・
                # 小屋束は ○ の記号を各位置に描く(柱が編集されれば記号も追随する)。
                # 柱(×)と束(○)を別オブジェクトに分けて描画設定を独立調整するため、
                # 下階柱記号は 1 階分につき管柱クラスと小屋束クラスの 2 つに分ける
                # (通し柱には記号を付けない)。これは管柱(×)を記号化する PIO。
                "layer": "2-下階柱",       # PIO を配置するデザインレイヤ名
                                          # (横架材天端の直上・既存のみ・なければスキップ)
                "class": "01作図-04記号-04構造-一般",  # PIO 本体(記号)を作図するクラス
                "target_layer": "1-柱",    # PIO が柱を検索する対象レイヤ(直下階の柱レイヤ)
                "target_class": "04構造-02木造-03柱-02管柱",  # 管柱クラスに絞る(×)
                "size": 300.0,            # 記号サイズ (mm)。PIO の MarkSize に渡す。
                # PIO の挿入点(センタリング済み)。記号は検索した柱のワールド位置に
                # 描かれ挿入点には依存しないため原点でよい。
                "position": [0.0, 0.0]
            },
            {
                # 同じ 2-下階柱 レイヤに、直下階に架かる下屋根(下屋)の小屋束を
                # 記号化する PIO(小屋束クラスに絞る)。柱(×)とは別オブジェクト。
                "layer": "2-下階柱",
                "class": "01作図-04記号-04構造-一般",
                "target_layer": "1-柱",
                "target_class": "04構造-02木造-05小屋組-02小屋束",  # 小屋束クラスに絞る(○)
                "size": 300.0,
                "position": [0.0, 0.0]
            },
            {
                # 母屋伏図に最上階(屋根)の小屋束を記号化する「小屋束記号」。
                # 屋根の柱レイヤ(R-柱)を検索対象にし、検索対象クラスを小屋束クラスに
                # 絞ることで小屋束(○)だけを記号化する(柱の下階柱記号とはクラスで
                # 分けた別オブジェクト)。
                "layer": "R-小屋束",      # PIO を配置するデザインレイヤ名(母屋の直上)
                "class": "01作図-04記号-04構造-一般",  # PIO 本体(記号)を作図するクラス
                "target_layer": "R-柱",   # PIO が小屋束を検索する対象レイヤ
                "target_class": "04構造-02木造-05小屋組-02小屋束",  # 小屋束クラスに絞る
                "size": 300.0,
                "position": [0.0, 0.0]
            }
        ],
        "legends": [
            {
                # シートレイヤ上にグラフィック凡例(VW 標準の「グラフィック凡例」
                # PIO)を配置する命令。基礎伏図ビューポートに表示されるシンボル
                # (既定ではアンカーボルト)の凡例を表す。凡例の対象シンボルと
                # 表示ラベルは items に持たせる(ラベルはコード内の固定マッピング)。
                # グラフィック凡例のデータソース(基礎伏図ビューポート)・行ごとの
                # ラベルテキストの詳細設定は VW 上で最終調整する(PIO の設定 API が
                # 未公開のため。描画フェーズは他要素と同じく VW 上で検証する方針)。
                "number": "1",            # 配置先シートレイヤ番号(基礎伏図=1)
                "position": [0.0, 0.0],   # シートレイヤ上の配置点 (mm)
                "items": [
                    # 凡例に並べるシンボルと表示ラベル(並び順どおりに表示する)。
                    {"symbol": "アンカーボルト_M12", "label": "土台用アンカーボルトM12"},
                    {"symbol": "アンカーボルト_M16", "label": "ホールダウン用アンカーボルトM16"}
                ]
            }
        ],
        "rebars": [
            {
                # 基礎の配筋。カスタム PIO「鉄筋」(姉妹プロジェクト
                # vectorworks-plugin-rebar)を 3D パス図形として配置する命令。
                # PIO は path(3D パス)とパラメータ(モード・鉄筋仕様)から平面線・
                # 3D 鉄筋・断面 2D コンポーネントを自前で描く(本リポジトリは PIO の
                # 配置とパラメータ設定までを担い、配筋の描画ロジックは持たない)。
                # 立上り(基礎梁)・地中梁は梁モード(mode="beam")、底盤はスラブ
                # モード(mode="slab")。配筋仕様は IFC の Pset_Reinforcement から
                # 取得し、無ければ既定値(立上り・地中梁=上下 1-D13・せん断 D10@250、
                # 底盤=D13@150 シングル両方向)を使う。
                "layer": "F-立上り",       # 配置先デザインレイヤ名(既存のみ・なければスキップ)
                                          # 立上り=F-立上り、地中梁・底盤=F-底盤
                "class": "04構造-01基礎-04配筋",  # PIO 本体の描画クラス(PIO は全図形をこのクラスで描く)
                "mode": "beam",           # "beam"=梁モード / "slab"=スラブモード
                # PIO の 3D パス頂点(mm・センタリング済み・絶対 Z)。梁モードは
                # 梁天端の中心線(開いた 2 点以上)、スラブモードは底盤天端の外形
                # (閉じた 3 点以上)。PIO はこの Z を天端として断面を下方向に取る。
                "closed": False,          # パスを閉じるか(スラブ=True、梁=False)
                "path": [[0.0, 0.0, 400.0], [3000.0, 0.0, 400.0]],
                # 梁モード (mode="beam") の配筋仕様。PIO の SectionSize/TopBars/
                # BottomBars/Stirrup パラメータに渡す。スラブモードでは空文字。
                "section_size": "120×500",  # 断面(壁厚×壁高、mm)
                "top_bars": "1-D13",        # 上端筋
                "bottom_bars": "1-D13",     # 下端筋
                "stirrup": "D10@250",       # せん断補強筋(あばら筋)
                # スラブモード (mode="slab") の配筋仕様。PIO の MainBar/DistBar/
                # SlabThickness パラメータに渡す(シングル配筋・両方向)。梁モードでは
                # main_bar/dist_bar は空文字、slab_thickness は 0。
                "main_bar": "",             # 主筋(D13@150 形式)
                "dist_bar": "",             # 配力筋(D13@150 形式、主筋に直交)
                "slab_thickness": 0.0       # スラブ厚 (mm)
            }
        ]
    }
"""
from __future__ import annotations

import json
from typing import Any, Optional, TypedDict

DOCUMENT_VERSION = 28


class LevelCommand(TypedDict):
    """story 命令内の 1 ストーリレベル。"""

    type: str
    offset: float
    layer: str


class StoryCommand(TypedDict):
    """ストーリ・ストーリレベル・デザインレイヤを生成する命令。"""

    name: str
    suffix: str
    elevation: float
    # levels の並び順は希望するデザインレイヤのスタック順(上→下)。柱レイヤを
    # FL(最上階は軒高)レイヤの直上に置くため柱レベルを先頭にする。描画フェーズが
    # HMoveForward でこの順序どおりにレイヤを並べ替える(レベルの高さには依存しない)。
    levels: list[LevelCommand]


# 'class' キーが Python の予約語のため functional 構文で定義する
GridCommand = TypedDict('GridCommand', {
    'label': str,
    'layer': str,
    'class': str,
    'start': list[float],
    'end': list[float],
})
"""通り芯 (GridAxis オブジェクト) を描画する命令。"""


class StoryBoundCommand(TypedDict):
    """高さ基準(ストーリレベルへのバインド)1 端分。

    柱・横架材の構造材ツールの始端/終端の高さ基準に使う。story_offset は
    構造材が乗るストーリ(=レイヤのストーリ)からの相対階数(0=自階、1=上階)、
    level はそのストーリのレベル名(横架材天端 / 軒高)、offset はレベルからの
    距離 (mm)。SetObjectStoryBound に渡す。
    """

    story_offset: int
    level: str
    offset: float


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
MemberCommand = TypedDict('MemberCommand', {
    'layer': str,
    'member_id': str,
    'class': str,
    'start': list[float],
    'end': list[float],
    'width': float,
    'height': float,
    'elevation': float,
    'end_elevation': float,
    'start_bound': StoryBoundCommand,
    'end_bound': StoryBoundCommand,
})
"""構造材 (StructuralMember オブジェクト) を描画する命令。

start/end と elevation/end_elevation は断面の基準点(左右中央・上端 = 天端中央)が
通る線を表す。elevation と end_elevation が異なる場合は傾斜梁(登り梁・隅木等)。
start_bound / end_bound は始端/終端の高さ基準を配置先レイヤのストーリレベル
(横架材天端、最上階は軒高)にバインドする。class は割り当てる構造種別クラス名。
"""


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
RafterCommand = TypedDict('RafterCommand', {
    'layer': str,
    'class': str,
    'width': float,
    'height': float,
    'start': list[float],
    'end': list[float],
    'elevation': float,
    'end_elevation': float,
})
"""垂木 (FramingMember オブジェクト、type='rafter') を描画する命令。

屋根版(IfcSlab の屋根面)の勾配・外形から導出する。start=軒側(低い端)・
end=棟側(高い端)の平面座標、elevation/end_elevation はそれぞれの天端 Z(絶対値)。
描画フェーズはこの 2 点と両端 Z から水平投影長・平面方位角・勾配(pitch)を求めて
軸組ツールに渡す。width×height は断面(既定 45×45)。class は割り当てる構造クラス名
(小屋組-垂木)。配置先レイヤ(layer)は母屋レイヤの直上に独立させた n-垂木。
"""


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
ColumnCommand = TypedDict('ColumnCommand', {
    'layer': str,
    'member_id': str,
    'class': str,
    'structural_use': str,
    'position': list[float],
    'width': float,
    'depth': float,
    'height': float,
    'elevation': float,
    'top_hardware': str,
    'bottom_hardware': str,
})
"""柱 (StructuralMember オブジェクト) を鉛直材として描画する命令。

柱は梁と同じ構造材ツールで描く。下端 (elevation) から高さ (height) 分の鉛直パスを
持ち、断面は width×depth。member_id は構造材 ID で、柱頭・柱脚金物の仕様も連結して
保持する(構造材ツールに金物専用フィールドが無いため)。class は割り当てる柱種別
クラス名。structural_use は構造材ツールの構造用途 (StructuralUse) 値で、管柱・通し柱は
"4"(柱)、小屋束は "5"(小屋束)。小屋束を柱用途にすると VW の柱高さモデルで上端
高さが崩れるため小屋束用途にする。柱の上端はパスのジオメトリ(elevation + height)で
決まり、ストーリレベルへの高さバインドは使わない(鉛直材ではバインドの高さが
パス由来の部材長に加算され上端が二重になるため)。position・elevation・height は
パスのジオメトリ(XY と下端 Z・長さ)に使う。
"""


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
WallCommand = TypedDict('WallCommand', {
    'layer': str,
    'class': str,
    'start': list[float],
    'end': list[float],
    'thickness': float,
    'bottom_bound': StoryBoundCommand,
    'top_bound': StoryBoundCommand,
})
"""基礎の立上り(基礎梁)を壁オブジェクトで描画する命令。

start/end は壁芯、thickness は壁厚。bottom_bound / top_bound は壁の下端/上端の
高さ基準で、下端は基礎(自階)の GL、上端は 1 階(上階)の横架材天端にバインドする。
class は割り当てる構造クラス名(立ち上がり)。
"""


class WallJoinCommand(TypedDict):
    """交差する立上り(壁)同士を VW の壁結合(JoinWalls)で結合する命令。

    ``a`` / ``b`` は結合する 2 つの壁の walls 内インデックス。描画フェーズは
    walls を描くときに命令インデックスをキーに壁ハンドルを記録し、``a`` / ``b`` で
    その壁を引いて JoinWalls に渡す(タグの member_index と同じ受け渡し方式)。
    ``point`` は 2 壁の壁芯の交点(mm・センタリング済み)で、参照用に保持する。

    ``pick_a`` / ``pick_b`` は JoinWalls に渡すピック点(``a`` / ``b`` それぞれの壁上の
    点、mm・センタリング済み)。**壁芯の交点そのものではなく、各壁の「残す側」(交点
    から遠い端点の方向)へ寄せた点**にする。交点は両壁芯の交点で相手壁の壁芯上にも
    乗るため「どちら側を残すか」が曖昧になり、VW が L 結合でコーナーを詰めず立上りが
    相手壁の外面まで伸びたまま残る。残す側へ控えめに寄せることで残す区間を明示しつつ、
    詰める端点(近い側)が最も近い端点のまま保たれる。``join_type`` は JoinWalls の
    joinModifier(1=T 結合・2=L 結合・3=X 結合)で、両壁が端点同士で交われば L、
    片方の端点と他方の内部で交われば T(``a`` を延長される stem、``b`` を通し
    through にする)、両方の内部で交われば X と解析フェーズが判定する。

    ``capped`` は JoinWalls の capped 引数(結合部を閉じるか)。天端高さの異なる
    立上り同士は低いほうを高いほうに結合して端部を閉じる(``a``=低い壁・
    ``capped=True``)。同じ天端高さの立上り同士はコンクリートで一体のため閉じない
    (``capped=False``)。3 本以上が集まる交点では天端が最も高い立上り同士を
    ``capped=False`` で先に繋ぎ、それより低い立上りを ``capped=True`` で繋ぐ。
    """

    a: int
    b: int
    point: list[float]
    pick_a: list[float]
    pick_b: list[float]
    join_type: int
    capped: bool


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
SlabCommand = TypedDict('SlabCommand', {
    'layer': str,
    'class': str,
    'boundary': list[list[float]],
    'elevation': float,
    'thickness': Optional[float],
    'bound': StoryBoundCommand,
})
"""基礎の底盤・地中梁をスラブオブジェクトで描画する命令。

boundary はスラブ外形(平面ポリゴンの頂点列)、elevation はスラブ天端の絶対 Z。
描画フェーズは SetSlabHeight に elevation を渡してスラブの天端高さを設定する
(SetSlabHeight は厚みではなく高さ=Coordinate を設定するため、厚みを渡すと
天端が厚み分だけ高く描画される)。bound はスラブ天端の高さ基準で、基礎の底盤天端
レベルにバインドする(地中梁は底盤天端より低いため offset が負値)。class は割り
当てる構造クラス名(基礎スラブ)。

thickness はスラブスタイルのコンクリート厚 (mm)。底盤(基礎底盤系)にだけ厚みを
設定し、描画フェーズが「基礎スラブ - コンクリート {厚}mm / 捨てコン …mm /
砕石 …mm」のスラブスタイルを適用する(既定=150mm はその既存スタイルをそのまま、
それ以外の厚みは既定スタイルを複製して最上層のコンクリート厚を変更する)。
地中梁など、スラブスタイルを適用しないスラブは None にする(実際の厚みはスラブ
スタイルのコンポーネントが決めるため、スタイルを適用しないスラブでは意味を持たない)。
"""


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
FloorCommand = TypedDict('FloorCommand', {
    'layer': str,
    'class': str,
    'boundary': list[list[float]],
    'thickness': float,
    'elevation': float,
    'bound': StoryBoundCommand,
})
"""床板(IfcSlab "床版")を床ツール(Floor オブジェクト)で描画する命令。

各階の FL レイヤ(``layer``)に床ツールで床を作図する。ホームズ君 IFC の床版は
``IfcSlab`` の ``Name`` が ``床版`` のもので、平面外形が押し出しプロファイルに
なっている(``boundary`` はその外形をグリッド中心オフセットで補正した頂点列)。

``thickness`` は床厚で、要件により 24mm 固定(IFC の押し出し厚は使わない)。
``elevation`` は床下端の絶対 Z で、要件により横架材天端(= ストーリ高さ +
横架材天端オフセット)に一致させる。``bound`` は床下端の高さ基準で、配置先
ストーリの横架材天端レベルにバインドする(offset は床下端が横架材天端ちょうど
のため 0)。``class`` は割り当てる構造クラス名(床板)。
"""


class AnchorBoltCommand(TypedDict):
    """アンカーボルトをハイブリッドシンボルに置換して配置する命令。

    layer は配置先デザインレイヤ名(基礎ストーリの F-アンカーボルト)。symbol は
    置換するハイブリッドシンボル名(座金付き=アンカーボルト_M12、座金なし=
    アンカーボルト_M16)。position はアンカーボルト軸芯の 2D 座標(センタリング済み)。
    高さの基準(基礎天端)は配置先レイヤのストーリレベルが担うため、命令には
    高さ情報を持たせない。
    """

    layer: str
    symbol: str
    position: list[float]


class FloorPostCommand(TypedDict):
    """床束をハイブリッドシンボルに置換して配置する命令。

    ホームズ君 IFC には床束が出力されないため、大引の下に 910mm 間隔で決め打ち
    配置する(``ifc/floor_post.py`` 参照)。layer は配置先デザインレイヤ名(基礎
    ストーリの F-床束)。symbol は置換するハイブリッドシンボル名(床束)。position は
    大引芯線上の床束位置の 2D 座標(センタリング済み)。高さの基準(基礎底盤上端=
    底盤天端)は配置先レイヤのストーリレベルが担うため、命令には高さ情報を持たせない。
    """

    layer: str
    symbol: str
    position: list[float]


class FireBraceCommand(TypedDict):
    """火打(火打梁)をハイブリッドシンボルに置換して配置する命令。

    layer は配置先デザインレイヤ名(火打が属する階の横架材天端、最上階は軒高)。
    symbol は置換するハイブリッドシンボル名(鋼製火打)。position は横架材接合部の
    内側面交点(火打が取り付く 2 梁の面が幾何学的に交わる内角の点、センタリング済み)
    の 2D 座標で、これがシンボルの基準点になる。angle は火打の向きに合わせた回転角
    (度)で、基準点(内角)から火打本体の重心へ向かう方向(内角の二等分方向)に
    シンボルの基準姿勢のずれを補正する反時計方向 45 度を加えた値。
    高さの基準(横架材天端 / 軒高)は配置先レイヤのストーリレベルが担うため、
    命令には高さ情報を持たせない。
    """

    layer: str
    symbol: str
    position: list[float]
    angle: float


class _ViewportBase(TypedDict):
    drawing_title: str
    drawing_number: str
    layers: list[str]


class ViewportCommand(_ViewportBase, total=False):
    """シート上に配置するビューポート 1 つ分。

    drawing_title / drawing_number はビューポートの図面タイトル・図番。layers は
    ビューポートに表示するデザインレイヤ名の並び。ここに挙げたレイヤだけを表示し、
    それ以外のデザインレイヤは非表示にする。hidden_classes は表示レイヤに乗っていても
    非表示にするクラス名の並び(省略可・既定は非表示クラス無し)。クラスは伏図に必要な
    要素が欠けないよう既定で全表示だが、ここに挙げたクラスの図形だけは非表示にする
    (例: 基礎伏図では配筋クラスを隠し、断面でのみ表示する)。
    """

    hidden_classes: list[str]


class SheetCommand(TypedDict):
    """シートレイヤとその上のビューポートを生成する命令。

    number はシートレイヤ番号、title はシートレイヤタイトル。viewport は
    シートに配置するビューポート(表示するデザインレイヤ・図面タイトル・図番)。
    """

    number: str
    title: str
    viewport: ViewportCommand


class TagCommand(TypedDict):
    """横架材の断面寸法データタグを配置する命令。

    style は適用するデータタグスタイル名(VW 側で設定した「断面寸法」)。
    layer は関連付け先の横架材が配置されるデザインレイヤ名で、このレイヤを
    表示するビューポート(=その階の床伏図・小屋伏図)の注釈にタグを置く。
    member_index は関連付け先の横架材の members 内インデックス。position は
    タグの挿入位置で、横架材の軸中央から軸直交方向の「上または左」へ断面幅/2 だけ
    オフセットした部材の辺の中央(左右に伸びる梁は上辺中央、上下に伸びる梁は
    左辺中央、mm・センタリング済み)。ここにデータタグの下端中央が来る。angle は
    横架材の軸方向に沿った文字角度 (度)。
    """

    style: str
    layer: str
    member_index: int
    position: list[float]
    angle: float


ColumnMarkCommand = TypedDict('ColumnMarkCommand', {
    'layer': str,
    'class': str,
    'target_layer': str,
    'target_class': str,
    'size': float,
    'position': list[float],
})
"""柱束伏図記号 PIO(下階柱記号・小屋束記号)を配置する命令。

カスタム PIO「柱束伏図記号」を ``layer`` に置く。PIO はリセット時に
``target_layer`` の構造用途 4/5 の構造材を検索し、柱は ×・小屋束は ○ の記号を
各位置に描く。用途は 2 種類:

- **下階柱記号**: 各階の伏図に直下階(N-1)の柱を記号化する。``layer`` は
  横架材天端(最上階は軒高)レイヤの直上の ``n-下階柱``、``target_layer`` は
  直下階の ``n-柱`` レイヤ。柱(×)と束(○)を別オブジェクトに分けて描画設定を
  独立調整するため、1 階分につき ``target_class`` を管柱クラスに絞った PIO と
  小屋束クラス(直下階に架かる下屋根の小屋束)に絞った PIO の 2 つを置く
  (通し柱には記号を付けない)。
- **小屋束記号**: 母屋伏図に最上階(屋根)の小屋束を記号化する。``layer`` は
  母屋レイヤの直上の ``R-小屋束``、``target_layer`` は屋根の ``R-柱`` レイヤ、
  ``target_class`` は小屋束クラス(小屋束だけに絞り、柱の下階柱記号とは別
  オブジェクトにする)。

``class`` は PIO 本体(=描かれる記号)を作図するクラス名(``vs.SetClass`` で
設定する。記号=柱・束の伏図記号の作図クラス)で、検索対象クラス ``target_class``
とは別物。``target_class`` は検索対象クラス(空=全クラス)、``size`` は記号サイズ
(mm、PIO の MarkSize に渡す)、``position`` は PIO の挿入点(記号は検索した
柱のワールド位置に描かれ挿入点には依存しないため原点でよい)。
"""


class LegendItemCommand(TypedDict):
    """グラフィック凡例の 1 行分(シンボルと表示ラベル)。

    symbol は凡例に載せるハイブリッドシンボル名(例 ``アンカーボルト_M12``)、
    label はその行に表示するラベルテキスト(コード内の固定マッピングで決める。
    例 ``土台用アンカーボルトM12``)。
    """

    symbol: str
    label: str


class LegendCommand(TypedDict):
    """シートレイヤ上にグラフィック凡例を配置する命令。

    VW 標準の「グラフィック凡例」PIO をシートレイヤ(``number``)上の
    ``position`` に置く。凡例は対象シートのビューポートに表示されるシンボル
    (既定ではアンカーボルト)を表し、載せるシンボルと表示ラベルは ``items`` に
    並び順どおり持たせる。グラフィック凡例のデータソース・行ラベルの詳細設定は
    PIO の設定 API が未公開のため VW 上で最終調整する(描画フェーズは他要素と
    同じく VW 上で検証する方針)。
    """

    number: str
    position: list[float]
    items: list[LegendItemCommand]


# 'class' キーが Python の予約語のため functional 構文で定義する(GridCommand と同様)
RebarCommand = TypedDict('RebarCommand', {
    'layer': str,
    'class': str,
    'mode': str,
    'closed': bool,
    'path': list[list[float]],
    'section_size': str,
    'top_bars': str,
    'bottom_bars': str,
    'stirrup': str,
    'main_bar': str,
    'dist_bar': str,
    'slab_thickness': float,
})
"""基礎の配筋 PIO「鉄筋」(姉妹プロジェクト vectorworks-plugin-rebar)を配置する命令。

``鉄筋`` PIO は 3D パス図形で、``path``(3D パス)とパラメータ(モード・鉄筋仕様)
から平面線・3D 鉄筋・断面 2D コンポーネントを自前で描く。本リポジトリは PIO の配置と
パラメータ設定までを担い、配筋の描画ロジックは持たない。

``mode`` は ``"beam"``(梁モード=立上り・地中梁)または ``"slab"``(スラブモード=底盤)。
``layer`` は配置先デザインレイヤ(立上り=F-立上り、地中梁・底盤=F-底盤)。``class`` は
PIO 本体の描画クラス(PIO は全図形をこのクラスで描く)。``path`` は PIO の 3D パス頂点
(mm・センタリング済み・絶対 Z)で、梁モードは梁天端の中心線(開いた線)、スラブモードは
底盤天端の外形(閉じた多角形)。``closed`` はパスを閉じるか(スラブ=True・梁=False)。

配筋仕様は IFC の ``Pset_Reinforcement`` から取得し、無ければ既定値を使う。梁モードは
``section_size``(壁厚×壁高)・``top_bars``/``bottom_bars``(上下端筋)・``stirrup``
(せん断補強筋)を PIO の SectionSize/TopBars/BottomBars/Stirrup に渡す。スラブモードは
``main_bar``/``dist_bar``(主筋・配力筋=シングル両方向)・``slab_thickness``(スラブ厚)を
PIO の MainBar/DistBar/SlabThickness に渡す。使わないモードのフィールドは空文字/0 にする。
"""


class Document(TypedDict):
    """両フェーズを接続する命令セット全体。"""

    version: int
    stories: list[StoryCommand]
    grids: list[GridCommand]
    members: list[MemberCommand]
    rafters: list[RafterCommand]
    columns: list[ColumnCommand]
    walls: list[WallCommand]
    wall_joins: list[WallJoinCommand]
    slabs: list[SlabCommand]
    floors: list[FloorCommand]
    anchor_bolts: list[AnchorBoltCommand]
    floor_posts: list[FloorPostCommand]
    fire_braces: list[FireBraceCommand]
    sheets: list[SheetCommand]
    tags: list[TagCommand]
    column_marks: list[ColumnMarkCommand]
    legends: list[LegendCommand]
    rebars: list[RebarCommand]


class DocumentValidationError(ValueError):
    """命令セットがスキーマに適合しない場合に送出される。"""


def _require(condition: object, message: str) -> None:
    if not condition:
        raise DocumentValidationError(message)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_point(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(_is_number(c) for c in value)
    )


def _is_point3(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_is_number(c) for c in value)
    )


def _validate_level(index: int, level_index: int, level: Any) -> None:
    where = f'stories[{index}].levels[{level_index}]'
    _require(isinstance(level, dict), f'{where} は dict である必要があります')
    _require(isinstance(level.get('type'), str) and level['type'],
             f'{where}.type は非空文字列である必要があります')
    _require(_is_number(level.get('offset')), f'{where}.offset は数値である必要があります')
    _require(isinstance(level.get('layer'), str) and level['layer'],
             f'{where}.layer は非空文字列である必要があります')


def _validate_story(index: int, command: Any) -> None:
    where = f'stories[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('name'), str) and command['name'],
             f'{where}.name は非空文字列である必要があります')
    # 空文字 suffix は VW 2026 で 2 回目以降の CreateStory が失敗するため不可
    _require(isinstance(command.get('suffix'), str) and command['suffix'],
             f'{where}.suffix は非空文字列である必要があります')
    _require(_is_number(command.get('elevation')),
             f'{where}.elevation は数値である必要があります')
    _require(isinstance(command.get('levels'), list),
             f'{where}.levels はリストである必要があります')
    for j, level in enumerate(command['levels']):
        _validate_level(index, j, level)


def _validate_grid(index: int, command: Any) -> None:
    where = f'grids[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('label'), str),
             f'{where}.label は文字列である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')


def _validate_member(index: int, command: Any) -> None:
    where = f'members[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('member_id'), str),
             f'{where}.member_id は文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')
    for key in ('width', 'height', 'elevation', 'end_elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')
    for key in ('start_bound', 'end_bound'):
        _validate_story_bound(where, key, command.get(key))


def _validate_rafter(index: int, command: Any) -> None:
    where = f'rafters[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')
    for key in ('width', 'height', 'elevation', 'end_elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')


def _validate_column(index: int, command: Any) -> None:
    where = f'columns[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('member_id'), str),
             f'{where}.member_id は文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(isinstance(command.get('structural_use'), str)
             and command['structural_use'],
             f'{where}.structural_use は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    for key in ('width', 'depth', 'height', 'elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')
    for key in ('top_hardware', 'bottom_hardware'):
        _require(isinstance(command.get(key), str),
                 f'{where}.{key} は文字列である必要があります')


def _validate_wall(index: int, command: Any) -> None:
    where = f'walls[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(_is_point(command.get('start')),
             f'{where}.start は [x, y] の数値ペアである必要があります')
    _require(_is_point(command.get('end')),
             f'{where}.end は [x, y] の数値ペアである必要があります')
    _require(_is_number(command.get('thickness')),
             f'{where}.thickness は数値である必要があります')
    for key in ('bottom_bound', 'top_bound'):
        _validate_story_bound(where, key, command.get(key))


def _validate_wall_join(index: int, command: Any) -> None:
    where = f'wall_joins[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    for key in ('a', 'b'):
        _require(isinstance(command.get(key), int)
                 and not isinstance(command.get(key), bool)
                 and command[key] >= 0,
                 f'{where}.{key} は 0 以上の整数である必要があります')
    _require(command.get('a') != command.get('b'),
             f'{where}.a と {where}.b は異なる壁インデックスである必要があります')
    _require(_is_point(command.get('point')),
             f'{where}.point は [x, y] の数値ペアである必要があります')
    for key in ('pick_a', 'pick_b'):
        _require(_is_point(command.get(key)),
                 f'{where}.{key} は [x, y] の数値ペアである必要があります')
    # joinModifier: 1=T / 2=L / 3=X / 4=auto
    _require(command.get('join_type') in (1, 2, 3, 4),
             f'{where}.join_type は 1/2/3/4 のいずれかである必要があります')
    _require(isinstance(command.get('capped'), bool),
             f'{where}.capped は真偽値である必要があります')


def _validate_slab(index: int, command: Any) -> None:
    where = f'slabs[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    boundary = command.get('boundary')
    _require(isinstance(boundary, list) and len(boundary) >= 3,
             f'{where}.boundary は 3 点以上の頂点リストである必要があります')
    for j, point in enumerate(boundary):
        _require(_is_point(point),
                 f'{where}.boundary[{j}] は [x, y] の数値ペアである必要があります')
    _require(_is_number(command.get('elevation')),
             f'{where}.elevation は数値である必要があります')
    thickness = command.get('thickness')
    _require(thickness is None or _is_number(thickness),
             f'{where}.thickness は数値または None である必要があります')
    _validate_story_bound(where, 'bound', command.get('bound'))


def _validate_floor(index: int, command: Any) -> None:
    where = f'floors[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    boundary = command.get('boundary')
    _require(isinstance(boundary, list) and len(boundary) >= 3,
             f'{where}.boundary は 3 点以上の頂点リストである必要があります')
    for j, point in enumerate(boundary):
        _require(_is_point(point),
                 f'{where}.boundary[{j}] は [x, y] の数値ペアである必要があります')
    for key in ('thickness', 'elevation'):
        _require(_is_number(command.get(key)),
                 f'{where}.{key} は数値である必要があります')
    _validate_story_bound(where, 'bound', command.get('bound'))


def _validate_anchor_bolt(index: int, command: Any) -> None:
    where = f'anchor_bolts[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('symbol'), str) and command['symbol'],
             f'{where}.symbol は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')


def _validate_floor_post(index: int, command: Any) -> None:
    where = f'floor_posts[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('symbol'), str) and command['symbol'],
             f'{where}.symbol は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')


def _validate_fire_brace(index: int, command: Any) -> None:
    where = f'fire_braces[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('symbol'), str) and command['symbol'],
             f'{where}.symbol は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    _require(_is_number(command.get('angle')),
             f'{where}.angle は数値である必要があります')


def _validate_viewport(where: str, viewport: Any) -> None:
    field = f'{where}.viewport'
    _require(isinstance(viewport, dict), f'{field} は dict である必要があります')
    _require(isinstance(viewport.get('drawing_title'), str),
             f'{field}.drawing_title は文字列である必要があります')
    _require(isinstance(viewport.get('drawing_number'), str),
             f'{field}.drawing_number は文字列である必要があります')
    layers = viewport.get('layers')
    _require(isinstance(layers, list) and len(layers) >= 1,
             f'{field}.layers は 1 つ以上のレイヤ名リストである必要があります')
    for j, layer in enumerate(layers):
        _require(isinstance(layer, str) and layer,
                 f'{field}.layers[{j}] は非空文字列である必要があります')
    hidden_classes = viewport.get('hidden_classes')
    if hidden_classes is not None:
        _require(isinstance(hidden_classes, list),
                 f'{field}.hidden_classes はリストである必要があります')
        for j, name in enumerate(hidden_classes):
            _require(isinstance(name, str) and name,
                     f'{field}.hidden_classes[{j}] は非空文字列である必要があります')


def _validate_sheet(index: int, command: Any) -> None:
    where = f'sheets[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('number'), str) and command['number'],
             f'{where}.number は非空文字列である必要があります')
    _require(isinstance(command.get('title'), str) and command['title'],
             f'{where}.title は非空文字列である必要があります')
    _validate_viewport(where, command.get('viewport'))


def _validate_tag(index: int, command: Any) -> None:
    where = f'tags[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('style'), str) and command['style'],
             f'{where}.style は非空文字列である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('member_index'), int)
             and not isinstance(command.get('member_index'), bool)
             and command['member_index'] >= 0,
             f'{where}.member_index は 0 以上の整数である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    _require(_is_number(command.get('angle')),
             f'{where}.angle は数値である必要があります')


def _validate_column_mark(index: int, command: Any) -> None:
    where = f'column_marks[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(isinstance(command.get('target_layer'), str)
             and command['target_layer'],
             f'{where}.target_layer は非空文字列である必要があります')
    # target_class は空文字(全クラス)を許容するため非空チェックはしない
    _require(isinstance(command.get('target_class'), str),
             f'{where}.target_class は文字列である必要があります')
    _require(_is_number(command.get('size')),
             f'{where}.size は数値である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')


def _validate_legend(index: int, command: Any) -> None:
    where = f'legends[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('number'), str) and command['number'],
             f'{where}.number は非空文字列である必要があります')
    _require(_is_point(command.get('position')),
             f'{where}.position は [x, y] の数値ペアである必要があります')
    items = command.get('items')
    _require(isinstance(items, list),
             f'{where}.items はリストである必要があります')
    for j, item in enumerate(items):
        _require(isinstance(item, dict),
                 f'{where}.items[{j}] は dict である必要があります')
        _require(isinstance(item.get('symbol'), str) and item['symbol'],
                 f'{where}.items[{j}].symbol は非空文字列である必要があります')
        _require(isinstance(item.get('label'), str) and item['label'],
                 f'{where}.items[{j}].label は非空文字列である必要があります')


def _validate_rebar(index: int, command: Any) -> None:
    where = f'rebars[{index}]'
    _require(isinstance(command, dict), f'{where} は dict である必要があります')
    _require(isinstance(command.get('layer'), str) and command['layer'],
             f'{where}.layer は非空文字列である必要があります')
    _require(isinstance(command.get('class'), str) and command['class'],
             f'{where}.class は非空文字列である必要があります')
    _require(command.get('mode') in ('beam', 'slab'),
             f'{where}.mode は "beam" または "slab" である必要があります')
    _require(isinstance(command.get('closed'), bool),
             f'{where}.closed は真偽値である必要があります')
    path = command.get('path')
    _require(isinstance(path, list) and len(path) >= 2,
             f'{where}.path は 2 点以上の頂点リストである必要があります')
    for j, point in enumerate(path):
        _require(_is_point3(point),
                 f'{where}.path[{j}] は [x, y, z] の数値 3 つ組である必要があります')
    for key in ('section_size', 'top_bars', 'bottom_bars', 'stirrup',
                'main_bar', 'dist_bar'):
        _require(isinstance(command.get(key), str),
                 f'{where}.{key} は文字列である必要があります')
    _require(_is_number(command.get('slab_thickness')),
             f'{where}.slab_thickness は数値である必要があります')


def _validate_story_bound(where: str, key: str, bound: Any) -> None:
    field = f'{where}.{key}'
    _require(isinstance(bound, dict), f'{field} は dict である必要があります')
    _require(isinstance(bound.get('story_offset'), int)
             and not isinstance(bound.get('story_offset'), bool),
             f'{field}.story_offset は整数である必要があります')
    _require(isinstance(bound.get('level'), str) and bound['level'],
             f'{field}.level は非空文字列である必要があります')
    _require(_is_number(bound.get('offset')),
             f'{field}.offset は数値である必要があります')


def validate_document(document: Any) -> Document:
    """命令セットを検証し、不正な場合は DocumentValidationError を送出する。"""
    _require(isinstance(document, dict), '命令セットは dict である必要があります')
    _require(document.get('version') == DOCUMENT_VERSION,
             f'未対応の命令セットバージョンです: {document.get("version")!r}')
    for key in ('stories', 'grids', 'members', 'rafters', 'columns', 'walls',
                'wall_joins', 'slabs', 'floors', 'anchor_bolts', 'floor_posts',
                'fire_braces', 'sheets', 'tags', 'column_marks', 'legends',
                'rebars'):
        _require(isinstance(document.get(key), list),
                 f'"{key}" はリストである必要があります')
    for i, command in enumerate(document['stories']):
        _validate_story(i, command)
    for i, command in enumerate(document['grids']):
        _validate_grid(i, command)
    for i, command in enumerate(document['members']):
        _validate_member(i, command)
    for i, command in enumerate(document['rafters']):
        _validate_rafter(i, command)
    for i, command in enumerate(document['columns']):
        _validate_column(i, command)
    for i, command in enumerate(document['walls']):
        _validate_wall(i, command)
    for i, command in enumerate(document['wall_joins']):
        _validate_wall_join(i, command)
    for i, command in enumerate(document['slabs']):
        _validate_slab(i, command)
    for i, command in enumerate(document['floors']):
        _validate_floor(i, command)
    for i, command in enumerate(document['anchor_bolts']):
        _validate_anchor_bolt(i, command)
    for i, command in enumerate(document['floor_posts']):
        _validate_floor_post(i, command)
    for i, command in enumerate(document['fire_braces']):
        _validate_fire_brace(i, command)
    for i, command in enumerate(document['sheets']):
        _validate_sheet(i, command)
    for i, command in enumerate(document['tags']):
        _validate_tag(i, command)
    for i, command in enumerate(document['column_marks']):
        _validate_column_mark(i, command)
    for i, command in enumerate(document['legends']):
        _validate_legend(i, command)
    for i, command in enumerate(document['rebars']):
        _validate_rebar(i, command)
    try:
        # スキーマ検証だけでは未知キー配下の非直列化値を検出できないため、
        # JSON 直列化可能性も明示的に検証する (NaN/Infinity も拒否)
        json.dumps(document, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise DocumentValidationError(
            f'命令セットは JSON 直列化可能である必要があります: {e}'
        ) from e
    return document
