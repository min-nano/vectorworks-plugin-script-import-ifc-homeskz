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

import importlib
import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.document import Document, validate_document
from vectorworks_plugin_import_ifc_homeskz.ifc import build_document, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


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
        anchor_bolts: int,
        fire_braces: int,
        sheets: int,
        column_marks: int,
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
        self.anchor_bolts = anchor_bolts
        self.fire_braces = fire_braces
        self.sheets = sheets
        self.column_marks = column_marks


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
        walls=38,
        slabs=38,
        anchor_bolts=96,
        fire_braces=66,
        sheets=5,
        column_marks=3,
    ),
    Expected(
        'スキップフロア_サンプル.ifc',
        story_names=['基礎', '1階', '2階', '屋根'],
        story_suffixes=['F', '1', '2', 'R'],
        story_elevations=[0.0, 612.0, 3571.0, 6374.0],
        grids=25,
        members=266,
        columns=197,
        walls=55,
        slabs=51,
        anchor_bolts=110,
        fire_braces=35,
        sheets=5,
        column_marks=3,
    ),
    Expected(
        '伏図次郎【2階】.ifc',
        story_names=['基礎', '1階', '2階', '屋根'],
        story_suffixes=['F', '1', '2', 'R'],
        story_elevations=[0.0, 600.0, 3500.0, 6300.0],
        grids=24,
        members=270,
        columns=141,
        walls=39,
        slabs=36,
        anchor_bolts=85,
        fire_braces=28,
        sheets=5,
        column_marks=3,
    ),
    Expected(
        'グレー本モデルプラン1【3階】.ifc',
        story_names=['基礎', '1階', '2階', '3階', '屋根'],
        story_suffixes=['F', '1', '2', '3', 'R'],
        story_elevations=[0.0, 500.0, 3300.0, 6100.0, 8900.0],
        grids=22,
        members=196,
        columns=165,
        walls=27,
        slabs=28,
        anchor_bolts=60,
        fire_braces=28,
        sheets=6,
        column_marks=4,
    ),
    Expected(
        'グレー本モデルプラン2【3階】.ifc',
        story_names=['基礎', '1階', '2階', '3階', '屋根'],
        story_suffixes=['F', '1', '2', '3', 'R'],
        story_elevations=[0.0, 455.0, 3185.0, 5915.0, 8190.0],
        grids=20,
        members=69,
        columns=109,
        walls=19,
        slabs=24,
        anchor_bolts=30,
        fire_braces=2,
        sheets=6,
        column_marks=4,
    ),
]

# pytest のテスト ID をファイル名にする
FIXTURE_IDS = [exp.filename for exp in FIXTURES]


def fixture_path(filename: str) -> str:
    return os.path.join(FIXTURES_DIR, filename)


def build_fixture_document(filename: str) -> Document:
    """フィクスチャ IFC を解析し JSON ラウンドトリップ済みの命令セットを返す。"""
    ifc = open_ifc(fixture_path(filename))
    document = build_document(ifc)
    # run() と同じく JSON を経由させ直列化可能性を保証する
    return json.loads(json.dumps(document))


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
        import vectorworks_plugin_import_ifc_homeskz.vw.member as vw_member
        import vectorworks_plugin_import_ifc_homeskz.vw.sheet as vw_sheet
        import vectorworks_plugin_import_ifc_homeskz.vw.story as vw_story
        importlib.reload(vw_grid)
        importlib.reload(vw_member)
        importlib.reload(vw_story)
        importlib.reload(vw_column)
        importlib.reload(vw_footing)
        importlib.reload(vw_anchor)
        importlib.reload(vw_fire)
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
        # 最下階は基礎ストーリ。レベルは GL(立上り) と 底盤天端(底盤)。
        # 並びは立上りを底盤の上に積むため GL を先頭にする。
        foundation = stories[0]
        assert foundation['name'] == '基礎'
        assert foundation['suffix'] == 'F'
        assert foundation['elevation'] == 0.0
        # 基礎天端(アンカーボルト) → GL(立上り) → 底盤天端(底盤) の順に積む
        assert [lv['type'] for lv in foundation['levels']] == [
            '基礎天端', 'GL', '底盤天端']
        assert [lv['layer'] for lv in foundation['levels']] == [
            'F-アンカーボルト', 'F-立上り', 'F-底盤']
        # 最上階は常に「屋根」、構造レベルは「軒高」＋柱配置用の柱＋下階柱記号の下階柱
        # ＋小屋束記号の小屋束＋母屋(棟木含む)配置用の母屋。柱レベルはレイヤを軒高の
        # 直上に積むため先頭、下階柱・小屋束・母屋は軒高の直上に積む(母屋が軒高の直前、
        # 小屋束が母屋の直前)。
        roof = stories[-1]
        assert roof['name'] == '屋根'
        assert [lv['type'] for lv in roof['levels']] == [
            '柱', '下階柱', '小屋束', '母屋', '軒高']
        # 最下階(1階=stories[1])は下に柱が無いため下階柱レベルを持たない
        assert [lv['type'] for lv in stories[1]['levels']] == [
            '柱', 'FL', '横架材天端']
        # 中間階は FL + 横架材天端 ＋柱＋下階柱(横架材天端の直上)
        for story in stories[2:-1]:
            assert [lv['type'] for lv in story['levels']] == [
                '柱', 'FL', '下階柱', '横架材天端']

    def test_grid_and_member_counts_match_expected(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        assert len(document['grids']) == exp.grids
        assert len(document['members']) == exp.members
        assert len(document['columns']) == exp.columns
        assert len(document['walls']) == exp.walls
        assert len(document['slabs']) == exp.slabs
        assert len(document['anchor_bolts']) == exp.anchor_bolts
        assert len(document['fire_braces']) == exp.fire_braces
        assert len(document['sheets']) == exp.sheets
        assert len(document['column_marks']) == exp.column_marks

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
            'F-底盤', 'F-立上り', 'F-アンカーボルト', '共通']

    def test_floor_framing_sheets_follow_foundation(
            self, exp: Expected) -> None:
        """基礎伏図に続けて各階の柱梁伏図が並び、最後に母屋伏図が来る。"""
        document = build_fixture_document(exp.filename)
        story_layers = {
            level['layer']
            for story in document['stories']
            for level in story['levels']
        }
        # 基礎伏図(先頭)と母屋伏図(末尾)を除いた中間が各階の柱梁伏図。
        # フロア数 = FL ストーリ数(= 基礎を除く)。
        floor_sheets = document['sheets'][1:-1]
        moya_sheet = document['sheets'][-1]
        floor_story_count = len(exp.story_names) - 1
        assert len(floor_sheets) == floor_story_count
        # タイトルは 1階床伏図・2階床伏図・…・小屋伏図
        expected_titles = [
            f'{i + 1}階床伏図' for i in range(floor_story_count - 1)
        ] + ['小屋伏図']
        assert [s['title'] for s in floor_sheets] == expected_titles
        # シートレイヤ番号は基礎伏図(1)に続けて 2 から連番
        assert [s['number'] for s in floor_sheets] == [
            str(2 + i) for i in range(floor_story_count)]
        # 母屋伏図は最後で、番号は柱梁伏図に続く。表示レイヤは母屋・小屋束記号・通り芯。
        assert moya_sheet['title'] == '母屋伏図'
        assert moya_sheet['number'] == str(2 + floor_story_count)
        assert moya_sheet['viewport']['layers'] == ['R-母屋', 'R-小屋束', '共通']
        # 各伏図の表示レイヤは 通り芯 と 各階のストーリレイヤ(横架材・柱・床・母屋)、
        # および最下階のアンカーボルトのみ。
        allowed = story_layers | {'共通'}
        for s in floor_sheets + [moya_sheet]:
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
        assert counts['columns'] == len(document['columns'])
        assert counts['walls'] == len(document['walls'])
        assert counts['slabs'] == len(document['slabs'])
        assert counts['anchor_bolts'] == len(document['anchor_bolts'])
        assert counts['fire_braces'] == len(document['fire_braces'])
        assert counts['column_marks'] == len(document['column_marks'])
        assert counts['sheets'] == len(document['sheets'])
        assert counts['stories'] == len(exp.story_names)
        assert counts['grids'] == exp.grids
        assert counts['members'] == exp.members
        assert counts['columns'] == exp.columns
        assert counts['walls'] == exp.walls
        assert counts['slabs'] == exp.slabs
        assert counts['anchor_bolts'] == exp.anchor_bolts
        assert counts['fire_braces'] == exp.fire_braces
        assert counts['column_marks'] == exp.column_marks
        assert counts['sheets'] == exp.sheets

    def test_each_story_is_created(self, exp: Expected) -> None:
        document = build_fixture_document(exp.filename)
        vs_mock = make_vs_mock()
        run_execute_document(vs_mock, document)

        created_story_names = [c.args[0] for c in vs_mock.CreateStory.call_args_list]
        created_story_suffixes = [c.args[1] for c in vs_mock.CreateStory.call_args_list]
        assert created_story_names == exp.story_names
        assert created_story_suffixes == exp.story_suffixes
