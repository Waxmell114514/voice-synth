"""最简前端：汉字文本 → 带调拼音（本调）+ 停顿记号。

只用 vendor/ 下的 pypinyin（MIT 许可，含其自带的字和词拼音词典，见 specs/g0-seed.md）。
标点转为停顿记号：逗号类 "<sp>"，句末类 "<sil>"。非汉字非标点的字符忽略。
"""
import os, sys, re

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")


def _load_pypinyin():
    mod = sys.modules.get("pypinyin")
    if mod is not None and not os.path.abspath(mod.__file__).startswith(_VENDOR):
        raise RuntimeError("非引擎内置的 pypinyin 已被导入；引擎只能使用 engine/frontend/vendor 下的副本")
    if _VENDOR not in sys.path:
        sys.path.insert(0, _VENDOR)
    import pypinyin
    assert os.path.abspath(pypinyin.__file__).startswith(_VENDOR)
    return pypinyin


_HAN = re.compile(r"[一-鿿]+")
_SHORT = set("，、；：,;:")
_LONG = set("。！？!?.…")


def text_to_tokens(text):
    pp = _load_pypinyin()
    out = []
    i = 0
    for m in re.finditer(r"[一-鿿]+|[，、；：,;:。！？!?.…]", text):
        s = m.group(0)
        if s in _SHORT:
            out.append("<sp>")
        elif s in _LONG:
            out.append("<sil>")
        else:
            py = pp.lazy_pinyin(s, style=pp.Style.TONE3, neutral_tone_with_five=True)
            out += [p if p[-1].isdigit() else p + "5" for p in py]
    return out
