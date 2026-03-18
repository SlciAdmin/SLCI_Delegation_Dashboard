#!/usr/bin/env python3
"""
SLCI Voice Processor - English Only
"""
import os
import tempfile
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

_model = None

WHISPER_CONFIG = {
    'language': 'en',
    'task': 'transcribe',
    'fp16': False,
    'verbose': False,
    'temperature': (0.0, 0.2),
}

AUDIO_CONFIG = {
    'sample_rate': 16000,
    'channels': 1,
    'min_silence_len': 400,
    'silence_thresh': -45,
    'keep_silence': 100,
}

def get_model(model_name: str = None):
    global _model
    if _model is None:
        model_name = model_name or os.getenv('WHISPER_MODEL', 'base')
        for model in [model_name, 'base', 'small', 'tiny']:
            try:
                print(f"🎤 Loading Whisper model: {model}...")
                _model = whisper.load_model(model, device='cpu')
                print(f"✅ Model '{model}' loaded")
                break
            except Exception as e:
                print(f"⚠️ Could not load {model}: {e}")
                continue
        if _model is None:
            raise RuntimeError("❌ Could not load any Whisper model")
    return _model

def convert_and_normalize_audio(input_path: str) -> str:
    temp_fd, temp_path = tempfile.mkstemp(suffix='.wav')
    os.close(temp_fd)
    try:
        if PYDUB_AVAILABLE:
            audio = AudioSegment.from_file(input_path)
            audio = audio.set_channels(1).set_frame_rate(AUDIO_CONFIG['sample_rate'])
            target_db = -15
            change = target_db - audio.dBFS
            if 0 < change < 20:
                audio = audio.apply_gain(change)
            audio.export(temp_path, format='wav')
            return temp_path
        else:
            return input_path
    except:
        return input_path

def transcribe_with_retry(model, audio_path: str, max_retries: int = 3) -> Dict[str, Any]:
    last_error = None
    for attempt in range(max_retries):
        try:
            temperature = WHISPER_CONFIG['temperature'][min(attempt, len(WHISPER_CONFIG['temperature']) - 1)]
            args = {
                'audio': audio_path,
                'language': WHISPER_CONFIG['language'],
                'task': WHISPER_CONFIG['task'],
                'fp16': WHISPER_CONFIG['fp16'],
                'verbose': WHISPER_CONFIG['verbose'],
                'temperature': temperature,
            }
            clean_args = {k: v for k, v in args.items() if v is not None}
            result = model.transcribe(**clean_args)
            text = result.get('text', '').strip()
            if not text or len(text) < 2:
                raise ValueError("Empty transcription")
            return {'text': text, 'language': 'en', 'success': True, 'segments': result.get('segments', [])}
        except Exception as e:
            last_error = e
            time.sleep(0.3)
    return {'text': '', 'language': 'en', 'success': False, 'error': str(last_error)}

def process_voice_task(audio_path: str, employee_list: List[Dict] = None) -> Dict[str, Any]:
    converted_path = None
    try:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")
        
        converted_path = convert_and_normalize_audio(audio_path)
        
        if WHISPER_AVAILABLE:
            model = get_model()
            transcription = transcribe_with_retry(model, converted_path)
            
            if not transcription['success'] or not transcription['text']:
                return _fallback_task("Could not understand audio.")
            
            text = transcription['text'].strip()
            
            return {
                "title": text[:60],
                "description": text,
                "deadline": datetime.now() + timedelta(days=2),
                "priority": "medium",
                "employee_id": None,
                "employee_name": None,
                "status": "pending",
                "raw_text": text,
                "language": "en",
                "confidence": "medium"
            }
        else:
            return _fallback_task("Whisper not available")
    
    except Exception as e:
        return _fallback_task(f"Error: {str(e)}")
    
    finally:
        if converted_path and os.path.exists(converted_path) and converted_path != audio_path:
            try:
                os.remove(converted_path)
            except:
                pass

def _fallback_task(error_msg: str) -> Dict[str, Any]:
    return {
        "title": "New Voice Task",
        "description": error_msg,
        "deadline": datetime.now() + timedelta(days=2),
        "priority": "medium",
        "employee_id": None,
        "employee_name": None,
        "status": "pending",
        "raw_text": "",
        "language": "en",
        "confidence": "low"
    }