"""AI Video Assistant — transcribe, summarise and chat with meeting recordings."""

__version__ = "1.0.0"

from . import config as _config

# Locate ffmpeg before anything imports pydub. pydub probes PATH once at import
# time and caches the answer, warning "may not work" if it comes up empty — and
# a terminal opened before ffmpeg was installed hands us a stale PATH. Doing this
# here, in the package root, guarantees it runs before any submodule loads pydub.
_config.ffmpeg_path()
