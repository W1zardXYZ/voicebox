"""ORM model definitions for the voicebox SQLite database."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

from ..utils.capture_chords import (
    default_push_to_talk_chord,
    default_toggle_to_talk_chord,
)

Base = declarative_base()


class VoiceProfile(Base):
    """Voice profile.

    voice_type discriminates three flavours:
      - "cloned"   — traditional reference-audio profiles (all cloning engines)
      - "preset"   — engine-specific pre-built voice (e.g. Kokoro voices)
      - "designed"  — text-described voice (e.g. Qwen CustomVoice, future)
    """

    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    language = Column(String, default="en")
    avatar_path = Column(String, nullable=True)
    effects_chain = Column(Text, nullable=True)

    # Voice type system — added v0.3.x
    voice_type = Column(String, default="cloned")  # "cloned" | "preset" | "designed"
    preset_engine = Column(String, nullable=True)  # e.g. "kokoro" — only for preset
    preset_voice_id = Column(String, nullable=True)  # e.g. "am_adam" — only for preset
    design_prompt = Column(Text, nullable=True)  # text description — only for designed
    default_engine = Column(String, nullable=True)  # auto-selected engine, locked for preset
    # Free-form character prompt used by the compose button and the
    # personality-rewrite path on /generate. Describes *what* this voice
    # says and how, orthogonal to how it sounds (handled by the preset /
    # cloning metadata above).
    personality = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProfileSample(Base):
    """Audio sample attached to a voice profile."""

    __tablename__ = "profile_samples"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    audio_path = Column(String, nullable=False)
    reference_text = Column(Text, nullable=False)


class Generation(Base):
    """A single TTS generation."""

    __tablename__ = "generations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    text = Column(Text, nullable=False)
    language = Column(String, default="en")
    audio_path = Column(String, nullable=True)
    duration = Column(Float, nullable=True)
    seed = Column(Integer)
    instruct = Column(Text)
    engine = Column(String, default="qwen")
    model_size = Column(String, nullable=True)
    status = Column(String, default="completed")
    error = Column(Text, nullable=True)
    is_favorited = Column(Boolean, default=False)
    # Origin of this generation — "manual" for plain /generate calls,
    # "personality_speak" for rows whose text was rewritten through the
    # profile's personality LLM before TTS. Future sources (bulk import,
    # agent replies, etc.) can extend this.
    source = Column(String, nullable=False, default="manual")
    created_at = Column(DateTime, default=datetime.utcnow)


class Story(Base):
    """A story that sequences multiple generations."""

    __tablename__ = "stories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    # Default voice for segments without an explicit speaker (spec §4.2).
    default_voice_profile_id = Column(String, ForeignKey("profiles.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoryChapter(Base):
    """A chapter inside a story (spec §4 — ElevenLabs-style hierarchy).

    Chapters are optional: legacy stories are flat lists of StoryItems with no
    chapters or segments. When present, a story is
    ``Story → Chapter → Segment → Generation/StoryItem``.
    """

    __tablename__ = "story_chapters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id = Column(String, ForeignKey("stories.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    # The markdown slice this chapter was segmented from (informational).
    source = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StorySegment(Base):
    """A chunk of story text with an assignable speaker (spec §4).

    ``text`` is the narration/dialogue to synthesize. ``profile_id`` assigns a
    voice (None → story default voice). When generated, ``generation_id``
    points at the resulting Generation row and ``status`` tracks the
    draft→queued→generating→completed|error lifecycle.
    """

    __tablename__ = "story_segments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chapter_id = Column(String, ForeignKey("story_chapters.id"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True)
    engine = Column(String, nullable=True)
    model_size = Column(String, nullable=True)
    language = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft|queued|generating|completed|error
    generation_id = Column(String, ForeignKey("generations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StoryItem(Base):
    """Links a generation to a story at a specific timecode."""

    __tablename__ = "story_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    story_id = Column(String, ForeignKey("stories.id"), nullable=False)
    generation_id = Column(String, ForeignKey("generations.id"), nullable=False)
    version_id = Column(String, ForeignKey("generation_versions.id"), nullable=True)
    start_time_ms = Column(Integer, nullable=False, default=0)
    track = Column(Integer, nullable=False, default=0)
    trim_start_ms = Column(Integer, nullable=False, default=0)
    trim_end_ms = Column(Integer, nullable=False, default=0)
    volume = Column(Float, nullable=False, default=1.0)
    # Optional trace-back from a timeline clip to its story segment (spec §4.2).
    story_segment_id = Column(String, ForeignKey("story_segments.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Project(Base):
    """Audio studio project (JSON blob)."""

    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GenerationVersion(Base):
    """A version of a generation's audio (original, processed, alternate takes)."""

    __tablename__ = "generation_versions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    generation_id = Column(String, ForeignKey("generations.id"), nullable=False)
    label = Column(String, nullable=False)
    audio_path = Column(String, nullable=False)
    effects_chain = Column(Text, nullable=True)
    source_version_id = Column(String, ForeignKey("generation_versions.id"), nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EffectPreset(Base):
    """Saved effect chain preset."""

    __tablename__ = "effect_presets"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    effects_chain = Column(Text, nullable=False)
    is_builtin = Column(Boolean, default=False)
    sort_order = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)


class AudioChannel(Base):
    """Audio output channel (bus)."""

    __tablename__ = "audio_channels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChannelDeviceMapping(Base):
    """Mapping between a channel and an OS audio device."""

    __tablename__ = "channel_device_mappings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    channel_id = Column(String, ForeignKey("audio_channels.id"), nullable=False)
    device_id = Column(String, nullable=False)


class ProfileChannelMapping(Base):
    """Many-to-many mapping between voice profiles and audio channels."""

    __tablename__ = "profile_channel_mappings"

    profile_id = Column(String, ForeignKey("profiles.id"), primary_key=True)
    channel_id = Column(String, ForeignKey("audio_channels.id"), primary_key=True)


class CaptureSettings(Base):
    """Singleton row holding user defaults for the capture/refine flow.

    Kept server-side so every window, CLI client, and API consumer reads the
    same preferences. The ``id`` column is always 1.
    """

    __tablename__ = "capture_settings"

    id = Column(Integer, primary_key=True, default=1)
    stt_model = Column(String, nullable=False, default="turbo")
    stt_engine = Column(String, nullable=False, default="whisper")  # whisper | parakeet
    language = Column(String, nullable=False, default="auto")
    auto_refine = Column(Boolean, nullable=False, default=True)
    llm_model = Column(String, nullable=False, default="0.6B")
    smart_cleanup = Column(Boolean, nullable=False, default=True)
    self_correction = Column(Boolean, nullable=False, default=True)
    preserve_technical = Column(Boolean, nullable=False, default=True)
    allow_auto_paste = Column(Boolean, nullable=False, default=True)
    default_playback_voice_id = Column(String, nullable=True)
    # Default OFF — opting in is what triggers the macOS Input Monitoring TCC
    # prompt. We deliberately don't spawn the global keyboard tap until the
    # user flips this on so a fresh-install user doesn't see a scary
    # "Voicebox would like to receive keystrokes from any application" dialog
    # before they've even opened the Captures tab.
    hotkey_enabled = Column(Boolean, nullable=False, default=False)
    # Lists of keytap key names (e.g. "MetaRight", "ControlRight"). Right-hand
    # modifiers by default so they don't collide with left-hand shortcuts.
    chord_push_to_talk_keys = Column(JSON, nullable=False, default=default_push_to_talk_chord)
    chord_toggle_to_talk_keys = Column(JSON, nullable=False, default=default_toggle_to_talk_chord)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GenerationSettings(Base):
    """Singleton row for long-form TTS generation preferences."""

    __tablename__ = "generation_settings"

    id = Column(Integer, primary_key=True, default=1)
    max_chunk_chars = Column(Integer, nullable=False, default=800)
    crossfade_ms = Column(Integer, nullable=False, default=50)
    normalize_audio = Column(Boolean, nullable=False, default=True)
    autoplay_on_generate = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CloudSettings(Base):
    """Singleton row holding the link to a Voicebox Cloud account.

    Populated by the "Log in with browser" pairing flow (see services/cloud.py):
    the browser hands back a one-time code, which the backend exchanges for an
    ``api_key`` it stores here. The key is a bearer credential for
    api.voicebox.sh — auth only, never an encryption key (E2E key material lives
    elsewhere). Stored in the local app database alongside the user's other data;
    moving it to the OS keychain is a future hardening step. The ``id`` is
    always 1; a null ``api_key`` means "not connected".
    """

    __tablename__ = "cloud_settings"

    id = Column(Integer, primary_key=True, default=1)
    api_key = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    account_user_id = Column(String, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MCPClientBinding(Base):
    """Per-MCP-client settings (voice profile, engine, personality default).

    Lets users bind distinct voices to distinct agents — e.g. Claude Code
    speaks in "Morgan," Cursor in "Scarlett." The MCP client identifies
    itself via the ``X-Voicebox-Client-Id`` HTTP header; direct-HTTP
    clients set it in their MCP config's ``headers`` block, the stdio
    shim forwards it from the ``VOICEBOX_CLIENT_ID`` env var.
    """

    __tablename__ = "mcp_client_bindings"

    client_id = Column(String, primary_key=True)
    label = Column(String, nullable=True)  # display name
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True)
    default_engine = Column(String, nullable=True)
    # When true, voicebox.speak routes through the profile's personality LLM
    # (rewrite) before TTS by default. Callers can still override per call.
    default_personality = Column(Boolean, nullable=False, default=False)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Capture(Base):
    """A single voice input capture (dictation, recording, or uploaded file).

    Stores the original audio alongside the raw transcript and, optionally, a
    refined version produced by the LLM. Refinement flags are serialized as
    JSON so we can reproduce the prompt that generated the refined text.
    """

    __tablename__ = "captures"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audio_path = Column(String, nullable=False)
    source = Column(String, nullable=False, default="file")  # dictation | recording | file
    language = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    transcript_raw = Column(Text, nullable=False, default="")
    transcript_refined = Column(Text, nullable=True)
    stt_model = Column(String, nullable=True)
    stt_engine = Column(String, nullable=True, default="whisper")  # whisper | parakeet
    llm_model = Column(String, nullable=True)
    refinement_flags = Column(Text, nullable=True)  # JSON blob
    created_at = Column(DateTime, default=datetime.utcnow)


class PronunciationDictionary(Base):
    """Pronunciation override for a specific word.

    ``phonemes`` holds IPA or CMU Arpabet for the term. Applied upstream of TTS
    so technical terms / proper nouns / acronyms are synthesized as intended.
    """

    __tablename__ = "pronunciation_dictionary"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    word = Column(String, unique=True, nullable=False, index=True)
    phonemes = Column(Text, nullable=False)
    language = Column(String, default="ALL")  # "ALL" applies to every language
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DubbingProject(Base):
    """A dubbing project: one source media file being translated to a target
    language, with per-speaker voice assignment."""

    __tablename__ = "dubbing_projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    status = Column(String, default="draft")  # draft | processing | ready | failed
    stage = Column(String, nullable=True)  # extract | transcribe | diarize | translate | synthesize | assemble
    source_language = Column(String, nullable=False, default="en")
    target_language = Column(String, nullable=False, default="en")
    source_path = Column(String, nullable=True)  # original media file
    dubbed_audio_path = Column(String, nullable=True)  # assembled output
    dubbed_video_path = Column(String, nullable=True)  # muxed MP4 (m03 export)
    duration = Column(Float, default=0.0)
    translation_style = Column(String, default="Natural")
    stt_engine = Column(String, default="parakeet")  # whisper | parakeet
    translation_model = Column(String, nullable=True)  # Qwen3 LLM size: 0.6B | 1.7B | 4B
    voice_source = Column(String, nullable=True, default=None)  # "auto" | "default" | profile id
    default_voice_profile_id = Column(String, nullable=True)
    prosody_preserve = Column(Boolean, nullable=False, default=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DubbingSpeaker(Base):
    """A speaker detected by diarization, mapped to a Voicebox voice profile
    (or left to the default) for synthesis."""

    __tablename__ = "dubbing_speakers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dubbing_projects.id"), nullable=False, index=True)
    label = Column(String, nullable=False)  # e.g. "SPEAKER_00"
    voice_profile_id = Column(String, nullable=True)  # FK to profiles.id (optional)
    preset_engine = Column(String, nullable=True)  # e.g. "kokoro" if using a preset
    preset_voice_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DubbingSegment(Base):
    """A single translated+dubbed segment on the timeline."""

    __tablename__ = "dubbing_segments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("dubbing_projects.id"), nullable=False, index=True)
    speaker_id = Column(String, ForeignKey("dubbing_speakers.id"), nullable=True)
    sequence_index = Column(Integer, nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    source_text = Column(Text, nullable=False, default="")
    translated_text = Column(Text, nullable=True)
    target_char_min = Column(Integer, default=0)
    target_char_max = Column(Integer, default=0)
    pace_multiplier = Column(Float, default=1.0)
    alignment = Column(String, default="start")  # start | center | end
    auto_stretch = Column(Boolean, default=False)
    prosody_annotation = Column(Text, nullable=True)  # director's-script instruct
    source_wps = Column(Float, nullable=True)  # measured source speaking rate
    is_locked = Column(Boolean, default=False)
    source_audio_path = Column(String, nullable=True)
    synthesized_audio_path = Column(String, nullable=True)
    is_dirty = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
