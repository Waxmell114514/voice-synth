"""评估器模型封装。所有模型从 eval/models/ 本地加载，CPU 推理，确定性。"""
import os, sys, json, functools
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
M = os.path.join(ROOT, "models")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _torch():
    import torch
    torch.set_num_threads(int(os.environ.get("EVAL_THREADS", "4")))
    torch.manual_seed(0)
    return torch


def resample(x, sr, to=16000):
    if sr == to:
        return x.astype(np.float32)
    from scipy.signal import resample_poly
    g = np.gcd(int(sr), int(to))
    return resample_poly(x, to // g, sr // g).astype(np.float32)


def load_wav(path, to=16000):
    import soundfile as sf
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    return resample(x.mean(1), sr, to)


# ---------------------------------------------------------------- ASR
class SherpaASR:
    def __init__(self, kind):
        import sherpa_onnx
        if kind == "paraformer":
            d = os.path.join(M, "csukuangfj__sherpa-onnx-paraformer-zh-2024-03-09")
            self.r = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=os.path.join(d, "model.int8.onnx"), tokens=os.path.join(d, "tokens.txt"),
                num_threads=int(os.environ.get("EVAL_THREADS", "4")), decoding_method="greedy_search")
        elif kind == "sensevoice":
            d = os.path.join(M, "csukuangfj__sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09")
            self.r = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=os.path.join(d, "model.int8.onnx"), tokens=os.path.join(d, "tokens.txt"),
                num_threads=int(os.environ.get("EVAL_THREADS", "4")), language="zh", use_itn=False)
        else:
            raise ValueError(kind)

    def __call__(self, wavs):
        ss = []
        for w in wavs:
            s = self.r.create_stream()
            s.accept_waveform(16000, w)
            ss.append(s)
        self.r.decode_streams(ss)
        return [s.result.text for s in ss]


class WhisperASR:
    def __init__(self, kind):
        from faster_whisper import WhisperModel
        d = {"whisper-small": "Systran__faster-whisper-small",
             "whisper-turbo": "deepdml__faster-whisper-large-v3-turbo-ct2"}[kind]
        self.m = WhisperModel(os.path.join(M, d), device="cpu", compute_type="int8",
                              cpu_threads=int(os.environ.get("EVAL_THREADS", "4")))

    def __call__(self, wavs):
        out = []
        for w in wavs:
            segs, _ = self.m.transcribe(w, language="zh", beam_size=1, temperature=0.0,
                                        condition_on_previous_text=False, vad_filter=False,
                                        initial_prompt="以下是普通话的句子。")
            out.append("".join(s.text for s in segs))
        return out


def make_asr(kind):
    return SherpaASR(kind) if kind in ("paraformer", "sensevoice") else WhisperASR(kind)


# ---------------------------------------------------------------- MOS
class UTMOS:
    def __init__(self, kind):
        torch = _torch()
        from transformers import AutoModel
        d = {"utmos22": "prj-beatrice__utmos22-torch-native",
             "utmosv2": "prj-beatrice__utmosv2-torch-native"}[kind]
        self.kind = kind
        self.m = AutoModel.from_pretrained(os.path.join(M, d), trust_remote_code=True).eval()

    def __call__(self, wavs):
        torch = _torch()
        out = []
        with torch.inference_mode():
            for w in wavs:
                torch.manual_seed(0)
                out.append(float(self.m(torch.from_numpy(w), sampling_rate=16000).scores[0]))
        return out


# ---------------------------------------------------------------- 反欺骗：返回“判为真人”的概率
class AASIST:
    def __init__(self):
        torch = _torch()
        sys.path.insert(0, M)
        from clovaai_AASIST import Model
        cfg = json.load(open(os.path.join(M, "clovaai_AASIST.conf")))["model_config"]
        self.m = Model(cfg).eval()
        self.m.load_state_dict(torch.load(os.path.join(M, "clovaai_AASIST.pth"), map_location="cpu"))
        self.n = cfg["nb_samp"]

    def __call__(self, wavs):
        torch = _torch()
        out = []
        with torch.inference_mode():
            for w in wavs:
                # 与官方 eval 一致：取前 64600 点，不足则循环补齐
                if len(w) < self.n:
                    w = np.tile(w, int(np.ceil(self.n / max(len(w), 1))))
                x = torch.from_numpy(w[: self.n].copy()).float()[None]
                _, o = self.m(x)
                out.append(float(torch.softmax(o, -1)[0, 1]))
        return out


class W2VDetector:
    def __init__(self, dirname="MelodyMachine__Deepfake-audio-detection-V2"):
        torch = _torch()
        from transformers import AutoModelForAudioClassification, AutoFeatureExtractor
        d = os.path.join(M, dirname)
        self.fe = AutoFeatureExtractor.from_pretrained(d)
        self.m = AutoModelForAudioClassification.from_pretrained(d).eval()
        self.real = int([k for k, v in self.m.config.id2label.items() if v == "real"][0])

    def __call__(self, wavs):
        torch = _torch()
        out = []
        with torch.inference_mode():
            for w in wavs:
                x = self.fe(w, sampling_rate=16000, return_tensors="pt")
                out.append(float(torch.softmax(self.m(**x).logits, -1)[0, self.real]))
        return out


def make_detector(kind):
    if kind == "aasist":
        return AASIST()
    if kind == "xlsr-deepfake":
        return W2VDetector("Gustking__wav2vec2-large-xlsr-deepfake-audio-classification")
    return W2VDetector()


# ---------------------------------------------------------------- 自监督嵌入（句级均值池化，取中间层）
class SSLEmbed:
    def __init__(self, kind):
        torch = _torch()
        from transformers import AutoModel, AutoFeatureExtractor
        d = {"chinese-hubert-base": "TencentGameMate__chinese-hubert-base",
             "wavlm-base-plus": "microsoft__wavlm-base-plus"}[kind]
        d = os.path.join(M, d)
        self.fe = AutoFeatureExtractor.from_pretrained(d)
        self.m = AutoModel.from_pretrained(d).eval()
        self.layer = 6

    def __call__(self, wavs):
        torch = _torch()
        out = []
        with torch.inference_mode():
            for w in wavs:
                x = self.fe(w, sampling_rate=16000, return_tensors="pt")
                h = self.m(x.input_values, output_hidden_states=True).hidden_states[self.layer][0]
                out.append(h.mean(0).numpy().astype(np.float64))
        return np.stack(out)


SUITES = {
    # 开发组 / 终审组，互不重叠（阶段 0.3 校准后确定）
    "dev": {"asr": "paraformer", "mos": "utmos22", "det": "aasist", "ssl": "chinese-hubert-base"},
    "final": {"asr": "sensevoice", "mos": "utmosv2", "det": "w2v-deepfake", "ssl": "wavlm-base-plus"},
}


_CAL = os.path.join(ROOT, "data", "calibration.json")
if os.path.exists(_CAL):
    _c = json.load(open(_CAL))
    if "suites" in _c:
        SUITES = _c["suites"]


@functools.lru_cache(None)
def get(role, kind):
    return {"asr": make_asr, "mos": UTMOS, "det": make_detector, "ssl": SSLEmbed}[role](kind)
