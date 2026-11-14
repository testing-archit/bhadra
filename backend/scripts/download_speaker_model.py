"""Install the pinned WeSpeaker voice embedding model for local inference."""

import hashlib
import urllib.request
from pathlib import Path

URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx"
)
SHA256 = "5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94"
DESTINATION = Path(__file__).resolve().parent.parent / "models" / "wespeaker_en_voxceleb_resnet34.onnx"


def main() -> None:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if DESTINATION.is_file() and hashlib.sha256(DESTINATION.read_bytes()).hexdigest() == SHA256:
        return
    pending = DESTINATION.with_suffix(".download")
    urllib.request.urlretrieve(URL, pending)
    if hashlib.sha256(pending.read_bytes()).hexdigest() != SHA256:
        pending.unlink(missing_ok=True)
        raise RuntimeError("Voice model download did not match the pinned SHA-256")
    pending.replace(DESTINATION)


if __name__ == "__main__":
    main()
