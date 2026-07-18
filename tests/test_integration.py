"""結合テスト: 実際のホームズ君 EX 出力 IFC を用いた両フェーズ通しの検証。

``tests/fixtures/`` に置いた実 IFC ファイルを対象に、

    IFC 解析フェーズ (ifc.build_document)
        → JSON 直列化 (json.dumps / json.loads)
        → 命令セット検証 (validate_document)
        → 描画フェーズ (vw.execute_document, vs はモック)

というパイプライン全体を 1 本のテストで通す。単体テスト (test_ifc_*, test_vw_*)
が手書きの小さな入力で各部品を検証するのに対し、本テストは実データで
パイプラインが破綻しないこと・解析結果が想定どおりであることを担保する。

vs に依存するのは描画フェーズだけなので、ここでは test_init.py と同じ要領で
ステートフルな vs モックを差し込んで execute_document まで実行する。
"""
from __future__ import annotations

import functools
import importlib
import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    Document,
    LevelCommand,
    validate_document,
)
from vectorworks_plugin_import_ifc_homeskz.ifc import build_document

from tests.conftest import FIXTURES_DIR, load_fixture_ifc


class Expected:
    """1 フィクスチャの想定解析結果。"""

    def __init__(
        self,
        filename: str,
        story_names: list[str],
        story_suffixes: list[str],
        story_elevations: list[float],
        grids: int,
        members: int,
        columns: int,
        walls: int,
        slabs: int,
        floors: int,
        anchor_bolts: int,
        floor_posts: int,
        fire_braces: int,
        sheets: int,
        column_marks: int,
        rafters: int,
        roofs: int,
        rebars: int,
        joints: int,
        moya_stories: set[str] | None = None,
        roof_stories: set[str] | None = None,
        legends: int = 1,
        slab_modifiers: int = 0,
    ) -> None:
        self.filename = filename
        self.story_names = story_names
        self.story_suffixes = story_suffixes
        self.story_elevations = story_elevations
        self.grids = grids
        self.members = members
        self.columns = columns
        self.walls = walls
        self.slabs = slabs
        # 底盤スラブに噛み合わせる地中梁モディファイア(台形プリズム)の総数。
        self.slab_modifiers = slab_modifiers
        self.floors = floors
        self.anchor_bolts = anchor_bolts
        self.floor_posts = floor_posts
        self.fire_braces = fire_braces
        self.sheets = sheets
        self.column_marks = column_marks
        # 屋根版から導出した垂木の総数。
        self.rafters = rafters
        # 屋根版から導出した野地板(屋根オブジェクト)の総数(屋根面 1 枚 1 つ)。
        self.roofs = roofs
        self.rebars = rebars
        # 受ける材のある横架材端部に配置する仕口シンボルの総数。
        self.joints = joints
        # グラフィック凡例数。基礎伏図(基礎があれば 1)+ 各柱梁伏図(床伏図・
        # 小屋伏図)+ 各母屋伏図に 1 つずつ。
        self.legends = legends
        # 下屋根の小屋組(母屋・棟木)を含む中間階のストーリ名の集合。
        # 該当階は 母屋 レベル(n-母屋 レイヤ)を持ち、専用の母屋伏図に母屋を表示する。
        self.moya_stories = moya_stories or set()
        # 屋根版(屋根面)を含む中間階(下屋根)のストーリ名の集合。該当階は
        # 垂木・野地板・小屋束記号レベル(n-垂木/n-野地板/n-小屋束 レイヤ)を持ち、
        # 専用の母屋伏図を 1 枚持つ。下屋根は母屋が無くても屋根版=垂木を持つため
        # moya_stories とは別に管理する(母屋の無い下屋根は moya_stories に含まれず
        # roof_stories にのみ含まれる)。
        self.roof_stories = roof_stories or set()


# 各フィクスチャの想定値。値は build_document の実出力から取得しており、
# 解析ロジックを変更したときに差分として検出できるよう明示的に記載する。
FIXTURES = [
    Expected(
        'サンプル1 (住木邸新築工事).ifc',
        story_names=['基礎', '1階', '2階', '屋根'],
        story_suffixes=['F', '1', '2', 'R'],
        story_elevations=[0.0, 600.0, 3500.0, 6300.0],
        grids=22,
        members=147,
        columns=138,
        walls=17,
        slabs=1,
        slab_modifiers=26,
        floors=2,
        anchor_bolts=96,
        floor_posts=41,
        fire_braces=66,
        sheets=6,
        column_marks=10,
        rafters=110,
        roofs=7,
        rebars=76,
        joints=225,
        legends=6,
        moya_stories={'2階'},
        roof_stories={'2階'},
    ),
    Expected(
        'スキップフロア_サンプル.ifc',
        story_names=['基礎', '1階', '2階', '屋根'],
        story_suffixes=['F', '1', '2', 'R'],
        story_elevations=[0.0, 612.0, 3571.0, 6374.0],
        grids=25,
        members=266,
        columns=197,
        walls=27,
        slabs=2,
        slab_modifiers=35,
        floors=4,
        anchor_bolts=110,
        floor_posts=25,
        fire_braces=35,
        sheets=6,
        column_marks=8,
        rafters=54,
        roofs=3,
        roof_stories={'2階'},
        rebars=106,
        joints=415,
        legends=6,
    ),
    Expected(
        '伏図次郎【2階】.ifc',
        story_names=['基礎', '1階', '2階', '屋根'],
        story_suffixes=['F', '1', '2', 'R'],
        story_elevations=[0.0, 600.0, 3500.0, 6300.0],
        grids=24,
        members=270,
        columns=141,
        walls=17,
        slabs=2,
        slab_modifiers=23,
        floors=2,
        anchor_bolts=85,
        floor_posts=98,
        fire_braces=28,
        sheets=6,
        column_marks=8,
        rafters=143,
        roofs=11,
        rebars=75,
        joints=459,
        legends=6,
        moya_stories={'2階'},
        roof_stories={'2階'},
    ),
    Expected(
        'グレー本モデルプラン1【3階】.ifc',
        story_names=['基礎', '1階', '2階', '3階', '屋根'],
        story_suffixes=['F', '1', '2', '3', 'R'],
        story_elevations=[0.0, 500.0, 3300.0, 6100.0, 8900.0],
        grids=22,
        members=196,
        columns=165,
        walls=13,
        slabs=28,
        slab_modifiers=0,
        floors=3,
        anchor_bolts=60,
        floor_posts=44,
        fire_braces=28,
        sheets=8,
        column_marks=16,
        rafters=106,
        roofs=9,
        rebars=55,
        joints=309,
        legends=8,
        moya_stories={'2階', '3階'},
        roof_stories={'2階', '3階'},
    ),
    Expected(
        'グレー本モデルプラン2【3階】.ifc',
        story_names=['基礎', '1階', '2階', '3階', '屋根'],
        story_suffixes=['F', '1', '2', '3', 'R'],
        story_elevations=[0.0, 455.0, 3185.0, 5915.0, 8190.0],
        grids=20,
        members=69,
        columns=109,
        walls=10,
        slabs=1,
        slab_modifiers=19,
        floors=3,
        anchor_bolts=30,
        floor_posts=20,
        fire_braces=2,
        sheets=6,
        column_marks=8,
        rafters=54,
        roofs=2,
        rebars=43,
        joints=95,
        legends=6,
    ),
]

# pytest のテスト ID をファイル名にする
FIXTURE_IDS = [exp.filename for exp in FIXTURES]


def fixture_path(filename: str) -> str:
    return os.path.join(FIXTURES_DIR, filename)


@functools.lru_cache(maxsize=None)
def _cached_document(filename: str) -> Document:
    """フィクスチャ IFC の解析+命令組み立てをファイルごとに 1 回だけ行いキャッシュする。"""
    return build_document(load_fixture_ifc(filename))


def build_fixture_document(filename: str) -> Document:
    """フィクスチャ IFC を解析し JSON ラウンドトリップ済みの命令セットを返す。

    解析 (load_fixture_ifc) と命令組み立て (build_document) はファイルごとに 1 回だけ
    行いキャッシュする。この関数は同一ファイルに対し多数のテストから繰り返し呼ばれる
    ため、キャッシュにより冗長な再解析・再組み立てを避ける。各呼び出しには JSON
    ラウンドトリップで独立したコピーを返すため (run() と同じ直列化保証も兼ねる)、
    テストが返り値を変更してもキャッシュは汚れない。
    """
    return json.loads(json.dumps(_cached_document(filename)))


def make_vs_mock() -> MagicMock:
    """ストーリ・レイヤ作成を追跡するステートフルな vs モック (test_init.py 準拠)。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created: set[str] = set()
    # デザインレイヤを作成順(下→上)で保持し、FLayer/NextLayer/HMoveForward を
    # モデル化する。これがないと reorder_story_layers の走査が終端しない。
    layers: list[str] = []

    def get_obj(name: str) -> object:
        if name in created:
            return 'HANDLE_' + name
        return null_handle

    def create_story(name: str, suffix: str) -> bool:
        created.add(name)
        return True

    def create_layer(name: str, layer_type: int) -> str:
        created.add(name)
        if name not in layers:
            layers.append(name)
        return 'HANDLE_' + name

    template_counter = [0]

    def create_level_template(layer_name: str, scale: float, level_type: str,
                              elev: float, wall_h: float) -> tuple[bool, int]:
        idx = template_counter[0]
        template_counter[0] += 1
        created.add(layer_name)
        if layer_name not in layers:
            layers.append(layer_name)
        return (True, idx)

    def f_layer() -> object:
        return layers[0] if layers else null_handle

    def next_layer(layer_h: Any) -> object:
        if layer_h in layers:
            i = layers.index(layer_h)
            if i + 1 < len(layers):
                return layers[i + 1]
        return null_handle

    def get_layer_by_name(name: str) -> object:
        return name if name in layers else null_handle

    def h_move_forward(layer_h: Any, to_front: bool) -> None:
        if layer_h in layers:
            i = layers.index(layer_h)
            if not to_front and i + 1 < len(layers):
                layers[i], layers[i + 1] = layers[i + 1], layers[i]

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateLevelTemplateN.side_effect = create_level_template
    vs_mock.FLayer.side_effect = f_layer
    vs_mock.NextLayer.side_effect = next_layer
    vs_mock.GetLayerByName.side_effect = get_layer_by_name
    vs_mock.HMoveForward.side_effect = h_move_forward
    vs_mock.AddLevelFromTemplate.return_value = True
    vs_mock.GetLayerForStory.return_value = 'HANDLE_template_layer'
    vs_mock.LNewObj.return_value = None
    vs_mock.CreateCustomObjectPath.return_value = None
    vs_mock.GetStoryElevationN.return_value = 0.0
    vs_mock.GetLayerElevationN.return_value = (0.0, 0.0)
    # スラブスタイル列挙(BuildResourceList)は空リストを返す(スタイル解決しない)
    vs_mock.BuildResourceList.return_value = (0, 0)
    # ビューポートの全クラス表示ループ用(クラス無し扱いで空ループにする)
    vs_mock.ClassNum.return_value = 0
    return vs_mock


def run_execute_document(vs_mock: MagicMock, document: Document) -> dict[str, int]:
    """vs モックを差し込んで描画フェーズ全体を実行する。"""
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw as vw
        import vectorworks_plugin_import_ifc_homeskz.vw.anchor_bolt as vw_anchor
        import vectorworks_plugin_import_ifc_homeskz.vw.column as vw_column
        import vectorworks_plugin_import_ifc_homeskz.vw.fire_brace as vw_fire
        import vectorworks_plugin_import_ifc_homeskz.vw.footing as vw_footing
        import vectorworks_plugin_import_ifc_homeskz.vw.grid as vw_grid
        import vectorworks_plugin_import_ifc_homeskz.vw.joint as vw_joint
        import vectorworks_plugin_import_ifc_homeskz.vw.member as vw_member
        import vectorworks_plugin_import_ifc_homeskz.vw.rafter as vw_rafter
        import vectorworks_plugin_import_ifc_homeskz.vw.sheet as vw_sheet
        import vectorworks_plugin_import_ifc_homeskz.vw.story as vw_story
        importlib.reload(vw_grid)
        importlib.reload(vw_member)
        importlib.reload(vw_rafter)
        importlib.reload(vw_story)
        importlib.reload(vw_column)
        importlib.reload(vw_footing)
        importlib.reload(vw_anchor)
        importlib.reload(vw_fire)
        importlib.reload(vw_joint)
        importlib.reload(vw_sheet)
        importlib.reload(vw)
        return vw.execute_document(document)


class TestFixturesExist:
    def test_all_fixtures_present(self) -> None:
        """マニフェストの全フィクスチャがリポジトリに存在する。"""
        for exp in FIXTURES:
            assert os.path.isfile(fixture_path(exp.filename)), \
                f'フィクスチャが見つかりません: {exp.filename}'


@pytest.mark.parametrize('exp', FIXTURES, ids=FIXTURE_IDS)
class TestSampleIfcAnalysis:
    """解析フェーズ: 実 IFC が想定どおりの命令セットになることを検証する。"""

    def test_opens_as_ifc(self, exp: Expected) -> None:
        ifc = ifcopenshell.open(fixture_path(exp.filename))
        # ホームズ君 EX 出力は IFC2X3
        assert ifc.schema == 'IFC2X3'

    def test_story_commands_match_expected(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        stories = document['stories']
        assert [s['name'] for s in stories] == exp.story_names
        assert [s['suffix'] for s in stories] == exp.story_suffixes
        assert [s['elevation'] for s in stories] == exp.story_elevations
        # 最下階は基礎ストーリ。レベルはアンカーボルト・立上り・床束・底盤。
        # 並びは希望スタック順(上→下)。
        foundation = stories[0]
        assert foundation['name'] == '基礎'
        assert foundation['suffix'] == 'F'
        assert foundation['elevation'] == 0.0
        # 基礎天端(アンカーボルト) → GL(立上り) → 床束 → 底盤天端(底盤) の順に積む
        assert [lv['type'] for lv in foundation['levels']] == [
            '基礎天端', 'GL', '床束', '底盤天端']
        assert [lv['layer'] for lv in foundation['levels']] == [
            'F-アンカーボルト', 'F-立上り', 'F-床束', 'F-底盤']
        # 柱・小屋束は span(``{from}to{to}-柱``)ごとのレイヤに配置し、各ストーリの
        # levels 先頭(スタック最上段)に積む。span レベルは type=レイヤ名で内容が
        # フィクスチャ依存なので、ここでは span 以外の構造レベルの並びを検証する
        # (span レベルは必ず先頭に来ることも確認する)。下階柱・小屋束(伏図記号)レベルは
        # span 方式で廃止した。
        def structural_types(levels: list[LevelCommand]) -> list[str]:
            return [lv['type'] for lv in levels if not lv['layer'].endswith('-柱')]

        def span_is_prefix(levels: list[LevelCommand]) -> bool:
            spans = [i for i, lv in enumerate(levels) if lv['layer'].endswith('-柱')]
            return spans == list(range(len(spans)))

        # 最上階(屋根): span... ＋ 野地板・垂木・母屋・軒高(この順)。
        roof = stories[-1]
        assert roof['name'] == '屋根'
        assert span_is_prefix(roof['levels'])
        assert structural_types(roof['levels']) == ['野地板', '垂木', '母屋', '軒高']
        # 最下階(1階=stories[1]): span... ＋ FL・横架材天端。
        assert span_is_prefix(stories[1]['levels'])
        assert structural_types(stories[1]['levels']) == ['FL', '横架材天端']
        # 中間階: span... ＋ FL ＋(屋根版があれば 野地板・垂木)＋(母屋があれば 母屋)
        # ＋ 横架材天端(いずれも横架材天端の直上)。
        for story in stories[2:-1]:
            assert span_is_prefix(story['levels'])
            expected_types = ['FL']
            if story['name'] in exp.roof_stories:
                expected_types.append('野地板')
                expected_types.append('垂木')
            if story['name'] in exp.moya_stories:
                expected_types.append('母屋')
            expected_types.append('横架材天端')
            assert structural_types(story['levels']) == expected_types

    def test_grid_and_member_counts_match_expected(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        assert len(document['grids']) == exp.grids
        assert len(document['members']) == exp.members
        assert len(document['rafters']) == exp.rafters
        assert len(document['roofs']) == exp.roofs
        assert len(document['columns']) == exp.columns
        assert len(document['walls']) == exp.walls
        assert len(document['slabs']) == exp.slabs
        assert sum(len(s['modifiers']) for s in document['slabs']) \
            == exp.slab_modifiers
        assert len(document['floors']) == exp.floors
        assert len(document['anchor_bolts']) == exp.anchor_bolts
        assert len(document['floor_posts']) == exp.floor_posts
        assert len(document['fire_braces']) == exp.fire_braces
        assert len(document['joints']) == exp.joints
        assert len(document['sheets']) == exp.sheets
        assert len(document['column_marks']) == exp.column_marks
        assert len(document['rebars']) == exp.rebars
        assert len(document['legends']) == exp.legends

    def test_foundation_plan_sheet_references_foundation_layers(
            self, exp: Expected) -> None:
        """基礎伏図シートは基礎・通り芯レイヤを表示するビューポートを持つ。"""
        document = build_fixture_document(exp.filename)
        # フィクスチャはいずれも基礎を含むため基礎伏図シートが先頭に来る
        sheet = document['sheets'][0]
        assert sheet['number'] == '1'
        assert sheet['title'] == '基礎伏図'
        viewport = sheet['viewport']
        assert viewport['drawing_title'] == '基礎伏図'
        assert viewport['drawing_number'] == '1'
        assert viewport['layers'] == [
            'F-底盤', 'F-立上り', 'F-床束', 'F-アンカーボルト', '共通']

    def test_floor_framing_sheets_follow_foundation(
            self, exp: Expected) -> None:
        """基礎伏図に続けて各階の柱梁伏図が並び、最後に屋根版を持つ階ごとの母屋伏図。"""
        document = build_fixture_document(exp.filename)
        story_layers = {
            level['layer']
            for story in document['stories']
            for level in story['levels']
        }
        # フロア数 = FL ストーリ数(= 基礎を除く)。基礎伏図(先頭・番号 1)に続けて
        # 各階の柱梁伏図(番号 2〜)、その後に屋根版を持つ階ごとの母屋伏図が並ぶ。
        floor_story_count = len(exp.story_names) - 1
        n = floor_story_count
        floor_sheets = document['sheets'][1:1 + n]
        moya_sheets = document['sheets'][1 + n:]
        assert len(floor_sheets) == n
        # タイトルは 1階床伏図・2階床伏図・…、最上階は主屋根の階番号を付けた
        # {n-1}階小屋伏図。下屋根の母屋は専用の母屋伏図に分けるため母屋の表記は付かない。
        expected_titles = [
            f'{n - 1}階小屋伏図' if i == n - 1 else f'{i + 1}階床伏図'
            for i in range(n)
        ]
        assert [s['title'] for s in floor_sheets] == expected_titles
        # シートレイヤ番号は基礎伏図(1)に続けて 2 から連番
        assert [s['number'] for s in floor_sheets] == [
            str(2 + i) for i in range(n)]
        # 母屋伏図は屋根版を持つ階ごとに 1 枚(最上階の主屋根+中間階の下屋根)。
        # story index(0 起点)= exp の階番号: roof_stories(中間階の下屋根)と最上階。
        # story_names[1:] は FL ストーリ(1階・2階・…・屋根)なので、index i の階名は
        # story_names[1 + i]。屋根版を持つ階は roof_stories(中間階)または最上階。
        fl_story_names = exp.story_names[1:]  # 基礎を除く
        moya_indices = [
            i for i in range(n)
            if i == n - 1 or fl_story_names[i] in exp.roof_stories
        ]
        # タイトルは {index}階母屋伏図、番号は柱梁伏図(1..1+n)に続く連番。
        assert [s['title'] for s in moya_sheets] == [
            f'{i}階母屋伏図' for i in moya_indices]
        assert [s['number'] for s in moya_sheets] == [
            str(2 + n + k) for k in range(len(moya_indices))]
        # 最上階(主屋根)の母屋伏図は母屋・垂木・野地板・(切断直下の主屋根小屋束の
        # 伏図記号)・通り芯。切断(3.75 等)を含む span 柱レイヤは無く、切断直下の
        # 小屋束(3.5 等)の伏図記号 {to}-柱伏図記号 だけが載る。
        top_moya_layers = moya_sheets[-1]['viewport']['layers']
        assert top_moya_layers[:3] == ['R-母屋', 'R-垂木', 'R-野地板']
        assert top_moya_layers[-1] == '共通'
        assert all(
            layer.endswith('-柱伏図記号') for layer in top_moya_layers[3:-1])
        # 各伏図の表示レイヤは 通り芯・各階のストーリレイヤ(横架材・柱 span・床・母屋・
        # 垂木・野地板)・最下階のアンカーボルト・伏図記号レイヤ({to}-柱伏図記号)のみ。
        # 伏図記号レイヤはストーリに縛られない独立レイヤ(story 命令には現れない)ため
        # column_marks から集める。
        mark_layers = {
            command['layer'] for command in document['column_marks']
            if command['style'] == '平面'
        }
        allowed = story_layers | {'共通'} | mark_layers
        for s in floor_sheets + moya_sheets:
            for layer in s['viewport']['layers']:
                assert layer in allowed, \
                    f"未知のレイヤを参照しています: {layer}"

    def test_wall_and_slab_layers_reference_foundation_layers(
            self, exp: Expected) -> None:
        """立上り・底盤が参照するレイヤは基礎ストーリのレイヤ名に含まれる。"""
        document = build_fixture_document(exp.filename)
        story_layers = {
            level['layer']
            for story in document['stories']
            for level in story['levels']
        }
        for wall in document['walls']:
            assert wall['layer'] == 'F-立上り'
            assert wall['layer'] in story_layers
        for slab in document['slabs']:
            assert slab['layer'] == 'F-底盤'
            assert slab['layer'] in story_layers

    def test_grids_are_x_or_y_axis_classes(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        valid_classes = {
            '01作図-01線-01基準線-01通り芯-X通り',
            '01作図-01線-01基準線-01通り芯-Y通り',
        }
        for grid in document['grids']:
            assert grid['layer'] == '共通'
            assert grid['class'] in valid_classes

    def test_member_layers_reference_known_story_layers(self, exp: Expected) -> None:
        """構造材が参照するレイヤは story 命令で生成されるレイヤ名に含まれる。"""
        document = build_fixture_document(exp.filename)
        story_layers = {
            level['layer']
            for story in document['stories']
            for level in story['levels']
        }
        for member in document['members']:
            assert member['layer'] in story_layers, \
                f"未知のレイヤを参照しています: {member['layer']}"

    def test_column_layers_reference_known_story_layers(self, exp: Expected) -> None:
        """柱が参照するレイヤは story 命令で生成されるレイヤ名に含まれる。"""
        document = build_fixture_document(exp.filename)
        story_layers = {
            level['layer']
            for story in document['stories']
            for level in story['levels']
        }
        for column in document['columns']:
            assert column['layer'] in story_layers, \
                f"未知のレイヤを参照しています: {column['layer']}"

    def test_floor_layers_and_height_match_stories(self, exp: Expected) -> None:
        """床板は非最上階の FL レイヤに乗り、床下端が IFC の床位置を尊重する。

        床下端(elevation)は「標準の床高(横架材天端)」+「基準高さからの高低差
        (bound.offset)」で表される。段差の無い床は offset 0、段差(スキップフロア)や
        床高の異なる床は offset がずれる。この不変条件と、横架材天端レベルへのバインド・
        厚み 24mm を検証する。
        """
        document = build_fixture_document(exp.filename)
        # story 命令から FL レイヤ→横架材天端の絶対 Z を引く。
        beam_top_by_fl: dict[str, float] = {}
        for story in document['stories']:
            levels = {lv['type']: lv for lv in story['levels']}
            fl = levels.get('FL')
            beam = levels.get('横架材天端')
            if fl is not None and beam is not None:
                beam_top_by_fl[fl['layer']] = story['elevation'] + beam['offset']
        for floor in document['floors']:
            assert floor['layer'] in beam_top_by_fl, \
                f"床板が未知の FL レイヤを参照しています: {floor['layer']}"
            # 床下端(elevation)= 横架材天端の絶対 Z + 高低差(offset)
            assert floor['bound']['level'] == '横架材天端'
            assert floor['bound']['story_offset'] == 0
            assert floor['elevation'] == (
                beam_top_by_fl[floor['layer']] + floor['bound']['offset'])
            assert floor['thickness'] == 24.0

    def test_document_passes_validation(self, exp: Expected) -> None:
        """JSON ラウンドトリップ後の命令セットが検証を通過する。"""
        document = build_fixture_document(exp.filename)
        # 不正なら DocumentValidationError が送出される
        validate_document(document)


@pytest.mark.parametrize('exp', FIXTURES, ids=FIXTURE_IDS)
class TestFullPipeline:
    """解析 → JSON → 検証 → 描画 のパイプライン全体を vs モックで実行する。"""

    def test_execute_document_draws_all_commands(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        vs_mock = make_vs_mock()
        counts = run_execute_document(vs_mock, document)

        # 各フェーズが命令数どおり実行されること
        assert counts['stories'] == len(document['stories'])
        assert counts['grids'] == len(document['grids'])
        assert counts['members'] == len(document['members'])
        assert counts['rafters'] == len(document['rafters'])
        assert counts['roofs'] == len(document['roofs'])
        assert counts['columns'] == len(document['columns'])
        assert counts['walls'] == len(document['walls'])
        assert counts['slabs'] == len(document['slabs'])
        assert counts['floors'] == len(document['floors'])
        assert counts['anchor_bolts'] == len(document['anchor_bolts'])
        assert counts['floor_posts'] == len(document['floor_posts'])
        assert counts['fire_braces'] == len(document['fire_braces'])
        assert counts['joints'] == len(document['joints'])
        assert counts['column_marks'] == len(document['column_marks'])
        assert counts['rebars'] == len(document['rebars'])
        assert counts['sheets'] == len(document['sheets'])
        assert counts['legends'] == len(document['legends'])
        assert counts['stories'] == len(exp.story_names)
        assert counts['grids'] == exp.grids
        assert counts['members'] == exp.members
        assert counts['rafters'] == exp.rafters
        assert counts['roofs'] == exp.roofs
        assert counts['columns'] == exp.columns
        assert counts['walls'] == exp.walls
        assert counts['slabs'] == exp.slabs
        assert counts['floors'] == exp.floors
        assert counts['anchor_bolts'] == exp.anchor_bolts
        assert counts['floor_posts'] == exp.floor_posts
        assert counts['fire_braces'] == exp.fire_braces
        assert counts['joints'] == exp.joints
        assert counts['column_marks'] == exp.column_marks
        assert counts['rebars'] == exp.rebars
        assert counts['sheets'] == exp.sheets
        assert counts['legends'] == exp.legends

    def test_each_story_is_created(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        vs_mock = make_vs_mock()
        run_execute_document(vs_mock, document)

        created_story_names = [c.args[0] for c in vs_mock.CreateStory.call_args_list]
        created_story_suffixes = [c.args[1] for c in vs_mock.CreateStory.call_args_list]
        assert created_story_names == exp.story_names
        assert created_story_suffixes == exp.story_suffixes
