#!/usr/bin/env python3
"""Home Assistant health monitor and fail-safe manager.

Monitors HA availability, orphaned entities, and provides safe restart procedures.
Run via cron: */5 * * * * /opt/scripts/ha_health_monitor.py
"""

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/tmp/ha_health.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class HAConfig:
    url: str
    token: Optional[str]
    container_name: str

class HAMonitor:
    def __init__(self, config: HAConfig):
        self.config = config
        self.client = httpx.Client(timeout=10.0)

    def is_ha_available(self) -> bool:
        """Check if HA is accessible."""
        try:
            resp = self.client.get(f"{self.config.url}/", follow_redirects=True)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"HA availability check failed: {e}")
            return False

    def get_entities(self) -> list[dict]:
        """Get all entities from HA."""
        headers = {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}
        try:
            resp = self.client.get(f"{self.config.url}/api/states", headers=headers)
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get entities: {e}")
            return []

    def get_entity_registry(self) -> dict:
        """Get entity registry from storage."""
        registry_path = Path(f"/home/ultra/homeassistant/.storage/core.entity_registry")
        if registry_path.exists():
            with open(registry_path) as f:
                return json.load(f)
        return {}

    def find_orphaned_entities(self) -> list[dict]:
        """Find orphaned entities in registry."""
        registry = self.get_entity_registry()
        entities = registry.get("data", {}).get("entities", [])
        orphaned = [e for e in entities if e.get("orphaned_timestamp")]
        return orphaned

    def find_duplicate_tts_entities(self) -> list[dict]:
        """Find duplicate TTS entities (same entity_id)."""
        registry = self.get_entity_registry()
        entities = registry.get("data", {}).get("entities", [])
        tts_entities = [e for e in entities if e.get("entity_id", "").startswith("tts.")]
        by_id = {}
        for e in tts_entities:
            eid = e["entity_id"]
            if eid not in by_id:
                by_id[eid] = []
            by_id[eid].append(e)
        duplicates = {k: v for k, v in by_id.items() if len(v) > 1}
        return duplicates

    def get_pipelines(self) -> list[dict]:
        """Get assist pipelines."""
        path = Path(f"/home/ultra/homeassistant/.storage/assist_pipeline.pipelines")
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                return data.get("data", {}).get("items", [])
        return []

    def validate_tts_pipeline(self) -> dict:
        """Validate TTS configuration in pipelines."""
        pipelines = self.get_pipelines()
        results = []
        for p in pipelines:
            tts_engine = p.get("tts_engine")
            if tts_engine:
                registry = self.get_entity_registry()
                entities = registry.get("data", {}).get("entities", [])
                tts_entity = next((e for e in entities if e["entity_id"] == tts_engine), None)
                is_valid = tts_entity and not tts_entity.get("orphaned_timestamp") and tts_entity.get("config_entry_id")
                results.append({
                    "pipeline": p["name"],
                    "tts_engine": tts_engine,
                    "is_valid": is_valid,
                    "has_config_entry": bool(tts_entity and tts_entity.get("config_entry_id")) if tts_entity else False,
                    "is_orphaned": bool(tts_entity and tts_entity.get("orphaned_timestamp")) if tts_entity else True
                })
            else:
                results.append({
                    "pipeline": p["name"],
                    "tts_engine": None,
                    "is_valid": True,
                    "has_config_entry": False,
                    "is_orphaned": False
                })
        return results

    def fix_orphaned_entity(self, entity_id: str) -> bool:
        """Remove orphaned entity from registry."""
        registry_path = Path(f"/home/ultra/homeassistant/.storage/core.entity_registry")
        backup_path = Path(f"/tmp/core.entity_registry.backup.{int(time.time())}")
        registry = self.get_entity_registry()
        entities = registry.get("data", {}).get("entities", [])
        original_count = len(entities)
        entities = [e for e in entities if e.get("entity_id") != entity_id or e.get("config_entry_id")]
        if len(entities) < original_count:
            subprocess.run(["cp", str(registry_path), str(backup_path)])
            registry["data"]["entities"] = entities
            with open(registry_path, "w") as f:
                json.dump(registry, f, indent=2)
            logger.info(f"Fixed orphaned entity: {entity_id} (backup: {backup_path})")
            return True
        return False

    def restart_ha(self, reason: str = "manual") -> bool:
        """Safely restart HA container."""
        logger.info(f"Restarting HA: {reason}")
        try:
            subprocess.run(["docker", "restart", self.config.container_name], check=True)
            time.sleep(30)
            for i in range(30):
                if self.is_ha_available():
                    logger.info("HA restarted successfully")
                    return True
                time.sleep(2)
            logger.error("HA did not come back after restart")
            return False
        except Exception as e:
            logger.error(f"Failed to restart HA: {e}")
            return False

    def check_and_fix_tts(self) -> dict:
        """Check and fix TTS configuration."""
        result = {"orphaned_removed": 0, "duplicates_found": {}, "pipeline_status": []}
        orphaned = self.find_orphaned_entities()
        if orphaned:
            tts_orphaned = [e for e in orphaned if e.get("entity_id", "").startswith("tts.")]
            for e in tts_orphaned:
                self.fix_orphaned_entity(e["entity_id"])
                result["orphaned_removed"] += 1
        duplicates = self.find_duplicate_tts_entities()
        result["duplicates_found"] = {k: len(v) for k, v in duplicates.items()}
        result["pipeline_status"] = self.validate_tts_pipeline()
        return result

def get_ha_token() -> Optional[str]:
    """Get HA token from environment or file."""
    token = os.environ.get("HA_LONG_LIVE_TOKEN")
    if token:
        return token
    token_file = Path("/home/ultra/homeassistant/secrets.yaml")
    if token_file.exists():
        with open(token_file) as f:
            for line in f:
                if line.startswith("ha_token:"):
                    return line.split(":", 1)[1].strip()
    return None

def main():
    config = HAConfig(
        url="http://localhost:8123",
        token=get_ha_token(),
        container_name="homeassistant-homeassistant-1"
    )

    monitor = HAMonitor(config)

    if not monitor.is_ha_available():
        logger.error("HA is not available!")
        sys.exit(1)

    orphaned = monitor.find_orphaned_entities()
    if orphaned:
        logger.warning(f"Found {len(orphaned)} orphaned entities")
        for e in orphaned[:5]:
            logger.info(f"  - {e['entity_id']} ({e.get('platform')})")

    result = monitor.check_and_fix_tts()
    logger.info(f"TTS status: {result}")

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()