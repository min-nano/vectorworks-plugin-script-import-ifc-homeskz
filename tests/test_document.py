"""命令セット (document) スキーマ検証のテスト。vs 非依存。"""
from __future__ import annotations

import json
from typing import Any

import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    DOCUMENT_VERSION,
    DocumentValidationError,
    validate_document,
)


def make_valid_document() -> dict[str, Any]:
    # 検証エラー系テストで自由に改変できるよう Document 型ではなく dict として返す
    return {
        'version': DOCUMENT_VERSION,
        'stories': [
            {
                'name': '1階', 'suffix': '1', 'elevation': 473.0,
                'levels': [
                    {'type': 'FL', 'offset': 0.0, 'layer': '1-FL'},
                    {'type': '横架材天端', 'offset': -48.0, 'layer': '1-横架材天端'},
                ],
            },
            {
                'name': '屋根', 'suffix': 'R', 'elevation': 5973.0,
                'levels': [
                    {'type': '軒高', 'offset': 0.0, 'layer': 'R-軒高'},
                ],
            },
        ],
        'grids': [
            {
                'label': 'X1', 'layer': '共通',
                'class': '01作図-01線-01基準線-01通り芯-X通り',
                'start': [0.0, -1000.0], 'end': [0.0, 1000.0],
            },
        ],
        'members': [
            {
                'layer': '1-横架材天端', 'member_id': '120×180 - 杉',
                'class': '04構造-02木造-01土台-01土台',
                'start': [0.0, 0.0], 'end': [3000.0, 0.0],
                'width': 120.0, 'height': 180.0,
                'elevation': 425.0, 'end_elevation': 425.0,
                'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
                'end_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
            },
        ],
        'rafters': [
            {
                'layer': 'R-垂木', 'class': '04構造-02木造-05小屋組-05垂木',
                'width': 45.0, 'height': 45.0,
                'start': [0.0, 0.0], 'end': [0.0, 2730.0],
                'elevation': 6060.0, 'end_elevation': 7000.0,
                'overhang': 600.0, 'embedment': 52.5, 'label': '45×45@455',
            },
        ],
        'roofs': [
            {
                'layer': 'R-野地板', 'class': '04構造-02木造-06耐力面材-03屋根',
                'boundary': [[0.0, 0.0], [4000.0, 0.0], [4000.0, 3000.0],
                             [0.0, 3000.0]],
                'axis_start': [0.0, 0.0], 'axis_end': [4000.0, 0.0],
                'upslope': [0.0, 3000.0],
                'rise': 400.0, 'run': 1000.0,
                'thickness': 12.0, 'elevation': 6060.0,
            },
        ],
        'columns': [
            {
                'layer': '1-柱',
                'member_id': '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(ろ)',
                'class': '04構造-02木造-03柱-02管柱', 'structural_use': '4',
                'position': [0.0, 0.0],
                'width': 105.0, 'depth': 105.0, 'height': 2844.0, 'elevation': 426.0,
                'top_hardware': '柱頭金物:(ろ)', 'bottom_hardware': '柱脚金物:(ろ)',
                'bottom_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
                'top_bound': {'story_offset': 1, 'level': '横架材天端', 'offset': -56.0},
            },
        ],
        'walls': [
            {
                'layer': 'F-立上り', 'class': '04構造-01基礎-03立ち上がり',
                'start': [0.0, 0.0], 'end': [3000.0, 0.0], 'thickness': 120.0,
                'bottom_bound': {'story_offset': 0, 'level': 'GL', 'offset': -100.0},
                'top_bound': {'story_offset': 1, 'level': '横架材天端', 'offset': -190.0},
            },
            {
                'layer': 'F-立上り', 'class': '04構造-01基礎-03立ち上がり',
                'start': [0.0, 0.0], 'end': [0.0, 3000.0], 'thickness': 120.0,
                'bottom_bound': {'story_offset': 0, 'level': 'GL', 'offset': -100.0},
                'top_bound': {'story_offset': 1, 'level': '横架材天端', 'offset': -190.0},
            },
        ],
        'wall_joins': [
            {'a': 0, 'b': 1, 'point': [0.0, 0.0],
             'pick_a': [30.0, 0.0], 'pick_b': [0.0, 30.0],
             'join_type': 2, 'capped': False},
        ],
        'slabs': [
            {
                'layer': 'F-底盤', 'class': '04構造-01基礎-02基礎スラブ',
                'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0], [0.0, 2000.0]],
                'elevation': 50.0,
                'thickness': 150.0,
                'bound': {'story_offset': 0, 'level': '底盤天端', 'offset': 0.0},
            },
        ],
        'floors': [
            {
                'layer': '1-FL', 'class': '04構造-02木造-06耐力面材-02床',
                'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0],
                             [0.0, 2000.0]],
                'thickness': 24.0, 'elevation': 425.0,
                'bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
            },
        ],
        'anchor_bolts': [
            {
                'layer': 'F-アンカーボルト', 'symbol': 'アンカーボルト_M12',
                'position': [0.0, 0.0],
            },
        ],
        'floor_posts': [
            {
                'layer': 'F-床束', 'symbol': '床束',
                'position': [910.0, 0.0],
            },
        ],
        'fire_braces': [
            {
                'layer': '2-横架材天端', 'symbol': '鋼製火打',
                'position': [1200.0, -800.0], 'angle': -45.0,
            },
        ],
        'joints': [
            {
                'layer': '1-横架材天端', 'symbol': '仕口',
                'position': [1500.0, 60.0], 'angle': 90.0,
            },
        ],
        'sheets': [
            {
                'number': '1', 'title': '基礎伏図',
                'viewport': {
                    'drawing_title': '基礎伏図', 'drawing_number': '1',
                    'layers': ['F-底盤', 'F-立上り', 'F-床束', 'F-アンカーボルト',
                               '共通'],
                },
            },
        ],
        'sections': [
            {
                'direction': 'X', 'source_number': 'X1',
                'drawing_number': 'X1', 'drawing_title': 'X1通り',
                'line_start': [0.0, -9000.0], 'line_end': [0.0, 9000.0],
            },
        ],
        'tags': [
            {
                'style': '断面寸法', 'layer': '1-横架材天端', 'member_index': 0,
                'position': [1500.0, 160.0], 'angle': 0.0,
            },
        ],
        'column_marks': [
            {
                'layer': '2-柱伏図記号', 'class': '01作図-04記号-04構造-一般',
                'target_layer': '1to2-柱',
                'target_class': '', 'size': 300.0, 'style': '平面',
                'symbol': '柱伏図記号',
                'position': [0.0, 0.0],
            },
        ],
        'legends': [
            {
                'number': '1', 'style': '基礎伏図凡例', 'position': [0.0, 0.0],
                'items': [
                    {'symbol': 'アンカーボルト_M12', 'label': '土台用アンカーボルトM12'},
                    {'symbol': 'アンカーボルト_M16',
                     'label': 'ホールダウン用アンカーボルトM16'},
                ],
            },
        ],
        'rebars': [
            {
                'layer': 'F-立上り', 'class': '04構造-01基礎-09鉄筋',
                'mode': 'beam', 'closed': False,
                'path': [[0.0, 0.0, 400.0], [3000.0, 0.0, 400.0]],
                'section_size': '120×500', 'top_bars': '1-D13',
                'bottom_bars': '1-D13', 'stirrup': 'D10@250',
                'main_bar': '', 'dist_bar': '', 'slab_thickness': 0.0,
            },
            {
                'layer': 'F-底盤', 'class': '04構造-01基礎-09鉄筋',
                'mode': 'slab', 'closed': True,
                'path': [[0.0, 0.0, 50.0], [3000.0, 0.0, 50.0],
                         [3000.0, 2000.0, 50.0], [0.0, 2000.0, 50.0]],
                'section_size': '', 'top_bars': '', 'bottom_bars': '',
                'stirrup': '', 'main_bar': 'D13@150', 'dist_bar': 'D13@150',
                'slab_thickness': 150.0,
            },
        ],
    }


class TestValidateDocument:
    def test_valid_document_passes(self) -> None:
        document = make_valid_document()
        assert validate_document(document) is document

    def test_valid_document_survives_json_roundtrip(self) -> None:
        document = json.loads(json.dumps(make_valid_document()))
        assert validate_document(document) is document

    def test_empty_command_lists_pass(self) -> None:
        document = {'version': DOCUMENT_VERSION, 'stories': [], 'grids': [],
                    'members': [], 'rafters': [], 'roofs': [], 'columns': [],
                    'walls': [],
                    'wall_joins': [], 'slabs': [], 'floors': [],
                    'anchor_bolts': [], 'floor_posts': [], 'fire_braces': [],
                    'joints': [], 'sheets': [], 'sections': [], 'tags': [],
                    'column_marks': [], 'legends': [], 'rebars': []}
        validate_document(document)

    def test_rejects_non_dict(self) -> None:
        with pytest.raises(DocumentValidationError):
            validate_document([])

    def test_rejects_unsupported_version(self) -> None:
        document = make_valid_document()
        document['version'] = 999
        with pytest.raises(DocumentValidationError, match='バージョン'):
            validate_document(document)

    def test_rejects_missing_version(self) -> None:
        document = make_valid_document()
        del document['version']
        with pytest.raises(DocumentValidationError):
            validate_document(document)

    @pytest.mark.parametrize('key', ['stories', 'grids', 'members', 'rafters',
                                     'roofs',
                                     'columns', 'walls', 'wall_joins', 'slabs',
                                     'floors',
                                     'anchor_bolts', 'floor_posts',
                                     'fire_braces', 'joints', 'sheets',
                                     'sections',
                                     'tags', 'column_marks', 'legends',
                                     'rebars'])
    def test_rejects_missing_command_list(self, key: str) -> None:
        document = make_valid_document()
        del document[key]
        with pytest.raises(DocumentValidationError):
            validate_document(document)

    def test_rejects_story_with_empty_suffix(self) -> None:
        # 空文字 suffix は VW 2026 で 2 回目以降の CreateStory が失敗する
        document = make_valid_document()
        document['stories'][0]['suffix'] = ''
        with pytest.raises(DocumentValidationError, match='suffix'):
            validate_document(document)

    def test_rejects_story_with_non_numeric_elevation(self) -> None:
        document = make_valid_document()
        document['stories'][0]['elevation'] = '473'
        with pytest.raises(DocumentValidationError, match='elevation'):
            validate_document(document)

    def test_rejects_level_without_layer(self) -> None:
        document = make_valid_document()
        del document['stories'][0]['levels'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_grid_without_class(self) -> None:
        document = make_valid_document()
        del document['grids'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_grid_with_bad_point(self) -> None:
        document = make_valid_document()
        document['grids'][0]['start'] = [0.0]
        with pytest.raises(DocumentValidationError, match='start'):
            validate_document(document)

    def test_rejects_member_without_dimension(self) -> None:
        document = make_valid_document()
        del document['members'][0]['width']
        with pytest.raises(DocumentValidationError, match='width'):
            validate_document(document)

    def test_rejects_member_without_end_elevation(self) -> None:
        document = make_valid_document()
        del document['members'][0]['end_elevation']
        with pytest.raises(DocumentValidationError, match='end_elevation'):
            validate_document(document)

    def test_rejects_rafter_without_class(self) -> None:
        document = make_valid_document()
        del document['rafters'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_rafter_without_dimension(self) -> None:
        document = make_valid_document()
        del document['rafters'][0]['width']
        with pytest.raises(DocumentValidationError, match='width'):
            validate_document(document)

    def test_rejects_rafter_with_bad_start(self) -> None:
        document = make_valid_document()
        document['rafters'][0]['start'] = [0.0]
        with pytest.raises(DocumentValidationError, match='start'):
            validate_document(document)

    def test_rejects_rafter_without_overhang(self) -> None:
        document = make_valid_document()
        del document['rafters'][0]['overhang']
        with pytest.raises(DocumentValidationError, match='overhang'):
            validate_document(document)

    def test_rejects_rafter_without_embedment(self) -> None:
        document = make_valid_document()
        del document['rafters'][0]['embedment']
        with pytest.raises(DocumentValidationError, match='embedment'):
            validate_document(document)

    def test_rejects_rafter_with_non_string_label(self) -> None:
        document = make_valid_document()
        document['rafters'][0]['label'] = 123
        with pytest.raises(DocumentValidationError, match='label'):
            validate_document(document)

    def test_rejects_roof_without_class(self) -> None:
        document = make_valid_document()
        del document['roofs'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_roof_with_short_boundary(self) -> None:
        document = make_valid_document()
        document['roofs'][0]['boundary'] = [[0.0, 0.0], [1.0, 1.0]]
        with pytest.raises(DocumentValidationError, match='boundary'):
            validate_document(document)

    def test_rejects_roof_with_bad_axis(self) -> None:
        document = make_valid_document()
        document['roofs'][0]['axis_start'] = [0.0]
        with pytest.raises(DocumentValidationError, match='axis_start'):
            validate_document(document)

    def test_rejects_roof_without_thickness(self) -> None:
        document = make_valid_document()
        del document['roofs'][0]['thickness']
        with pytest.raises(DocumentValidationError, match='thickness'):
            validate_document(document)

    def test_rejects_member_with_non_string_id(self) -> None:
        document = make_valid_document()
        document['members'][0]['member_id'] = 120
        with pytest.raises(DocumentValidationError, match='member_id'):
            validate_document(document)

    def test_rejects_member_without_class(self) -> None:
        document = make_valid_document()
        del document['members'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_member_without_start_bound(self) -> None:
        document = make_valid_document()
        del document['members'][0]['start_bound']
        with pytest.raises(DocumentValidationError, match='start_bound'):
            validate_document(document)

    def test_rejects_member_with_empty_bound_level(self) -> None:
        document = make_valid_document()
        document['members'][0]['end_bound']['level'] = ''
        with pytest.raises(DocumentValidationError, match='end_bound.level'):
            validate_document(document)

    def test_rejects_column_without_dimension(self) -> None:
        document = make_valid_document()
        del document['columns'][0]['depth']
        with pytest.raises(DocumentValidationError, match='depth'):
            validate_document(document)

    def test_rejects_column_with_non_string_member_id(self) -> None:
        document = make_valid_document()
        document['columns'][0]['member_id'] = 105
        with pytest.raises(DocumentValidationError, match='member_id'):
            validate_document(document)

    def test_rejects_column_without_class(self) -> None:
        document = make_valid_document()
        del document['columns'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_column_without_structural_use(self) -> None:
        document = make_valid_document()
        del document['columns'][0]['structural_use']
        with pytest.raises(DocumentValidationError, match='structural_use'):
            validate_document(document)

    def test_rejects_column_with_empty_structural_use(self) -> None:
        document = make_valid_document()
        document['columns'][0]['structural_use'] = ''
        with pytest.raises(DocumentValidationError, match='structural_use'):
            validate_document(document)

    def test_rejects_column_with_bad_position(self) -> None:
        document = make_valid_document()
        document['columns'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_column_with_non_string_hardware(self) -> None:
        document = make_valid_document()
        document['columns'][0]['top_hardware'] = 123
        with pytest.raises(DocumentValidationError, match='top_hardware'):
            validate_document(document)

    def test_rejects_member_with_non_int_story_offset(self) -> None:
        document = make_valid_document()
        document['members'][0]['start_bound']['story_offset'] = 1.5
        with pytest.raises(DocumentValidationError, match='story_offset'):
            validate_document(document)

    def test_rejects_wall_without_thickness(self) -> None:
        document = make_valid_document()
        del document['walls'][0]['thickness']
        with pytest.raises(DocumentValidationError, match='thickness'):
            validate_document(document)

    def test_rejects_wall_without_class(self) -> None:
        document = make_valid_document()
        del document['walls'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_wall_with_bad_point(self) -> None:
        document = make_valid_document()
        document['walls'][0]['end'] = [0.0]
        with pytest.raises(DocumentValidationError, match='end'):
            validate_document(document)

    def test_rejects_wall_without_top_bound(self) -> None:
        document = make_valid_document()
        del document['walls'][0]['top_bound']
        with pytest.raises(DocumentValidationError, match='top_bound'):
            validate_document(document)

    def test_rejects_wall_with_bad_bound_level(self) -> None:
        document = make_valid_document()
        document['walls'][0]['bottom_bound']['level'] = ''
        with pytest.raises(DocumentValidationError, match='bottom_bound.level'):
            validate_document(document)

    def test_rejects_wall_join_with_non_int_index(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['a'] = 0.5
        with pytest.raises(DocumentValidationError, match='wall_joins'):
            validate_document(document)

    def test_rejects_wall_join_with_negative_index(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['b'] = -1
        with pytest.raises(DocumentValidationError, match='wall_joins'):
            validate_document(document)

    def test_rejects_wall_join_with_same_indices(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['b'] = document['wall_joins'][0]['a']
        with pytest.raises(DocumentValidationError, match='異なる壁インデックス'):
            validate_document(document)

    def test_rejects_wall_join_with_bad_point(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['point'] = [0.0]
        with pytest.raises(DocumentValidationError, match='point'):
            validate_document(document)

    def test_rejects_wall_join_with_bad_pick_a(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['pick_a'] = [0.0]
        with pytest.raises(DocumentValidationError, match='pick_a'):
            validate_document(document)

    def test_rejects_wall_join_with_bad_pick_b(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['pick_b'] = 'x'
        with pytest.raises(DocumentValidationError, match='pick_b'):
            validate_document(document)

    def test_rejects_wall_join_with_invalid_join_type(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['join_type'] = 9
        with pytest.raises(DocumentValidationError, match='join_type'):
            validate_document(document)

    def test_rejects_wall_join_without_capped(self) -> None:
        document = make_valid_document()
        del document['wall_joins'][0]['capped']
        with pytest.raises(DocumentValidationError, match='capped'):
            validate_document(document)

    def test_rejects_wall_join_with_non_bool_capped(self) -> None:
        document = make_valid_document()
        document['wall_joins'][0]['capped'] = 1
        with pytest.raises(DocumentValidationError, match='capped'):
            validate_document(document)

    def test_rejects_slab_without_elevation(self) -> None:
        document = make_valid_document()
        del document['slabs'][0]['elevation']
        with pytest.raises(DocumentValidationError, match='elevation'):
            validate_document(document)

    def test_rejects_slab_without_class(self) -> None:
        document = make_valid_document()
        del document['slabs'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_slab_with_too_few_boundary_points(self) -> None:
        document = make_valid_document()
        document['slabs'][0]['boundary'] = [[0.0, 0.0], [1.0, 0.0]]
        with pytest.raises(DocumentValidationError, match='boundary'):
            validate_document(document)

    def test_rejects_slab_with_bad_boundary_point(self) -> None:
        document = make_valid_document()
        document['slabs'][0]['boundary'] = [[0.0, 0.0], [1.0, 0.0], [0.0]]
        with pytest.raises(DocumentValidationError, match='boundary'):
            validate_document(document)

    def test_rejects_slab_with_bad_bound_level(self) -> None:
        document = make_valid_document()
        document['slabs'][0]['bound']['level'] = ''
        with pytest.raises(DocumentValidationError, match='bound.level'):
            validate_document(document)

    def test_accepts_slab_with_none_thickness(self) -> None:
        # 地中梁など、スラブスタイルを適用しないスラブは thickness=None を許容する
        document = make_valid_document()
        document['slabs'][0]['thickness'] = None
        validate_document(document)

    def test_rejects_slab_with_non_numeric_thickness(self) -> None:
        document = make_valid_document()
        document['slabs'][0]['thickness'] = 'thick'
        with pytest.raises(DocumentValidationError, match='thickness'):
            validate_document(document)

    def test_rejects_floor_without_layer(self) -> None:
        document = make_valid_document()
        del document['floors'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_floor_without_class(self) -> None:
        document = make_valid_document()
        del document['floors'][0]['class']
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_floor_with_too_few_boundary_points(self) -> None:
        document = make_valid_document()
        document['floors'][0]['boundary'] = [[0.0, 0.0], [1.0, 0.0]]
        with pytest.raises(DocumentValidationError, match='boundary'):
            validate_document(document)

    def test_rejects_floor_with_bad_boundary_point(self) -> None:
        document = make_valid_document()
        document['floors'][0]['boundary'] = [[0.0, 0.0], [1.0, 0.0], [0.0]]
        with pytest.raises(DocumentValidationError, match='boundary'):
            validate_document(document)

    def test_rejects_floor_without_thickness(self) -> None:
        document = make_valid_document()
        del document['floors'][0]['thickness']
        with pytest.raises(DocumentValidationError, match='thickness'):
            validate_document(document)

    def test_rejects_floor_with_non_numeric_elevation(self) -> None:
        document = make_valid_document()
        document['floors'][0]['elevation'] = 'high'
        with pytest.raises(DocumentValidationError, match='elevation'):
            validate_document(document)

    def test_rejects_floor_with_bad_bound_level(self) -> None:
        document = make_valid_document()
        document['floors'][0]['bound']['level'] = ''
        with pytest.raises(DocumentValidationError, match='bound.level'):
            validate_document(document)

    def test_rejects_anchor_bolt_without_symbol(self) -> None:
        document = make_valid_document()
        del document['anchor_bolts'][0]['symbol']
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_anchor_bolt_with_empty_symbol(self) -> None:
        document = make_valid_document()
        document['anchor_bolts'][0]['symbol'] = ''
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_anchor_bolt_without_layer(self) -> None:
        document = make_valid_document()
        del document['anchor_bolts'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_anchor_bolt_with_bad_position(self) -> None:
        document = make_valid_document()
        document['anchor_bolts'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_floor_post_without_symbol(self) -> None:
        document = make_valid_document()
        del document['floor_posts'][0]['symbol']
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_floor_post_with_empty_symbol(self) -> None:
        document = make_valid_document()
        document['floor_posts'][0]['symbol'] = ''
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_floor_post_without_layer(self) -> None:
        document = make_valid_document()
        del document['floor_posts'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_floor_post_with_bad_position(self) -> None:
        document = make_valid_document()
        document['floor_posts'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_fire_brace_without_symbol(self) -> None:
        document = make_valid_document()
        del document['fire_braces'][0]['symbol']
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_fire_brace_with_empty_symbol(self) -> None:
        document = make_valid_document()
        document['fire_braces'][0]['symbol'] = ''
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_fire_brace_without_layer(self) -> None:
        document = make_valid_document()
        del document['fire_braces'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_fire_brace_with_bad_position(self) -> None:
        document = make_valid_document()
        document['fire_braces'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_fire_brace_with_non_number_angle(self) -> None:
        document = make_valid_document()
        document['fire_braces'][0]['angle'] = 'x'
        with pytest.raises(DocumentValidationError, match='angle'):
            validate_document(document)

    def test_rejects_joint_without_symbol(self) -> None:
        document = make_valid_document()
        del document['joints'][0]['symbol']
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_joint_with_empty_symbol(self) -> None:
        document = make_valid_document()
        document['joints'][0]['symbol'] = ''
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_joint_without_layer(self) -> None:
        document = make_valid_document()
        del document['joints'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_joint_with_bad_position(self) -> None:
        document = make_valid_document()
        document['joints'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_joint_with_non_number_angle(self) -> None:
        document = make_valid_document()
        document['joints'][0]['angle'] = 'x'
        with pytest.raises(DocumentValidationError, match='angle'):
            validate_document(document)

    def test_rejects_sheet_with_empty_number(self) -> None:
        document = make_valid_document()
        document['sheets'][0]['number'] = ''
        with pytest.raises(DocumentValidationError, match='number'):
            validate_document(document)

    def test_rejects_sheet_without_title(self) -> None:
        document = make_valid_document()
        del document['sheets'][0]['title']
        with pytest.raises(DocumentValidationError, match='title'):
            validate_document(document)

    def test_rejects_sheet_without_viewport(self) -> None:
        document = make_valid_document()
        del document['sheets'][0]['viewport']
        with pytest.raises(DocumentValidationError, match='viewport'):
            validate_document(document)

    def test_rejects_viewport_with_non_string_drawing_number(self) -> None:
        document = make_valid_document()
        document['sheets'][0]['viewport']['drawing_number'] = 1
        with pytest.raises(DocumentValidationError, match='drawing_number'):
            validate_document(document)

    def test_rejects_viewport_without_layers(self) -> None:
        document = make_valid_document()
        document['sheets'][0]['viewport']['layers'] = []
        with pytest.raises(DocumentValidationError, match='layers'):
            validate_document(document)

    def test_rejects_viewport_with_empty_layer_name(self) -> None:
        document = make_valid_document()
        document['sheets'][0]['viewport']['layers'] = ['F-底盤', '']
        with pytest.raises(DocumentValidationError, match='layers'):
            validate_document(document)

    def test_rejects_tag_without_style(self) -> None:
        document = make_valid_document()
        del document['tags'][0]['style']
        with pytest.raises(DocumentValidationError, match='style'):
            validate_document(document)

    def test_rejects_tag_with_empty_layer(self) -> None:
        document = make_valid_document()
        document['tags'][0]['layer'] = ''
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_tag_with_negative_member_index(self) -> None:
        document = make_valid_document()
        document['tags'][0]['member_index'] = -1
        with pytest.raises(DocumentValidationError, match='member_index'):
            validate_document(document)

    def test_rejects_tag_with_non_int_member_index(self) -> None:
        document = make_valid_document()
        document['tags'][0]['member_index'] = 0.5
        with pytest.raises(DocumentValidationError, match='member_index'):
            validate_document(document)

    def test_rejects_tag_with_bad_position(self) -> None:
        document = make_valid_document()
        document['tags'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_tag_with_non_numeric_angle(self) -> None:
        document = make_valid_document()
        document['tags'][0]['angle'] = '0'
        with pytest.raises(DocumentValidationError, match='angle'):
            validate_document(document)

    def test_rejects_column_mark_without_layer(self) -> None:
        document = make_valid_document()
        del document['column_marks'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_column_mark_with_empty_class(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['class'] = ''
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_column_mark_with_empty_target_layer(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['target_layer'] = ''
        with pytest.raises(DocumentValidationError, match='target_layer'):
            validate_document(document)

    def test_rejects_column_mark_with_non_string_target_class(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['target_class'] = 1
        with pytest.raises(DocumentValidationError, match='target_class'):
            validate_document(document)

    def test_accepts_column_mark_with_empty_target_class(self) -> None:
        # 空の target_class(全クラス)は許容する
        document = make_valid_document()
        document['column_marks'][0]['target_class'] = ''
        validate_document(document)

    def test_rejects_column_mark_without_size(self) -> None:
        document = make_valid_document()
        del document['column_marks'][0]['size']
        with pytest.raises(DocumentValidationError, match='size'):
            validate_document(document)

    def test_rejects_column_mark_with_bad_position(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_column_mark_with_empty_style(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['style'] = ''
        with pytest.raises(DocumentValidationError, match='style'):
            validate_document(document)

    def test_rejects_column_mark_with_non_string_symbol(self) -> None:
        document = make_valid_document()
        document['column_marks'][0]['symbol'] = 1
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_accepts_column_mark_with_empty_symbol(self) -> None:
        # 断面記号はシンボルを持たない(空文字)ため許容する
        document = make_valid_document()
        document['column_marks'][0]['symbol'] = ''
        validate_document(document)

    def test_rejects_legend_without_number(self) -> None:
        document = make_valid_document()
        del document['legends'][0]['number']
        with pytest.raises(DocumentValidationError, match='number'):
            validate_document(document)

    def test_rejects_legend_with_empty_number(self) -> None:
        document = make_valid_document()
        document['legends'][0]['number'] = ''
        with pytest.raises(DocumentValidationError, match='number'):
            validate_document(document)

    def test_rejects_legend_without_style(self) -> None:
        document = make_valid_document()
        del document['legends'][0]['style']
        with pytest.raises(DocumentValidationError, match='style'):
            validate_document(document)

    def test_rejects_legend_with_empty_style(self) -> None:
        document = make_valid_document()
        document['legends'][0]['style'] = ''
        with pytest.raises(DocumentValidationError, match='style'):
            validate_document(document)

    def test_rejects_legend_with_bad_position(self) -> None:
        document = make_valid_document()
        document['legends'][0]['position'] = [0.0]
        with pytest.raises(DocumentValidationError, match='position'):
            validate_document(document)

    def test_rejects_legend_with_non_list_items(self) -> None:
        document = make_valid_document()
        document['legends'][0]['items'] = 'x'
        with pytest.raises(DocumentValidationError, match='items'):
            validate_document(document)

    def test_rejects_legend_item_with_empty_symbol(self) -> None:
        document = make_valid_document()
        document['legends'][0]['items'][0]['symbol'] = ''
        with pytest.raises(DocumentValidationError, match='symbol'):
            validate_document(document)

    def test_rejects_legend_item_with_empty_label(self) -> None:
        document = make_valid_document()
        document['legends'][0]['items'][0]['label'] = ''
        with pytest.raises(DocumentValidationError, match='label'):
            validate_document(document)

    def test_accepts_legend_with_empty_items(self) -> None:
        # items が空(載せるシンボルが無い)場合も凡例命令自体は許容する
        document = make_valid_document()
        document['legends'][0]['items'] = []
        validate_document(document)

    def test_rejects_rebar_without_layer(self) -> None:
        document = make_valid_document()
        del document['rebars'][0]['layer']
        with pytest.raises(DocumentValidationError, match='layer'):
            validate_document(document)

    def test_rejects_rebar_with_empty_class(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['class'] = ''
        with pytest.raises(DocumentValidationError, match='class'):
            validate_document(document)

    def test_rejects_rebar_with_bad_mode(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['mode'] = 'column'
        with pytest.raises(DocumentValidationError, match='mode'):
            validate_document(document)

    def test_rejects_rebar_with_non_bool_closed(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['closed'] = 'yes'
        with pytest.raises(DocumentValidationError, match='closed'):
            validate_document(document)

    def test_rejects_rebar_with_short_path(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['path'] = [[0.0, 0.0, 0.0]]
        with pytest.raises(DocumentValidationError, match='path'):
            validate_document(document)

    def test_rejects_rebar_with_2d_path_vertex(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['path'] = [[0.0, 0.0], [1.0, 1.0]]
        with pytest.raises(DocumentValidationError, match='path'):
            validate_document(document)

    def test_rejects_rebar_with_non_string_section_size(self) -> None:
        document = make_valid_document()
        document['rebars'][0]['section_size'] = 120
        with pytest.raises(DocumentValidationError, match='section_size'):
            validate_document(document)

    def test_rejects_rebar_with_non_number_slab_thickness(self) -> None:
        document = make_valid_document()
        document['rebars'][1]['slab_thickness'] = '150'
        with pytest.raises(DocumentValidationError, match='slab_thickness'):
            validate_document(document)

    def test_accepts_rebar_with_empty_spec_fields(self) -> None:
        # 使わないモードの仕様フィールドは空文字を許容する
        document = make_valid_document()
        document['rebars'][0]['main_bar'] = ''
        document['rebars'][0]['dist_bar'] = ''
        validate_document(document)

    def test_rejects_non_json_serializable_value(self) -> None:
        """スキーマ検証を通る位置 (未知キー) に非直列化オブジェクトが混入しても拒否する。"""
        document = make_valid_document()
        document['stories'][0]['_debug'] = object()
        with pytest.raises(DocumentValidationError, match='JSON'):
            validate_document(document)

    def test_rejects_nan_value(self) -> None:
        """NaN は JSON 仕様外なので拒否する。"""
        document = make_valid_document()
        document['members'][0]['elevation'] = float('nan')
        with pytest.raises(DocumentValidationError, match='JSON'):
            validate_document(document)
