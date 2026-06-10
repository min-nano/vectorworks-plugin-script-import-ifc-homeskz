"""描画フェーズ (vw.story) のテスト。vs をモックし手書きの story 命令で検証する。"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from vectorworks_plugin_import_ifc_homeskz.document import StoryCommand


def make_story_commands() -> list[StoryCommand]:
    """3 階建て (1階・2階・屋根) の story 命令セットを返す。"""
    return [
        {
            'name': '1階', 'suffix': '1', 'elevation': 473.0,
            'levels': [
                {'type': 'FL', 'offset': 0.0, 'layer': '1-FL'},
                {'type': '横架材天端', 'offset': -48.0, 'layer': '1-横架材天端'},
            ],
        },
        {
            'name': '2階', 'suffix': '2', 'elevation': 3273.0,
            'levels': [
                {'type': 'FL', 'offset': 0.0, 'layer': '2-FL'},
                {'type': '横架材天端', 'offset': -36.0, 'layer': '2-横架材天端'},
            ],
        },
        {
            'name': '屋根', 'suffix': 'R', 'elevation': 5973.0,
            'levels': [
                {'type': '軒高', 'offset': 0.0, 'layer': 'R-軒高'},
            ],
        },
    ]


def _make_stateful_vs_mock() -> MagicMock:
    """CreateStory/CreateLayer/CreateLevelTemplateN の作成有無を追跡するステートフルな vs モック。"""
    vs_mock = MagicMock()
    null_handle = object()
    vs_mock.Handle.return_value = null_handle

    created: set[str] = set()
    template_counter = [0]

    def get_obj(name: str) -> object:
        if name in created:
            return 'HANDLE_' + name
        return null_handle

    def create_story(name: str, suffix: str) -> bool:
        created.add(name)
        return True

    def create_layer(name: str, layer_type: int) -> str:
        created.add(name)
        return 'HANDLE_' + name

    def create_level_template(layer_name: str, scale: float, level_type: str,
                              elev: float, wall_h: float) -> tuple[bool, int]:
        idx = template_counter[0]
        template_counter[0] += 1
        return (True, idx)

    vs_mock.GetObject.side_effect = get_obj
    vs_mock.CreateStory.side_effect = create_story
    vs_mock.CreateLayer.side_effect = create_layer
    vs_mock.CreateLevelTemplateN.side_effect = create_level_template
    vs_mock.AddLevelFromTemplate.return_value = True
    vs_mock.GetLayerForStory.return_value = 'HANDLE_template_layer'
    vs_mock.GetStoryElevationN.return_value = 0.0
    vs_mock.GetLayerElevationN.return_value = (0.0, 0.0)
    return vs_mock


def _run_execute_stories(vs_mock: MagicMock, commands: list[StoryCommand]) -> int:
    with patch.dict('sys.modules', {'vs': vs_mock}):
        import vectorworks_plugin_import_ifc_homeskz.vw.story as vw_story
        importlib.reload(vw_story)
        return vw_story.execute_stories(commands)


class TestExecuteStories:
    def test_creates_stories_levels_and_layers(self) -> None:
        vs_mock = _make_stateful_vs_mock()

        count = _run_execute_stories(vs_mock, make_story_commands())

        assert count == 3

        # レベルタイプが登場順に事前登録されていること
        level_type_names = [call.args[0] for call in vs_mock.CreateLayerLevelType.call_args_list]
        assert level_type_names == ['FL', '横架材天端', '軒高']

        story_calls = [call.args for call in vs_mock.CreateStory.call_args_list]
        # 建築慣例: 一般階は階番号、最上階は "R"。空文字 suffix だと 2 回目以降失敗する
        assert story_calls == [('1階', '1'), ('2階', '2'), ('屋根', 'R')]

        # ストーリ高さは N 付き版で document units 指定
        elev_calls = [(call.args[0], call.args[1]) for call in vs_mock.SetStoryElevationN.call_args_list]
        assert elev_calls == [
            ('HANDLE_1階', 473.0),
            ('HANDLE_2階', 3273.0),
            ('HANDLE_屋根', 5973.0),
        ]

        # ストーリレベル + レイヤは Story Level Template 経由で作る
        # (AddStoryLevelN + AssociateLayerWithStory ではレイヤ→レベルの紐付けが
        # UI で <なし> になる現象を回避するため)
        template_calls = [call.args for call in vs_mock.CreateLevelTemplateN.call_args_list]
        # (layerName, scaleFactor, levelType, elevation, wallHeight)
        assert ('1-FL', 1.0, 'FL', 0.0, 2400.0) in template_calls
        assert ('1-横架材天端', 1.0, '横架材天端', -48.0, 2400.0) in template_calls
        assert ('2-FL', 1.0, 'FL', 0.0, 2400.0) in template_calls
        assert ('2-横架材天端', 1.0, '横架材天端', -36.0, 2400.0) in template_calls
        assert ('R-軒高', 1.0, '軒高', 0.0, 2400.0) in template_calls

        # AddLevelFromTemplate がストーリ毎に呼ばれること
        add_calls = [call.args for call in vs_mock.AddLevelFromTemplate.call_args_list]
        # 屋根は 1 つだけ (軒高)、それ以外は 2 つ (FL, 横架材天端) = 計 5 呼び出し
        assert len(add_calls) == 5
        story_call_counts: dict[str, int] = {}
        for h, _ in add_calls:
            story_call_counts[h] = story_call_counts.get(h, 0) + 1
        assert story_call_counts['HANDLE_1階'] == 2
        assert story_call_counts['HANDLE_2階'] == 2
        assert story_call_counts['HANDLE_屋根'] == 1

        # AddLevelFromTemplate 後にレイヤをリネーム ("1-FL-1" → "1-FL")
        rename_calls = [call.args for call in vs_mock.SetName.call_args_list]
        renamed_names = [name for _, name in rename_calls]
        assert '1-FL' in renamed_names
        assert '1-横架材天端' in renamed_names
        assert '2-FL' in renamed_names
        assert '2-横架材天端' in renamed_names
        assert 'R-軒高' in renamed_names

    def test_empty_commands_return_zero(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        count = _run_execute_stories(vs_mock, [])
        assert count == 0
        vs_mock.CreateStory.assert_not_called()
        vs_mock.CreateLayerLevelType.assert_not_called()

    def test_single_roof_story(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        commands: list[StoryCommand] = [
            {
                'name': '屋根', 'suffix': 'R', 'elevation': 0.0,
                'levels': [{'type': '軒高', 'offset': 0.0, 'layer': 'R-軒高'}],
            },
        ]

        count = _run_execute_stories(vs_mock, commands)

        assert count == 1
        story_names = [call.args[0] for call in vs_mock.CreateStory.call_args_list]
        assert story_names == ['屋根']
        # 命令セットに登場するレベルタイプのみ登録される
        level_type_names = [call.args[0] for call in vs_mock.CreateLayerLevelType.call_args_list]
        assert level_type_names == ['軒高']

    def test_skips_story_when_creation_fails(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        # CreateStory が作成に失敗する (created に追加されない)
        vs_mock.CreateStory.side_effect = lambda name, suffix: False

        count = _run_execute_stories(vs_mock, make_story_commands())

        assert count == 0
        vs_mock.SetStoryElevationN.assert_not_called()
        vs_mock.AddLevelFromTemplate.assert_not_called()

    def test_reuses_existing_story(self) -> None:
        vs_mock = _make_stateful_vs_mock()
        # GetObject が最初から非 null を返す (既存ストーリ)
        vs_mock.GetObject.side_effect = lambda name: 'HANDLE_' + name

        commands = make_story_commands()[:1]
        count = _run_execute_stories(vs_mock, commands)

        assert count == 1
        vs_mock.CreateStory.assert_not_called()
        vs_mock.SetStoryElevationN.assert_called_once_with('HANDLE_1階', 473.0)
