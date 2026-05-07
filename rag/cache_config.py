import os
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def configure_project_cache(project_root: str | Path | None = None) -> dict[str, str]:
    root = Path(project_root) if project_root else get_project_root()
    cache_root = root / ".cache"

    env_defaults = {
        "XDG_CACHE_HOME": cache_root,
        "HF_HOME": cache_root / "huggingface",
        "HF_HUB_CACHE": cache_root / "huggingface" / "hub",
        "HUGGINGFACE_HUB_CACHE": cache_root / "huggingface" / "hub",
        "MODELSCOPE_CACHE": cache_root / "modelscope",
        "MODELSCOPE_HOME": cache_root / "modelscope",
        "DOCLING_ARTIFACTS_PATH": cache_root / "docling",
        "PADDLE_HOME": cache_root / "paddle",
        "PADDLEOCR_HOME": cache_root / "paddleocr",
        "PADDLE_PDX_CACHE_HOME": cache_root / "paddlex",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "TORCH_HOME": cache_root / "torch",
        "MPLCONFIGDIR": cache_root / "matplotlib",
        "TEMP": cache_root / "tmp",
        "TMP": cache_root / "tmp",
        "MINERU_TOOLS_CONFIG_JSON": cache_root / "mineru" / "mineru.json",
        "MINERU_MODEL_SOURCE": "modelscope",
    }
    file_path_keys = {"MINERU_TOOLS_CONFIG_JSON"}
    forced_env_keys = {"TEMP", "TMP"}

    cache_root.mkdir(parents=True, exist_ok=True)
    for key, value in env_defaults.items():
        if not isinstance(value, Path):
            continue
        if key in file_path_keys:
            value.parent.mkdir(parents=True, exist_ok=True)
        else:
            value.mkdir(parents=True, exist_ok=True)

    resolved: dict[str, str] = {}
    for key, default_value in env_defaults.items():
        value = str(default_value)
        if key in forced_env_keys:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
        resolved[key] = os.environ[key]

    print(f"[cache_config] project cache root: {cache_root}")
    for key, value in resolved.items():
        print(f"[cache_config] {key}={value}")

    return resolved
