from __future__ import annotations

from ...desktop_capabilities import find_capability, load_keybinding_catalogue
from ...core.models import ActionType


class DeepinKeybindingProvider:
    provider_id = "deepin-keybindings"

    def __init__(self, loader=load_keybinding_catalogue, resolver=find_capability):
        self._loader = loader
        self._resolver = resolver

    def list_capabilities(self):
        return self._loader()

    def resolve(self, capability_id: str):
        return self._resolver(capability_id)
