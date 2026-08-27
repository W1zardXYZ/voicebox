"""Regression tests for spec §2 (device handling / "GPU string" bug) and §3
(unload-on-switch memory policy).

The core regression: no backend may ever pass a bare device string ("cuda",
"mps", "xpu") as ``device_map`` to ``from_pretrained`` — transformers forwards
``device_map`` to accelerate, which treats a string as a special mode and
trips GPU inference ("GPU string" family of errors). The robust convention is
load-on-CPU + ``model.to(device)``.
"""

import pytest

from backend.backends import base as base_mod
from backend.backends.base import (
    build_model_kwargs,
    engine_device_policy,
    engine_platform_note,
    get_torch_device,
    mps_is_available,
)


# -- §2.4: build_model_kwargs never emits a bare device_map -----------------


def test_build_model_kwargs_never_contains_device_map():
    for device in ("cpu", "cuda", "mps", "xpu"):
        kwargs = build_model_kwargs(device)
        assert "device_map" not in kwargs, f"device_map must never be passed for {device}"
        assert "device" not in kwargs, f"from_pretrained has no device= kwarg ({device})"


def test_build_model_kwargs_cpu_uses_float32():
    import torch

    kwargs = build_model_kwargs("cpu", low_cpu_mem_usage=False)
    assert kwargs["torch_dtype"] is torch.float32
    assert kwargs["low_cpu_mem_usage"] is False


def test_build_model_kwargs_accelerator_uses_bf16_by_default():
    import torch

    kwargs = build_model_kwargs("cuda")
    assert kwargs["torch_dtype"] is torch.bfloat16
    kwargs = build_model_kwargs("mps", torch.float16)
    assert kwargs["torch_dtype"] is torch.float16


def test_load_model_to_device_is_noop_on_cpu():
    class _Fake:
        def to(self, device):
            self.moved_to = device
            return self

    cpu_model = _Fake()
    out = base_mod.load_model_to_device(cpu_model, "cpu")
    assert out is cpu_model
    assert not hasattr(cpu_model, "moved_to")

    gpu_model = _Fake()
    out = base_mod.load_model_to_device(gpu_model, "mps")
    assert out.moved_to == "mps"


# -- §2.4.3: Qwen may use MPS on Apple Silicon -----------------------------


def test_engine_device_policy_lets_qwen_use_mps():
    for engine in ("qwen", "qwen_custom_voice"):
        policy = engine_device_policy(engine)
        assert policy.get("allow_mps") is True
        assert policy.get("allow_xpu") is True
        assert policy.get("allow_directml") is True


def test_qwen_backends_resolve_device_via_policy(monkeypatch):
    """Both Qwen backends must resolve their device through the shared policy
    table so the Models-pane note can never drift from reality."""
    from backend.backends import pytorch_backend, qwen_custom_voice_backend

    calls: list[dict] = []

    def fake_get_torch_device(**kwargs):
        calls.append(kwargs)
        return "cpu"

    # The backends bind get_torch_device into their own module namespace at
    # import time — patch those references, not base's.
    monkeypatch.setattr(pytorch_backend, "get_torch_device", fake_get_torch_device)
    monkeypatch.setattr(qwen_custom_voice_backend, "get_torch_device", fake_get_torch_device)

    pytorch_backend.PyTorchTTSBackend()
    qwen_custom_voice_backend.QwenCustomVoiceBackend()

    assert len(calls) == 2
    for kwargs in calls:
        assert kwargs.get("allow_mps") is True


@pytest.mark.skipif(not mps_is_available(), reason="MPS not available")
def test_get_torch_device_returns_mps_when_available():
    assert get_torch_device(allow_mps=True) == "mps"


# -- §1.3: engine_platform_note --------------------------------------------


def test_engine_platform_note_apple_silicon(monkeypatch):
    monkeypatch.setattr(base_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(base_mod.platform, "machine", lambda: "arm64")

    supported, note = engine_platform_note("qwen")
    assert supported is True
    assert note == "Uses the Apple GPU (MPS)"

    supported, note = engine_platform_note("chatterbox")
    assert supported is True
    assert note == "Runs on CPU on Apple Silicon (no Metal path)"

    supported, note = engine_platform_note("kokoro")
    assert supported is True
    assert "CPU" in note


def test_engine_platform_note_linux(monkeypatch):
    monkeypatch.setattr(base_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(base_mod.platform, "machine", lambda: "x86_64")

    supported, note = engine_platform_note("qwen")
    assert supported is True
    assert note is None


# -- §3: single-active-engine unload policy ---------------------------------


class _FakeBackend:
    def __init__(self, name: str):
        self.name = name
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def unload_model(self):
        self.loaded = False

    async def load_model_async(self, model_size=None):
        self.loaded = True

    async def load_model(self):
        self.loaded = True


def _reset_tts_backends():
    from backend.backends import _tts_backends, _tts_backends_lock

    with _tts_backends_lock:
        _tts_backends.clear()


def test_unload_other_tts_engines_keeps_target():
    from backend.backends import _unload_other_tts_engines, _tts_backends, _tts_backends_lock

    try:
        with _tts_backends_lock:
            qwen, chatter = _FakeBackend("qwen"), _FakeBackend("chatterbox")
            qwen.loaded = True
            _tts_backends["qwen"] = qwen
            _tts_backends["chatterbox"] = chatter

        _unload_other_tts_engines("qwen")

        assert qwen.loaded is True, "target engine must not be unloaded"
        assert chatter.loaded is False, "other engines must be unloaded"
    finally:
        _reset_tts_backends()


@pytest.mark.asyncio
async def test_load_engine_model_unloads_previous_engine():
    from backend.backends import _tts_backends, _tts_backends_lock, load_engine_model

    try:
        with _tts_backends_lock:
            qwen, chatter = _FakeBackend("qwen"), _FakeBackend("chatterbox")
            qwen.loaded = True
            _tts_backends["qwen"] = qwen
            _tts_backends["chatterbox"] = chatter

        await load_engine_model("chatterbox")

        assert qwen.loaded is False, "previous engine unloaded on switch"
        assert chatter.loaded is True, "new engine loaded"
    finally:
        _reset_tts_backends()


@pytest.mark.asyncio
async def test_load_engine_model_same_engine_is_noop_unload():
    from backend.backends import _tts_backends, _tts_backends_lock, load_engine_model

    try:
        with _tts_backends_lock:
            qwen = _FakeBackend("qwen")
            qwen.loaded = True
            _tts_backends["qwen"] = qwen

        await load_engine_model("qwen")

        assert qwen.loaded is True
    finally:
        _reset_tts_backends()
