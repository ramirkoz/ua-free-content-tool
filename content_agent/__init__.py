"""UA FREE Content Tool."""

__version__ = "1.2.2-rc3"
APP_NAME = "UA FREE Content Tool"

# Final v1.2.1 production provider policy is applied at package import time so
# every AI workflow sees the same filtered priority chain.
from .active_ai_providers_v1_2_1 import activate_ai_providers as _activate_ai_providers

_activate_ai_providers()
