"""rafter 命令の描画。軸組ツール (FramingMember) で垂木を配置する。

垂木は VectorWorks の軸組ツール(FramingMember、部材種別 ``type='rafter'``)で
描く。命令は軒側(低い端)``start`` と棟側(高い端)``end`` の平面座標と両端の
天端 Z を持つ。ここから **水平投影長(LineLength)・平面方位角・勾配(pitch)** を
求めて FramingMember に渡す。

軸組ツールは点オブジェクト(``CreateCustomObjectN``、``showPref=False`` で設定
ダイアログを抑止)として原点に生成し、``Rotate3D`` で平面方位角(軒→棟)へ回し、
``Move3D`` で軒側の絶対位置(XY + 天端 Z)へ移動する(VectorWorks の VectorScript
エクスポートで確認した配置パターンに従う)。``CreateCustomObject`` はプラグインの
設定に従いインポート中に設定ダイアログを開いてしまうため、点オブジェクト(柱束伏図
記号・鉄筋)と同じく ``CreateCustomObjectN`` で ``showPref=False`` を渡す。
勾配(垂木の傾き)は本体の pitch パラメータが担い、始端(軒側・下端基準)から棟側へ
向かって立ち上がる。フィールド名(``type`` / ``width`` / ``height`` / ``LineLength`` /
``pitch`` / ``verticalReference`` / ``2DDisplay``)は同エクスポートで確認した名前。
軸組ツールの高さ・向き・pitch の最終挙動は VectorWorks 上で検証する(描画フェーズは
他要素と同じく VW 上で検証する方針)。

配置先レイヤが存在しない命令はスキップする(レイヤは story 命令が生成する)。
プラグインが利用できない場合は平面投影の直線にフォールバックする。
"""
from __future__ import annotations

import math
from typing import Any

import vs

from ..document import RafterCommand

PLUGIN_NAME = 'FramingMember'
# 軸組ツールの部材種別。垂木は 'rafter'。
_MEMBER_TYPE = 'rafter'
# CreateCustomObjectN の showPref 引数(オブジェクトの設定ダイアログの表示)。
# インポート中にダイアログで手動入力を求められないよう常に非表示にする。
_SHOW_PREF_DIALOG = False


def draw_rafter(command: RafterCommand) -> Any:
    """rafter 命令 1 件を軸組ツールで描画し、配置したハンドルを返す。

    プラグインが利用できずフォールバック(直線)で描画した場合は None を返す。
    """
    x1, y1 = command['start']        # 軒側(低い端)
    x2, y2 = command['end']          # 棟側(高い端)
    z1 = command['elevation']        # 軒側天端 Z(絶対)
    z2 = command['end_elevation']    # 棟側天端 Z(絶対)

    dx, dy = x2 - x1, y2 - y1
    run = math.hypot(dx, dy)         # 平面投影長 = LineLength
    if run <= 0.0:
        return None
    azimuth = math.degrees(math.atan2(dy, dx))     # 軒→棟の平面方位角
    pitch = math.degrees(math.atan2(z2 - z1, run))  # 勾配(度)

    w = int(round(command['width']))
    h = int(round(command['height']))

    obj = vs.CreateCustomObjectN(PLUGIN_NAME, (0.0, 0.0), 0, _SHOW_PREF_DIALOG)
    if obj != vs.Handle(0):
        # 原点で生成した軸組を平面方位角へ回し、軒側の絶対位置へ移動する。
        vs.ResetOrientation3D()
        vs.Rotate3D(0.0, 0.0, azimuth)
        vs.Move3D(x1, y1, z1)
        vs.SetClass(obj, command['class'])
        vs.SetRField(obj, PLUGIN_NAME, 'type', _MEMBER_TYPE)
        vs.SetRField(obj, PLUGIN_NAME, 'width', str(w))
        vs.SetRField(obj, PLUGIN_NAME, 'height', str(h))
        vs.SetRField(obj, PLUGIN_NAME, 'LineLength', str(run))
        vs.SetRField(obj, PLUGIN_NAME, 'pitch', f'{pitch}°')
        # 軒側(下端基準)から棟側へ立ち上がる
        vs.SetRField(obj, PLUGIN_NAME, 'verticalReference', 'bottom')
        vs.SetRField(obj, PLUGIN_NAME, '2DDisplay', 'widthcenter')
        vs.ResetObject(obj)
        return obj
    # フォールバック: 通常の直線(平面投影)
    vs.MoveTo(x1, y1)
    vs.LineTo(x2, y2)
    fallback_line = vs.LNewObj()
    vs.SetClass(fallback_line, command['class'])
    return None


def execute_rafters(commands: list[RafterCommand]) -> int:
    """rafter 命令のリストを描画し、配置数を返す。

    配置先レイヤ(``n-垂木``)が存在しない命令はスキップする(レイヤは story 命令が
    生成する。未生成 = その階のストーリ設定がスキップされた場合であり、勝手に
    レイヤを作らない。火打・床束等と同じ扱い)。
    """
    count = 0
    for command in commands:
        layer = command['layer']
        if vs.GetObject(layer) == vs.Handle(0):
            continue
        vs.Layer(layer)

        draw_rafter(command)
        count += 1

    return count
