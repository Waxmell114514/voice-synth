"""阶段 0 一次性脚本：从 AISHELL-3 测试集构造评估数据。

产物（全部在 eval/data/ 下）：
  speakers.json   参考池说话人 / 校准说话人划分
  sentences.json  400 句音素平衡句，dev 200 + hidden 200（每句带一条真人录音）
  refpool.json    参考池语句清单（用于 T1 统计、T4 参考分布）
  wordlist.json   覆盖常用词中全部带调音节的双音节词
  wav/            下载的录音（44.1 kHz 原始文件）
只依赖 AISHELL-3 content.txt / spk-info.txt、pypinyin、jieba 词频。
"""
import json, os, random, re, sys, collections, urllib.request, concurrent.futures as cf
from pypinyin import lazy_pinyin, Style

ROOT = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(ROOT, "data")
A3 = os.path.join(D, "aishell3")
HF = "https://huggingface.co/datasets/AISHELL/AISHELL-3/resolve/main/"
RNG = random.Random(20261124)


def toned(text):
    """引擎外部统一的拼音化：TONE3，轻声记 5。"""
    return [p if p[-1].isdigit() else p + "5"
            for p in lazy_pinyin(text, style=Style.TONE3, neutral_tone_with_five=True)]


def load():
    info = {}
    for l in open(os.path.join(A3, "spk-info.txt"), encoding="utf-8"):
        if l.startswith("SSB"):
            s, age, g, acc = l.split()
            info[s] = (g, acc)
    # HF 镜像只含部分录音（hf_files.txt 为其文件清单），只用实际存在的
    have = {}
    for f in open(os.path.join(A3, "hf_files.txt"), encoding="utf-8").read().split():
        if f.endswith(".wav"):
            have[os.path.basename(f)[:-4]] = f
    utts = []
    for split in ("train", "test"):
        for l in open(os.path.join(A3, split, "content.txt"), encoding="utf-8"):
            name, rest = l.rstrip("\n").split("\t")
            if name[:-4] not in have:
                continue
            tok = rest.split()
            han = "".join(tok[0::2])
            utts.append((name[:-4], name[:7], han))
    return info, utts, have


def fetch(rel, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    for attempt in range(4):
        try:
            urllib.request.urlretrieve(HF + rel, dst + ".part")
            os.replace(dst + ".part", dst)
            return dst
        except Exception as e:  # 网络重试
            err = e
    raise RuntimeError(f"download failed {rel}: {err}")


def main():
    info, utts, have = load()
    spk = sorted({s for _, s, _ in utts if info.get(s) == ("female", "north")})
    RNG.shuffle(spk)
    half = len(spk) // 2
    ref_spk, cal_spk = sorted(spk[:half]), sorted(spk[half:])
    json.dump({"gender": "female", "accent": "north", "reference": ref_spk,
               "calibration": cal_spk}, open(os.path.join(D, "speakers.json"), "w"), indent=1)

    ok = re.compile(r"^[一-鿿]{8,22}$")
    # ---- 400 句音素平衡句：只从校准说话人中选，贪心覆盖带调音节 / 声母 / 韵母 / 声调二元组
    cand = [(u, s, h) for u, s, h in utts if s in cal_spk and ok.match(h)]
    seen_text = set()
    cand2 = []
    for c in cand:
        if c[2] not in seen_text:
            seen_text.add(c[2]); cand2.append(c)
    RNG.shuffle(cand2)

    def units(h):
        py = toned(h)
        u = set()
        for p in py:
            u.add(("syl", p)); u.add(("base", p[:-1]))
        tones = [p[-1] for p in py]
        for a, b in zip(tones, tones[1:]):
            u.add(("tt", a + b))
        return u
    feats = [(c, units(c[2])) for c in cand2[:7000]]
    covered = collections.Counter()
    chosen, per_spk = [], collections.Counter()
    pool = list(feats)
    while len(chosen) < 400:
        best, bs = None, -1
        for i, (c, u) in enumerate(pool):
            if per_spk[c[1]] >= 16:
                continue
            sc = sum(1.0 / (1 + covered[x]) ** 2 for x in u) / (len(c[2]) ** 0.5)
            if sc > bs:
                bs, best = sc, i
        c, u = pool.pop(best)
        chosen.append(c); per_spk[c[1]] += 1
        for x in u:
            covered[x] += 1
    RNG.shuffle(chosen)
    sents = [{"id": f"s{i:03d}", "text": h, "pinyin": " ".join(toned(h)),
              "human_utt": u, "speaker": s, "split": "dev" if i < 200 else "hidden"}
             for i, (u, s, h) in enumerate(chosen)]
    json.dump(sents, open(os.path.join(D, "sentences.json"), "w"), ensure_ascii=False, indent=1)
    n_syl = len({x for _, u in feats for x in u if x[0] == "syl"})
    n_cov = len({x for x in covered if x[0] == "syl"})
    print(f"sentences: 400, toned syllables covered {n_cov}/{n_syl} in candidate pool")

    # ---- 参考池：参考说话人每人至多 12 句
    by = collections.defaultdict(list)
    for u, s, h in utts:
        if s in ref_spk and ok.match(h):
            by[s].append((u, s, h))
    ref = []
    for s in ref_spk:
        RNG.shuffle(by[s])
        ref += [{"utt": u, "speaker": s, "text": h} for u, s, h in by[s][:12]]
    json.dump(ref, open(os.path.join(D, "refpool.json"), "w"), ensure_ascii=False, indent=1)
    print("refpool:", len(ref))

    # ---- 词表：jieba 词频 >= 阈值的双字词，贪心覆盖全部带调音节（频率优先）
    import jieba
    dict_path = os.path.join(os.path.dirname(jieba.__file__), "dict.txt")
    words = []
    for l in open(dict_path, encoding="utf-8"):
        w, f = l.split()[:2]
        if len(w) == 2 and re.match(r"^[一-鿿]{2}$", w):
            words.append((int(f), w))
    words.sort(reverse=True)
    common = words[:30000]
    universe = set()
    wpy = []
    for f, w in common:
        py = toned(w)
        wpy.append((f, w, py)); universe.update(py)
    need = set(universe)
    wl = []
    for f, w, py in wpy:  # 按频率顺序，每个词只要贡献一个新音节就收
        if need & set(py):
            wl.append({"word": w, "pinyin": " ".join(py), "freq": f})
            need -= set(py)
        if not need:
            break
    json.dump(wl, open(os.path.join(D, "wordlist.json"), "w"), ensure_ascii=False, indent=1)
    print(f"wordlist: {len(wl)} words covering {len(universe)} toned syllables of top-30000 two-char words")

    # ---- T1 元音池：两组说话人各取至多 30 句额外语句（不与上面重复），只用于共振峰统计
    used = {x["human_utt"] for x in sents} | {x["utt"] for x in ref}
    byall = collections.defaultdict(list)
    for u, s, h in utts:
        if s in spk and u not in used and re.match(r"^[\u4e00-\u9fff]{4,30}$", h):
            byall[s].append((u, s, h))
    t1 = []
    for s in sorted(byall):
        RNG.shuffle(byall[s])
        t1 += [{"utt": u, "speaker": s, "text": h,
                "group": "reference" if s in ref_spk else "calibration"} for u, s, h in byall[s][:30]]
    json.dump(t1, open(os.path.join(D, "t1pool.json"), "w"), ensure_ascii=False, indent=1)
    print("t1pool:", len(t1))

    # ---- 下载录音
    rels = [have[x["human_utt"]] for x in sents] + [have[x["utt"]] for x in ref] + [have[x["utt"]] for x in t1]
    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda r: fetch(r, os.path.join(D, "wav", os.path.basename(r))), rels))
    print("downloaded", len(rels))


if __name__ == "__main__":
    main()
