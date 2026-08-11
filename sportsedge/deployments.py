import json
from pathlib import Path
from typing import Any


class DeploymentRegistryError(ValueError):
    pass


def load_registry(path: str | Path = "config/deployments.json") -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("markets"), dict):
        raise DeploymentRegistryError("invalid deployment registry schema")
    for market, meta in data["markets"].items():
        if meta.get("eligible") is not True and meta.get("eligible") is not False:
            raise DeploymentRegistryError(f"{market}: eligible must be boolean")
        if meta.get("eligible") is True and meta.get("stage") != "DEPLOYED":
            raise DeploymentRegistryError(f"{market}: eligible requires stage=DEPLOYED")
    return data


def deployment_for(market: str, path: str | Path = "config/deployments.json") -> dict[str, Any]:
    meta = load_registry(path)["markets"].get(market)
    if meta is None:
        return {"market": market, "eligible": False, "stage": "UNKNOWN", "reason": "market absent from registry"}
    return {"market": market, **meta}
