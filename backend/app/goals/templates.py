"""Static goal templates. They are code, never editable from the UI or DB."""

from __future__ import annotations

from typing import Any

TEMPLATE_VERSION = "1"

GUEST_RECOVER = "guest.recover.v1"

# Variables are the only values an operator may supply. ``approval_code`` is a
# one-time server-generated secret, not a variable and never sent to the LLM.
TEMPLATES: dict[str, dict[str, Any]] = {
    GUEST_RECOVER: {
        "id": GUEST_RECOVER,
        "version": TEMPLATE_VERSION,
        "name": "Pulihkan guest Proxmox",
        "description": "Pulihkan satu VM/CT dengan aksi tertutup start, resume, atau reset.",
        "target_kind": "guest",
        "actions": ["start", "resume", "reset", "noop", "escalate"],
        "max_steps": 1,
        "variables": [
            {
                "name": "reason",
                "type": "string",
                "required": True,
                "max_length": 200,
                "description": "Alasan tindakan, terlihat oleh approver.",
            },
            {
                "name": "expected_effect",
                "type": "enum",
                "required": True,
                "enum": ["running", "reachable"],
                "default": "running",
            },
            {
                "name": "allow_reset",
                "type": "boolean",
                "required": False,
                "default": False,
                "description": "Izinkan reset untuk VM yang berjalan tetapi agent tidak menjawab.",
            },
        ],
        "manual_secrets": [
            {
                "name": "approval_code",
                "description": "Dibuat server saat goal dibuat dan ditampilkan sekali.",
            }
        ],
    }
}


def get_template(template_id: str) -> dict[str, Any] | None:
    return TEMPLATES.get(template_id)
