"""拼音音节解析：声母 + 韵母（规范化）+ 声调。纯拼写规则，与具体文本无关。"""

INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h",
            "j", "q", "x", "r", "z", "c", "s"]

_Y = {"yi": "i", "ya": "ia", "yo": "io", "ye": "ie", "yao": "iao", "you": "iou", "yan": "ian",
      "yin": "in", "yang": "iang", "ying": "ing", "yong": "iong", "yu": "v", "yue": "ve",
      "yuan": "van", "yun": "vn", "wu": "u", "wa": "ua", "wo": "uo", "wai": "uai", "wei": "uei",
      "wan": "uan", "wen": "uen", "wang": "uang", "weng": "ueng"}


def parse(syl):
    """'zhuang1' -> ('zh', 'uang', 1)；'yu2' -> ('', 'v', 2)；返回 None 表示无法解析。"""
    s = syl.strip().lower().replace("ü", "v").replace("u:", "v")
    tone = 5
    if s and s[-1].isdigit():
        tone = int(s[-1]); s = s[:-1]
    if tone not in (1, 2, 3, 4, 5):
        tone = 5
    if not s:
        return None
    # 儿化：去掉词尾 r（"er" 本身除外），按 er 韵尾处理留待后续版本
    if s.endswith("r") and s != "er" and len(s) > 2:
        s = s[:-1]
    if s in _Y:
        return "", _Y[s], tone
    if s[0] in "yw":
        return None
    ini = ""
    for c in INITIALS:
        if s.startswith(c):
            ini = c; break
    fin = s[len(ini):]
    if ini in ("j", "q", "x") and fin.startswith("u"):
        fin = "v" + fin[1:]
    if fin == "iu":
        fin = "iou"
    elif fin == "ui":
        fin = "uei"
    elif fin == "un" and ini not in ("j", "q", "x"):
        fin = "uen"
    if fin == "i" and ini in ("z", "c", "s"):
        fin = "ii"        # 舌尖前元音
    elif fin == "i" and ini in ("zh", "ch", "sh", "r"):
        fin = "iii"       # 舌尖后元音
    if fin == "" :
        return None
    return ini, fin, tone
