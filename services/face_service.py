from __future__ import annotations
import os
import pickle
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np


_BACKEND = 'opencv-sface'
_DETECTOR_MODEL = 'face_detection_yunet_2023mar.onnx'
_RECOGNIZER_MODEL = 'face_recognition_sface_2021dec.onnx'
_MODEL_URLS = {
    _DETECTOR_MODEL: 'https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx',
    _RECOGNIZER_MODEL: 'https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx',
}
_MODEL_LOCK = threading.RLock()
_detector = None
_recognizer = None


def _model_directory():
    return Path(__file__).resolve().parents[1] / 'instance' / 'models'


def _download_model(filename, url):
    destination = _model_directory() / filename
    if destination.is_file() and destination.stat().st_size > 1024:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent) as temporary_file:
                temporary_path = Path(temporary_file.name)
                shutil.copyfileobj(response, temporary_file)
        if temporary_path.stat().st_size <= 1024:
            raise RuntimeError(f'Downloaded face model is incomplete: {filename}')
        os.replace(temporary_path, destination)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError('Unable to download the OpenCV face models. Check your internet connection and try again.') from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def _get_models():
    global _detector, _recognizer
    if _detector is not None and _recognizer is not None:
        return _detector, _recognizer
    if not available():
        raise RuntimeError('OpenCV face recognition is unavailable. Install opencv-python 4.10 or later.')

    with _MODEL_LOCK:
        if _detector is None or _recognizer is None:
            detector_path = _download_model(_DETECTOR_MODEL, _MODEL_URLS[_DETECTOR_MODEL])
            recognizer_path = _download_model(_RECOGNIZER_MODEL, _MODEL_URLS[_RECOGNIZER_MODEL])
            _detector = cv2.FaceDetectorYN_create(str(detector_path), '', (320, 320))
            _recognizer = cv2.FaceRecognizerSF_create(str(recognizer_path), '')
    return _detector, _recognizer


def available():
    return hasattr(cv2, 'FaceDetectorYN_create') and hasattr(cv2, 'FaceRecognizerSF_create')


def _extract_encoding(image_bytes):
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('The uploaded image could not be read')

    with _MODEL_LOCK:
        detector, recognizer = _get_models()
        detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = detector.detect(image)
        if faces is None or len(faces) != 1:
            raise ValueError('Exactly one face must be visible')
        aligned = recognizer.alignCrop(image, faces)
        return recognizer.feature(aligned)


def encode_image(image_bytes):
    encoding = _extract_encoding(image_bytes)
    return pickle.dumps({'backend': _BACKEND, 'encoding': encoding}, protocol=pickle.HIGHEST_PROTOCOL)


def unpack_encoding(blob):
    return pickle.loads(blob)


def encoding_distance(blob, encoding):
    stored = unpack_encoding(blob)
    if not isinstance(stored, dict) or stored.get('backend') != _BACKEND:
        raise ValueError('This employee has an older face sample. Register their face again.')
    with _MODEL_LOCK:
        _, recognizer = _get_models()
        similarity = recognizer.match(stored['encoding'], encoding, cv2.FaceRecognizerSF_FR_COSINE)
    return 1.0 - float(similarity)


def recognize_image(image_bytes, threshold=0.50):
    return _extract_encoding(image_bytes), None
