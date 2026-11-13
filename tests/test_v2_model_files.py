import numpy as np
import pytest

from app.services.v2.phone_model import PhoneModel


def test_missing_model_files_raise_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        PhoneModel(tmp_path, int8=True)
    (tmp_path / "model.int8.onnx").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):  # vocab.json still absent
        PhoneModel(tmp_path, int8=True)


def test_too_short_audio_is_rejected_before_inference():
    model = PhoneModel.__new__(PhoneModel)  # guard runs before the session is touched
    with pytest.raises(ValueError, match="too short"):
        model.log_posteriors(np.zeros(100, dtype=np.float32))
