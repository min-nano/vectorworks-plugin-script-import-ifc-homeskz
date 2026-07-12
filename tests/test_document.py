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
        'columns': [
            {
                'layer': '1-柱',
                'member_id': '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(ろ)',
                'class': '04構造-02木造-03柱-02管柱',
                'position': [0.0, 0.0],
                'width': 105.0, 'depth': 105.0, 'height': 2844.0, 'elevation': 426.0,
                'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
                'end_bound': {'story_offset': 1, 'level': '軒高', 'offset': 0.0},
                'top_hardware': '柱頭金物:(ろ)', 'bottom_hardware': '柱脚金物:(ろ)',
            },
        ],
        'walls': [
            {
                'layer': 'F-立上り', 'class': '04構造-01基礎-03立ち上がり',
                'start': [0.0, 0.0], 'end': [3000.0, 0.0], 'thickness': 120.0,
                'bottom_bound': {'story_offset': 0, 'level': 'GL', 'offset': -100.0},
                'top_bound': {'story_offset': 1, 'level': '横架材天端', 'offset': -190.0},
            },
        ],
        'slabs': [
            {
                'layer': 'F-底盤', 'class': '04構造-01基礎-02基礎スラブ',
                'boundary': [[0.0, 0.0], [3000.0, 0.0], [3000.0, 2000.0], [0.0, 2000.0]],
                'thickness': 150.0,
                'bound': {'story_offset': 0, 'level': '底盤天端', 'offset': 0.0},
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
                    'members': [], 'columns': [], 'walls': [], 'slabs': []}
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

    @pytest.mark.parametrize('key', ['stories', 'grids', 'members', 'columns',
                                     'walls', 'slabs'])
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

    def test_accepts_level_with_wall_height(self) -> None:
        document = make_valid_document()
        document['stories'][0]['levels'][0]['wall_height'] = 550.0
        assert validate_document(document) is document

    def test_rejects_level_with_non_numeric_wall_height(self) -> None:
        document = make_valid_document()
        document['stories'][0]['levels'][0]['wall_height'] = 'tall'
        with pytest.raises(DocumentValidationError, match='wall_height'):
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

    def test_rejects_column_without_start_bound(self) -> None:
        document = make_valid_document()
        del document['columns'][0]['start_bound']
        with pytest.raises(DocumentValidationError, match='start_bound'):
            validate_document(document)

    def test_rejects_column_with_bad_story_bound_level(self) -> None:
        document = make_valid_document()
        document['columns'][0]['end_bound']['level'] = ''
        with pytest.raises(DocumentValidationError, match='end_bound.level'):
            validate_document(document)

    def test_rejects_column_with_non_int_story_offset(self) -> None:
        document = make_valid_document()
        document['columns'][0]['start_bound']['story_offset'] = 1.5
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

    def test_rejects_slab_without_thickness(self) -> None:
        document = make_valid_document()
        del document['slabs'][0]['thickness']
        with pytest.raises(DocumentValidationError, match='thickness'):
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
