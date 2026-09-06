"""XRF session watermark research package."""

from .core import (
    CapacityError,
    Detection,
    WatermarkConfig,
    detect_watermark,
    detect_watermarks,
    embed_distributed_watermark,
    embed_watermark,
    session_tag,
)

__all__ = [
    "CapacityError",
    "Detection",
    "WatermarkConfig",
    "detect_watermark",
    "detect_watermarks",
    "embed_distributed_watermark",
    "embed_watermark",
    "session_tag",
]
