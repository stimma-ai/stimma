"""Task type definitions for the generation system."""

from enum import Enum


class TaskType(str, Enum):
    """Canonical task types supported by the generation system."""

    TEXT_TO_IMAGE = "text-to-image"
    IMAGE_TO_IMAGE = "image-to-image"
    FILTER = "filter"
    IMAGE_TO_VIDEO = "image-to-video"
    TEXT_TO_VIDEO = "text-to-video"
    VIDEO_TO_VIDEO = "video-to-video"
    UPSCALE_IMAGE = "upscale-image"
    UPSCALE_VIDEO = "upscale-video"
    INPAINT_IMAGE = "inpaint-image"
    OUTPAINT_IMAGE = "outpaint-image"
    REMOVE_BACKGROUND = "remove-background"
    DETECT_OBJECTS = "detect-objects"
    VIDEO_STITCH = "video-stitch"
    VIDEO_EXTEND = "video-extend"
    LIP_SYNC = "lip-sync"
    TEXT_TO_AUDIO = "text-to-audio"
    TEXT_TO_MUSIC = "text-to-music"
    TEXT_TO_SPEECH = "text-to-speech"
    AUDIO_TO_AUDIO = "audio-to-audio"
    SPEECH_TO_TEXT = "speech-to-text"

    @classmethod
    def from_string(cls, value: str) -> "TaskType":
        """Convert a string to TaskType, with common aliases."""
        aliases = {
            "t2i": cls.TEXT_TO_IMAGE,
            "i2i": cls.IMAGE_TO_IMAGE,
            "img2img": cls.IMAGE_TO_IMAGE,
            "edit": cls.IMAGE_TO_IMAGE,
            "image-edit": cls.IMAGE_TO_IMAGE,  # backward compat alias
            "i2v": cls.IMAGE_TO_VIDEO,
            "t2v": cls.TEXT_TO_VIDEO,
            "v2v": cls.VIDEO_TO_VIDEO,
            "upscale": cls.UPSCALE_IMAGE,
            "upscale-vid": cls.UPSCALE_VIDEO,
            "video-upscale": cls.UPSCALE_VIDEO,
            "inpaint": cls.INPAINT_IMAGE,
            "outpaint": cls.OUTPAINT_IMAGE,
            "rembg": cls.REMOVE_BACKGROUND,
            "background-removal": cls.REMOVE_BACKGROUND,
            "detect": cls.DETECT_OBJECTS,
            # Audio generation: music/speech have their own task types; "text-to-audio"
            # is the lower-level case (sound effects / ambience).
            "t2a": cls.TEXT_TO_AUDIO,
            "tts": cls.TEXT_TO_SPEECH,
            "text-to-speech": cls.TEXT_TO_SPEECH,
            "text-to-music": cls.TEXT_TO_MUSIC,
            "a2a": cls.AUDIO_TO_AUDIO,
            "stt": cls.SPEECH_TO_TEXT,
        }

        normalized = value.lower().strip()
        if normalized in aliases:
            return aliases[normalized]

        # Try direct enum lookup
        for task_type in cls:
            if task_type.value == normalized:
                return task_type

        raise ValueError(f"Unknown task type: {value}")
