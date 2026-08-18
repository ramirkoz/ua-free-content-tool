"""UA FREE Content Tool."""

__version__ = "1.3.0-rc1"
APP_NAME = "UA FREE Content Tool"

# Keep the proven v1.2.x production provider registry. v1.3 changes task routing,
# evidence selection and factual validation, not the provider zoo.
from .active_ai_providers_v1_2_1 import activate_ai_providers as _activate_ai_providers

_activate_ai_providers()
