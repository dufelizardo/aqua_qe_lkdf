"""
AQuA-QE LKDF — Config Manager
Persistência de configuração entre restarts.

Arquivos:
  config/gateway.json  → provider settings, routing, deployment mode
  config/.env          → API keys (nunca no JSON — segurança)

Estrutura do gateway.json:
{
  "deployment_mode": "cloud",
  "providers": {
    "anthropic": {"enabled": true, "priority": 9, "default_model": "claude-sonnet-4-5", ...}
  },
  "routing": {
    "requirement": {"primary": "anthropic", "model": "claude-sonnet-4-5", "fallbacks": [...], "strategy": "..."}
  }
}
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ── Paths ──────────────────────────────────────────────────────
_ROOT        = Path(__file__).parent.parent.parent   # aqua-gateway/
CONFIG_DIR   = _ROOT / "config"
GATEWAY_JSON = CONFIG_DIR / "gateway.json"
ENV_FILE     = CONFIG_DIR / ".env"
GITIGNORE    = CONFIG_DIR / ".gitignore"


# ── Helpers ────────────────────────────────────────────────────

def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Never commit secrets
    if not GITIGNORE.exists():
        GITIGNORE.write_text("# AQuA-QE config — auto-generated\n.env\n*.key\n")


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ConfigManager] Warning: could not read {path}: {e}")
    return {}


def _save_json(path: Path, data: dict):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _load_env(path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE .env file."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _save_env(path: Path, data: dict[str, str]):
    """Write KEY=VALUE .env file, preserving comments at top."""
    lines = [
        "# AQuA-QE Gateway API Keys",
        "# Auto-generated — do not commit to version control",
        f"# Last updated: {datetime.utcnow().isoformat()}Z",
        "",
    ]
    for k, v in sorted(data.items()):
        lines.append(f'{k}="{v}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── ConfigManager ──────────────────────────────────────────────

class ConfigManager:
    """
    Singleton responsável por ler e gravar toda configuração persistente do gateway.
    Thread-safe via lock interno.
    """

    def __init__(self):
        self._lock   = threading.Lock()
        self._config: dict = {}
        self._keys:   dict[str, str] = {}
        self._loaded  = False

    # ── Load ───────────────────────────────────────────────────

    def load(self):
        """Carrega configuração do disco. Chamado no startup."""
        _ensure_config_dir()
        with self._lock:
            self._config = _load_json(GATEWAY_JSON)
            self._keys   = _load_env(ENV_FILE)
            self._loaded = True

        n_keys = sum(1 for v in self._keys.values() if v)
        n_prov = len(self._config.get("providers", {}))
        n_rout = len(self._config.get("routing", {}))
        print(f"[ConfigManager] Loaded: {n_prov} providers, {n_rout} routes, {n_keys} keys")

    # ── Apply to gateway state ─────────────────────────────────

    def apply_to_gateway(self, gateway_instance):
        """
        Aplica configuração carregada ao estado do gateway.
        Deve ser chamado após load() e após o gateway ser inicializado.
        """
        from backend.models.schemas import ProviderName, EngineType, DeploymentMode

        with self._lock:
            cfg = self._config

        # 1. Deployment mode
        mode_str = cfg.get("deployment_mode", "")
        if mode_str:
            try:
                gateway_instance.set_deployment_mode(DeploymentMode(mode_str))
            except ValueError:
                pass

        # 2. API keys → provider configs
        for raw_key, value in self._keys.items():
            # Expected format: AQUA_KEY_ANTHROPIC, AQUA_KEY_OPENAI, etc.
            if raw_key.startswith("AQUA_KEY_") and value:
                provider_suffix = raw_key[len("AQUA_KEY_"):].lower()
                try:
                    pname = ProviderName(provider_suffix)
                    gateway_instance.update_provider(pname, {"api_key": value})
                except ValueError:
                    pass  # unknown provider name — skip

        # 3. Provider settings (non-key fields)
        for pname_str, settings in cfg.get("providers", {}).items():
            try:
                pname = ProviderName(pname_str)
                # Never apply api_key from JSON (only from .env)
                safe = {k: v for k, v in settings.items() if k != "api_key"}
                if safe:
                    gateway_instance.update_provider(pname, safe)
            except (ValueError, KeyError):
                pass

        # 4. Engine routing
        for engine_str, routing in cfg.get("routing", {}).items():
            try:
                EngineType(engine_str)
                gateway_instance.update_engine_routing(engine_str, {
                    "primary":   routing.get("primary"),
                    "model":     routing.get("model", ""),
                    "fallbacks": routing.get("fallbacks", []),
                    "strategy":  routing.get("strategy", "capability_match"),
                })
            except ValueError:
                pass

        n_keys = sum(
            1 for k in self._keys
            if k.startswith("AQUA_KEY_") and self._keys[k]
        )
        print(f"[ConfigManager] Applied: {n_keys} keys, "
              f"{len(cfg.get('providers', {}))} provider overrides, "
              f"{len(cfg.get('routing', {}))} routing overrides")

    # ── Save keys ──────────────────────────────────────────────

    def save_api_key(self, provider_name: str, api_key: str):
        """Persiste API key no .env."""
        _ensure_config_dir()
        env_key = f"AQUA_KEY_{provider_name.upper()}"
        with self._lock:
            if api_key:
                self._keys[env_key] = api_key
            else:
                self._keys.pop(env_key, None)
            _save_env(ENV_FILE, self._keys)

    def get_api_key(self, provider_name: str) -> Optional[str]:
        """Retorna API key de um provider, se configurada."""
        env_key = f"AQUA_KEY_{provider_name.upper()}"
        with self._lock:
            return self._keys.get(env_key) or None

    def list_configured_providers(self) -> list[str]:
        """Retorna providers que têm API key configurada."""
        with self._lock:
            return [
                k[len("AQUA_KEY_"):].lower()
                for k, v in self._keys.items()
                if k.startswith("AQUA_KEY_") and v
            ]

    # ── Save provider settings ─────────────────────────────────

    def save_provider_settings(self, provider_name: str, settings: dict):
        """Persiste settings de provider no gateway.json (sem api_key)."""
        _ensure_config_dir()
        with self._lock:
            safe = {k: v for k, v in settings.items() if k != "api_key"}
            if not safe:
                return
            if "providers" not in self._config:
                self._config["providers"] = {}
            existing = self._config["providers"].get(provider_name, {})
            existing.update(safe)
            self._config["providers"][provider_name] = existing
            self._config["_updated_at"] = datetime.utcnow().isoformat() + "Z"
            _save_json(GATEWAY_JSON, self._config)

    # ── Save routing ───────────────────────────────────────────

    def save_routing(self, engine_name: str, routing: dict):
        """Persiste routing de uma engine no gateway.json."""
        _ensure_config_dir()
        with self._lock:
            if "routing" not in self._config:
                self._config["routing"] = {}
            self._config["routing"][engine_name] = routing
            self._config["_updated_at"] = datetime.utcnow().isoformat() + "Z"
            _save_json(GATEWAY_JSON, self._config)

    # ── Save deployment mode ───────────────────────────────────

    def save_deployment_mode(self, mode: str):
        _ensure_config_dir()
        with self._lock:
            self._config["deployment_mode"] = mode
            self._config["_updated_at"] = datetime.utcnow().isoformat() + "Z"
            _save_json(GATEWAY_JSON, self._config)

    # ── Full snapshot ──────────────────────────────────────────

    def save_full_snapshot(self, gateway_instance):
        """
        Salva estado completo do gateway (providers + routing + mode).
        Útil para backup manual ou exportação.
        """
        _ensure_config_dir()
        from backend.models.schemas import ProviderName

        providers_data = {}
        for pname, cfg in gateway_instance.state.providers.items():
            pname_str = pname.value if hasattr(pname, "value") else str(pname)
            providers_data[pname_str] = {
                "enabled":       cfg.enabled,
                "priority":      cfg.priority,
                "default_model": cfg.default_model,
                "base_url":      cfg.base_url,
                "timeout_seconds": cfg.timeout_seconds,
                # api_key goes to .env, never here
            }

        routing_data = {}
        for engine, rcfg in gateway_instance.state.engine_routing.items():
            engine_str = engine.value if hasattr(engine, "value") else str(engine)
            routing_data[engine_str] = {
                "primary":   str(rcfg.get("primary", "")),
                "model":     rcfg.get("model", ""),
                "fallbacks": [str(f) for f in rcfg.get("fallbacks", [])],
                "strategy":  str(rcfg.get("strategy", "capability_match")),
            }

        with self._lock:
            self._config = {
                "deployment_mode": str(gateway_instance.state.deployment_mode),
                "providers":       providers_data,
                "routing":         routing_data,
                "_updated_at":     datetime.utcnow().isoformat() + "Z",
                "_version":        "2.0",
            }
            _save_json(GATEWAY_JSON, self._config)

        print(f"[ConfigManager] Snapshot saved → {GATEWAY_JSON}")

    # ── Status ─────────────────────────────────────────────────

    def status(self) -> dict:
        with self._lock:
            return {
                "config_file":   str(GATEWAY_JSON),
                "env_file":      str(ENV_FILE),
                "config_exists": GATEWAY_JSON.exists(),
                "env_exists":    ENV_FILE.exists(),
                "loaded":        self._loaded,
                "providers_in_config": list(self._config.get("providers", {}).keys()),
                "routes_in_config":    list(self._config.get("routing", {}).keys()),
                "keys_configured":     self.list_configured_providers(),
                "deployment_mode":     self._config.get("deployment_mode", ""),
                "last_updated":        self._config.get("_updated_at", "never"),
            }


# Singleton
config_manager = ConfigManager()
