"""構造材(柱・横架材)を割り当てる VectorWorks クラス名の定義と判定。vs 非依存。

ホームズ君 IFC の ``Name`` フィールドには部材種別が埋め込まれている
(例: ``木梁:土台:1`` / ``木梁:軒桁:1_1`` / ``木梁:母屋:1_2`` / ``小屋束:1_1``)。
種別が判別できる場合はその IFC 記録を信用してクラスを決め、判別できない場合
(火打・隅木谷木・無名等)は階と高さの状況からクラスを推定する。

クラス階層(VW のクラス名は ``-`` 区切りで全パスを連結する):

    04構造
      02木造
        01土台 / 01土台
        02床組 / 01大引・02根太
        03柱   / 01通し柱・02管柱
        04梁桁 / 01小屋梁・02軒桁・03床梁・04胴差
        05小屋組 / 02小屋束・03母屋・04棟木・05垂木
        06耐力面材 / 01壁・02床・03屋根
"""
from __future__ import annotations

# クラス階層の共通接頭辞(04構造 > 02木造)。VW のクラス名は通り芯クラスと同じく
# 番号と名称の間にスペースを入れず、全パスを - で連結する。
_WOOD = '04構造-02木造'

CLASS_DODAI = f'{_WOOD}-01土台-01土台'
CLASS_OOBIKI = f'{_WOOD}-02床組-01大引'
CLASS_NEDA = f'{_WOOD}-02床組-02根太'
# 床板(床合板。IfcSlab "床版")は耐力面材(壁・床・屋根)の床に置く。
CLASS_FLOOR = f'{_WOOD}-06耐力面材-02床'
# 野地板(屋根の下地合板。IfcSlab "屋根版")は耐力面材の屋根に置く。
CLASS_ROOF_SHEATHING = f'{_WOOD}-06耐力面材-03屋根'
CLASS_TOSHIBASHIRA = f'{_WOOD}-03柱-01通し柱'
CLASS_KUDABASHIRA = f'{_WOOD}-03柱-02管柱'
CLASS_KOYABARI = f'{_WOOD}-04梁桁-01小屋梁'
CLASS_NOKIGETA = f'{_WOOD}-04梁桁-02軒桁'
CLASS_YUKABARI = f'{_WOOD}-04梁桁-03床梁'
CLASS_DOUSASHI = f'{_WOOD}-04梁桁-04胴差'
CLASS_KOYAZUKA = f'{_WOOD}-05小屋組-02小屋束'
CLASS_MOYA = f'{_WOOD}-05小屋組-03母屋'
CLASS_MUNAGI = f'{_WOOD}-05小屋組-04棟木'
CLASS_TARUKI = f'{_WOOD}-05小屋組-05垂木'

# IFC Name の種別トークン → 横架材クラス(ホームズ君 IFC の記録を信用する直接対応)。
# 床小梁・床大梁・甲乙梁はいずれも床組の梁なので床梁クラスにまとめる。
_MEMBER_CLASS_BY_TYPE = {
    '土台': CLASS_DODAI,
    '大引': CLASS_OOBIKI,
    '根太': CLASS_NEDA,
    '軒桁': CLASS_NOKIGETA,
    '胴差': CLASS_DOUSASHI,
    '床小梁': CLASS_YUKABARI,
    '床大梁': CLASS_YUKABARI,
    '甲乙梁': CLASS_YUKABARI,
    '小屋梁': CLASS_KOYABARI,
    '母屋': CLASS_MOYA,
    '棟木': CLASS_MUNAGI,
}

# 小屋束を識別する IFC 記録: ObjectType と Name 接頭辞
COLUMN_STANDCOLUMN_OBJECT_TYPE = 'STANDCOLUMN'
COLUMN_KOYAZUKA_NAME_PREFIX = '小屋束'


def member_type_of_name(name: str | None) -> str:
    """IFC ``Name`` から部材種別トークンを取り出す。

    ``木梁:{種別}:{連番}`` は中央の種別(例 ``土台``・``軒桁``)を、
    ``火打:0_1`` / ``筋かい:1FL_1`` のような 2 要素名は接頭辞を返す。
    """
    parts = (name or '').split(':')
    if len(parts) >= 3 and parts[0] == '木梁':
        return parts[1]
    return parts[0]


def member_class_from_name(name: str | None) -> str | None:
    """IFC ``Name`` の種別から横架材クラスを返す。直接対応が無ければ None。"""
    return _MEMBER_CLASS_BY_TYPE.get(member_type_of_name(name))


def resolve_member_class(
    name: str | None, index: int, top_index: int, above_eaves: bool,
) -> str:
    """横架材のクラスを決定する。

    IFC ``Name`` の種別で判別できればそれを信用する。判別できない部材
    (火打・隅木谷木・無名等)は階と高さの状況から推定する:

    - 最下階 (``index == 0``) の横架材 → 土台
    - 中間階の横架材 → 床梁
    - 最上階の地廻り(軒)高さの横架材 → 小屋梁
    - 最上階のそれより高い横架材 (``above_eaves``) → 母屋
    """
    cls = member_class_from_name(name)
    if cls is not None:
        return cls
    if index >= top_index:
        # 最上階(屋根): 軒高付近は小屋梁、それより高ければ母屋
        return CLASS_MOYA if above_eaves else CLASS_KOYABARI
    if index <= 0:
        return CLASS_DODAI
    return CLASS_YUKABARI


def resolve_column_class(
    object_type: str | None, name: str | None,
    index: int, top_index: int, is_through: bool,
) -> str:
    """柱のクラスを決定する。

    小屋束は IFC 記録(``ObjectType == STANDCOLUMN`` または ``Name`` が
    ``小屋束`` で始まる)で判別する。記録が無くても最上階(屋根)の柱は
    小屋束として扱う。一般階の柱は上下端の高さ(複数階を貫くか=``is_through``)で
    通し柱/管柱を判別する。
    """
    if (
        object_type == COLUMN_STANDCOLUMN_OBJECT_TYPE
        or (name or '').startswith(COLUMN_KOYAZUKA_NAME_PREFIX)
        or index >= top_index
    ):
        return CLASS_KOYAZUKA
    return CLASS_TOSHIBASHIRA if is_through else CLASS_KUDABASHIRA
