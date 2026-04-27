from __future__ import annotations

import warnings
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_user_db_path() -> str:
    return str(Path.home() / ".docmancer" / "docmancer.db")


class IndexConfig(BaseSettings):
    provider: str = "sqlite"
    db_path: str = Field(default_factory=default_user_db_path)
    extracted_dir: str = ""
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_INDEX_", extra="ignore")


class QueryConfig(BaseSettings):
    default_budget: int = Field(default=2400, ge=100)
    default_limit: int = Field(default=8, ge=1)
    default_expand: str = "adjacent"
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_QUERY_", extra="ignore")


class WebFetchConfig(BaseSettings):
    workers: int = Field(default=8, ge=1)
    default_page_cap: int = Field(default=500, ge=1)
    browser_fallback: bool = False
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_WEB_FETCH_", extra="ignore")


class BenchBackendConfig(BaseSettings):
    k_retrieve: int = Field(default=10, ge=1)
    k_answer: int = Field(default=5, ge=1)
    timeout_s_fts: float = Field(default=60.0, gt=0)
    timeout_s_qdrant: float = Field(default=60.0, gt=0)
    timeout_s_rlm: float = Field(default=300.0, gt=0)
    # RLM-specific knobs (see docmancer/bench/backends/rlm.py). Empty string
    # means "auto" (detect provider from env vars, use default model).
    rlm_provider: str = ""
    rlm_model: str = ""
    rlm_max_chars: int = Field(default=120_000, ge=1_000)
    rlm_max_iterations: int = Field(default=6, ge=1)
    rlm_verbose: bool = False
    rlm_log_dir: str = ""
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_BENCH_", extra="ignore")


class BenchConfig(BaseSettings):
    datasets_dir: str = ".docmancer/bench/datasets"
    runs_dir: str = ".docmancer/bench/runs"
    judge_provider: str = ""
    backends: BenchBackendConfig = Field(default_factory=BenchBackendConfig)
    model_config = SettingsConfigDict(env_prefix="DOCMANCER_BENCH_", extra="ignore")


def _translate_eval_to_bench(legacy: dict) -> dict:
    """Map old `eval:` keys onto the `bench:` schema.

    Legacy shape (from the pre-bench `EvalConfig`):
        dataset_path: ".docmancer/eval_dataset.json"
        output_dir:   ".docmancer/eval"
        judge_provider: ""
        default_k: 5

    New `BenchConfig` uses `datasets_dir`, `runs_dir`, `judge_provider`, and
    `backends.k_retrieve` / `backends.k_answer`. The legacy `dataset_path`
    pointed at a single JSON file; the parent directory becomes the new
    `datasets_dir` so legacy users keep working with `bench dataset validate
    <path>`.
    """
    if not isinstance(legacy, dict):
        return {}
    out: dict = {}
    if legacy.get("dataset_path"):
        out["datasets_dir"] = str(Path(str(legacy["dataset_path"])).parent)
    if legacy.get("output_dir"):
        out["runs_dir"] = str(legacy["output_dir"])
    if legacy.get("judge_provider"):
        out["judge_provider"] = str(legacy["judge_provider"])
    if legacy.get("default_k") is not None:
        backends = out.setdefault("backends", {})
        backends["k_retrieve"] = int(legacy["default_k"])
        backends["k_answer"] = int(legacy["default_k"])
    # Preserve any keys the caller already uses the new names for.
    for passthrough in ("datasets_dir", "runs_dir", "backends"):
        if passthrough in legacy and passthrough not in out:
            out[passthrough] = legacy[passthrough]
    return out


class DocmancerConfig(BaseModel):
    index: IndexConfig = Field(default_factory=IndexConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    web_fetch: WebFetchConfig = Field(default_factory=WebFetchConfig)
    bench: BenchConfig = Field(default_factory=BenchConfig)

    @classmethod
    def from_yaml(cls, path: Path | str) -> DocmancerConfig:
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f) or {}

        if "registry" in data:
            warnings.warn(
                "registry config is obsolete and has been removed; the key is ignored.",
                DeprecationWarning,
                stacklevel=2,
            )
            data.pop("registry", None)

        if "eval" in data:
            legacy_eval = data.pop("eval") or {}
            if "bench" not in data:
                warnings.warn(
                    "`eval:` config is deprecated; translating to `bench:`. Rename "
                    "your config to `bench:` to silence this warning.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                data["bench"] = _translate_eval_to_bench(legacy_eval)
            else:
                warnings.warn(
                    "`eval:` config is deprecated; both `eval:` and `bench:` are set "
                    "so `eval:` is ignored.",
                    DeprecationWarning,
                    stacklevel=2,
                )

        data.pop("packs", None)

        if "index" not in data and isinstance(data.get("vector_store"), dict):
            vector_store = data.get("vector_store") or {}
            local_path = vector_store.get("db_path") or vector_store.get("local_path")
            if local_path:
                legacy_path = Path(str(local_path))
                if legacy_path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                    data["index"] = {"db_path": local_path}
                else:
                    data["index"] = {"db_path": ".docmancer/docmancer.db"}

        config = cls(**data)
        db_path = Path(config.index.db_path)
        if not db_path.is_absolute():
            config.index.db_path = str((path.parent / db_path).resolve())

        extracted_dir = config.index.extracted_dir
        if extracted_dir:
            extracted_path = Path(extracted_dir)
            if not extracted_path.is_absolute():
                config.index.extracted_dir = str((path.parent / extracted_path).resolve())

        return config

    @classmethod
    def from_env(cls) -> DocmancerConfig:
        return cls()
