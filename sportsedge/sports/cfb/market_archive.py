"""Only public row-consumption entry point for the restricted market archive."""
from .market_archive_contract import load_contract, require_use
from .history_cache import _iter_market_archive


def iter_market_archive(*, contract_path, cache_file, use):
    # Validate before even constructing the underlying generator.
    require_use(load_contract(contract_path), use)
    return _iter_market_archive(contract_path=contract_path, cache_file=cache_file, use=use)
