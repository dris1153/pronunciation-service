"""Pydantic models for API request/response schemas."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────────────────────


class PronunciationLevel(str, Enum):
    """Overall pronunciation quality level."""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class ErrorType(str, Enum):
    """Word-level error classification (Azure-compatible)."""
    NONE = "None"
    MISPRONUNCIATION = "Mispronunciation"
    OMISSION = "Omission"
    INSERTION = "Insertion"
    UNEXPECTED_BREAK = "UnexpectedBreak"
    MISSING_BREAK = "MissingBreak"


# ── Unified per-phoneme / per-word result models ─────────────────────────────


class PhonemeResult(BaseModel):
    """Unified per-phoneme result combining IPA comparison and GOP scoring."""
    expected_ipa: str = Field(..., description="Expected IPA phoneme from reference")
    actual_ipa: str = Field(..., description="Actual IPA phoneme from speech")
    is_correct_ipa: bool = Field(..., description="Whether the phoneme matches")
    confidence_ipa: float = Field(
        ..., ge=0.0, le=1.0, description="Phoneme similarity confidence (0–1)"
    )
    gop_score: float = Field(..., description="GOP log-posterior score (0–100)")
    gop_quality: PronunciationLevel = Field(..., description="GOP quality level")


class WordResult(BaseModel):
    """Unified per-word result combining IPA and GOP information."""
    word: str = Field(..., description="The reference word")
    expected_ipa: str = Field(..., description="Expected IPA transcription")
    actual_ipa: str = Field(..., description="Actual IPA from speech")
    phoneme_details: list[PhonemeResult] = Field(
        default_factory=list, description="Per-phoneme IPA + GOP detail"
    )
    ipa_accuracy: float = Field(
        ..., ge=0.0, le=100.0, description="Word-level IPA accuracy (%)"
    )
    word_gop_score: float = Field(..., description="Average GOP score for this word (0–100)")
    word_gop_quality: PronunciationLevel = Field(
        ..., description="GOP quality level for this word"
    )
    error_type: ErrorType = Field(
        default=ErrorType.NONE,
        description=(
            "Word-level error classification: None, Mispronunciation, "
            "Omission, Insertion, UnexpectedBreak, or MissingBreak"
        ),
    )


class EvaluationResult(BaseModel):
    """Combined IPA + GOP evaluation result (top-level ``results`` field)."""
    reference_ipa: str = Field(..., description="Full reference IPA string")
    actual_ipa: str = Field(..., description="Full actual IPA string")
    word_details: list[WordResult] = Field(
        default_factory=list, description="Per-word combined IPA + GOP analysis"
    )
    overall_ipa_accuracy: float = Field(
        ..., ge=0.0, le=100.0, description="Overall IPA accuracy (%)"
    )
    overall_gop_score: float = Field(..., description="Overall GOP score (0–100)")
    overall_gop_quality: PronunciationLevel = Field(..., description="Overall GOP quality level")


# ── Internal-only models (used by GOPService; not exposed in /evaluate) ──────


class PhonemeGOP(BaseModel):
    """GOP score for an individual phoneme — used internally by GOPService."""
    phoneme: str
    gop_score: float = Field(..., description="Log-posterior GOP score (0–100)")
    quality: PronunciationLevel


class WordGOP(BaseModel):
    """GOP score for a single word — used internally by GOPService."""
    word: str
    phoneme_scores: list[PhonemeGOP] = Field(default_factory=list)
    word_gop_score: float
    quality: PronunciationLevel
    start_frame: int = Field(0, description="First CTC frame of this word (inclusive)")
    end_frame: int = Field(0, description="Last CTC frame of this word (exclusive)")


class GOPResult(BaseModel):
    """Full GOP scoring result — used internally by GOPService."""
    word_scores: list[WordGOP] = Field(default_factory=list)
    overall_gop_score: float
    overall_quality: PronunciationLevel
    sample_rate: int = Field(16000, description="Audio sample rate used for frame conversion")
    total_frames: int = Field(0, description="Total CTC frames in the emission matrix")


class ProsodyResult(BaseModel):
    """Prosody analysis result — used internally by ProsodyService."""
    pitch_mean_hz: float = Field(0.0, description="Mean f0 of voiced frames (Hz)")
    pitch_std_hz: float = Field(0.0, description="Std-dev of f0 of voiced frames (Hz)")
    pitch_range_semitones: float = Field(
        0.0, description="Pitch range in semitones (max − min of voiced f0)"
    )
    voiced_ratio: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Fraction of frames classified as voiced",
    )
    is_monotone: bool = Field(False, description="True if pitch CV < monotone threshold")
    prosody_score: float = Field(
        0.0, ge=0.0, le=100.0, description="Overall prosody quality score (0–100)"
    )


# ── API Schemas ──────────────────────────────────────────────────────────────


class PronunciationRequest(BaseModel):
    """Body when reference text is sent as form field (audio as file upload)."""
    reference_text: str = Field(
        ..., min_length=1, max_length=500, description="Reference text to compare"
    )


class PronunciationResponse(BaseModel):
    """Unified evaluation response."""
    reference_text: str
    transcribed_text: str
    results: EvaluationResult = Field(..., description="Combined IPA and GOP analysis")
    accuracy_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Phoneme-level pronunciation accuracy (55% IPA + 45% GOP)",
    )
    completeness_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Ratio of pronounced words to reference text (%)",
    )
    fluency_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Speech fluency based on timing, pauses, and speech rate (0–100)",
    )
    prosody_score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Prosody quality based on pitch variation, range, and intonation (0–100)",
    )
    overall_score: float = Field(
        ..., ge=0.0, le=100.0, description="Combined overall score"
    )
    level: PronunciationLevel
    feedback: str = Field(..., description="Human-readable feedback")


# ── v2 (additive: same keys as v1 plus word timing) ──────────────────────────


class WordResultV2(WordResult):
    start_ms: int = Field(..., ge=0, description="Word start in the audio (ms)")
    end_ms: int = Field(..., ge=0, description="Word end in the audio (ms)")


class EvaluationResultV2(EvaluationResult):
    word_details: list[WordResultV2] = Field(
        default_factory=list, description="Per-word combined IPA + GOP analysis with timing"
    )


class PronunciationResponseV2(PronunciationResponse):
    """v1 response shape. ``transcribed_text`` is the heard IPA string, not words."""
    results: EvaluationResultV2 = Field(..., description="Combined IPA and GOP analysis")


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    model_loaded: bool


# ── IPA / Phoneme conversion ────────────────────────────────────────────────


class WordIPADetail(BaseModel):
    """IPA breakdown for a single word."""
    word: str = Field(..., description="Original word")
    ipa: str = Field(..., description="IPA transcription")
    phonemes: list[str] = Field(..., description="List of IPA phoneme tokens")


class IPAConvertResponse(BaseModel):
    """Response for text → IPA conversion."""
    text: str = Field(..., description="Original input text (normalised)")
    ipa: str = Field(..., description="Full IPA transcription (space-separated words)")
    words: list[WordIPADetail] = Field(..., description="Per-word IPA breakdown")


# ── Transcription ────────────────────────────────────────────────────────────


class TranscribeResponse(BaseModel):
    """Response for audio → text transcription."""
    transcription: str = Field(..., description="Transcribed text from audio")
    duration_sec: float = Field(..., description="Audio duration in seconds")


# ── Model info ───────────────────────────────────────────────────────────────


class ModelInfoResponse(BaseModel):
    """Service metadata and capabilities."""
    app_name: str
    app_version: str
    asr_model: str = Field(..., description="HuggingFace model identifier")
    device: str = Field(..., description="Compute device (cpu / cuda)")
    sample_rate: int = Field(..., description="Expected audio sample rate (Hz)")
    max_duration_sec: int = Field(..., description="Maximum audio duration (seconds)")
    max_upload_mb: int = Field(..., description="Maximum upload file size (MB)")
    supported_formats: list[str] = Field(
        ..., description="Supported audio MIME types"
    )


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
