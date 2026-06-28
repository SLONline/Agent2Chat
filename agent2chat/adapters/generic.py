"""A fully configurable adapter for any other CLI agent.

There is no default command — you must supply one in config:

    {
      "agent": "generic",
      "command": ["my-agent", "--prompt", "{prompt}"],
      "continue_command": ["my-agent", "--resume", "--prompt", "{prompt}"]
    }

The first token of ``command`` is treated as the binary to look for on PATH.
"""
from __future__ import annotations

import shutil

from .base import Adapter, AdapterError


class GenericAdapter(Adapter):
    name = "generic"
    label = "Generic CLI"
    binary = ""

    def __init__(self, *, command=None, continue_command=None, timeout=600):
        if not command:
            raise AdapterError("The 'generic' agent requires a 'command' in config.")
        super().__init__(command=command, continue_command=continue_command, timeout=timeout)
        self.binary = command[0]

    @classmethod
    def detect(cls) -> bool:
        return True  # can't know the binary until configured

    def run(self, prompt, *, work_dir, is_continuation):
        if shutil.which(self.binary) is None and "/" not in self.binary:
            raise AdapterError(f"'{self.binary}' not found on PATH.")
        return super().run(prompt, work_dir=work_dir, is_continuation=is_continuation)
