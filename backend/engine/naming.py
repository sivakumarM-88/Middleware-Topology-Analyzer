"""Naming convention engine for MQ objects."""

from __future__ import annotations

import re

# MQ naming rules
MQ_MAX_NAME_LENGTH = 48
MQ_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9._]+$")


class NamingEngine:
    """Generates and validates MQ object names following conventions."""

    @staticmethod
    def queue_name(
        producer_app_id: str,
        consumer_app_id: str,
        system: str = "",
        function: str = "",
        suffix: str = "DAT",
    ) -> str:
        """Generate queue name: {PROD}.{CONS}.{SYSTEM}.{FUNCTION}.{SUFFIX}"""
        parts = [producer_app_id.upper(), consumer_app_id.upper()]
        if system:
            parts.append(system.upper())
        if function:
            parts.append(function.upper())
        parts.append(suffix.upper())
        name = ".".join(parts)
        return NamingEngine._sanitize(name)

    @staticmethod
    def channel_sender(from_qm: str, to_qm: str) -> str:
        """Generate sender channel name: {FROM_QM}.TO.{TO_QM}"""
        name = f"{from_qm}.TO.{to_qm}"
        return NamingEngine._sanitize(name)

    @staticmethod
    def channel_receiver(from_qm: str, to_qm: str) -> str:
        """Generate receiver channel name: {TO_QM}.FROM.{FROM_QM}"""
        name = f"{to_qm}.FROM.{from_qm}"
        return NamingEngine._sanitize(name)

    @staticmethod
    def xmit_queue(target_qm: str) -> str:
        """Generate transmission queue name: {TARGET_QM}"""
        return NamingEngine._sanitize(target_qm.upper())

    @staticmethod
    def alias_name(original_queue: str, version: int = 1) -> str:
        """Generate alias name: {ORIGINAL}.XA{VERSION}"""
        name = f"{original_queue}.XA{version:02d}"
        return NamingEngine._sanitize(name)

    @staticmethod
    def remote_queue(
        producer_app_id: str,
        consumer_app_id: str,
        suffix: str = "DAT",
    ) -> str:
        """Generate remote queue name matching the target local queue pattern."""
        return NamingEngine.queue_name(producer_app_id, consumer_app_id, suffix=suffix)

    @staticmethod
    def edge_id(source_qm: str, target_qm: str) -> str:
        """Generate a deterministic edge ID."""
        return f"{source_qm}->{target_qm}"

    @staticmethod
    def validate(name: str) -> list[str]:
        """Validate a name against MQ naming rules. Returns list of violations."""
        errors = []
        if len(name) > MQ_MAX_NAME_LENGTH:
            errors.append(f"Name '{name}' exceeds {MQ_MAX_NAME_LENGTH} chars ({len(name)})")
        if not MQ_ALLOWED_CHARS.match(name):
            errors.append(f"Name '{name}' contains invalid characters")
        if not name:
            errors.append("Name is empty")
        return errors

    @staticmethod
    def _sanitize(name: str) -> str:
        """Clean and truncate a name to fit MQ rules."""
        name = re.sub(r"[^A-Za-z0-9._]", "", name)
        if len(name) > MQ_MAX_NAME_LENGTH:
            name = name[:MQ_MAX_NAME_LENGTH]
        return name
