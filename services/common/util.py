import hashlib
from typing import List


def shard_index(product: str, num_shards: int) -> int:
    hash_obj = hashlib.sha256(product.encode("utf-8"))
    hash_int = int(hash_obj.hexdigest(), 16)
    return hash_int % num_shards


def stable_hash(value: str) -> int:
    """Return a deterministic integer hash for the given string.

    Uses SHA-256 to ensure stability across processes and Python versions.
    """
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(h, 16)


def shard_product(product: str, num_shards: int) -> int:
    """Alias for shard computation for a product symbol.

    Keeps naming consistent at call-sites while using shard_index internally.
    """
    return shard_index(product, num_shards)


def get_shard_subject(
    product: str, num_shards: int, base_subject: str = "market_ticks"
) -> str:
    shard = shard_index(product, num_shards)
    return f"{base_subject}.{shard}"


def validate_product_list(products: List[str]) -> List[str]:
    if not products:
        raise ValueError("Product list cannot be empty")

    normalized = []
    for product in products:
        if not product or not isinstance(product, str):
            raise ValueError(f"Invalid product: {product}")

        # Normalize to uppercase
        normalized_product = product.upper().strip()
        if not normalized_product:
            raise ValueError(f"Empty product after normalization: {product}")

        normalized.append(normalized_product)

    return normalized


def format_quantity(qty: float) -> str:
    """Format a quantity with up to 8 decimal places, trimming trailing zeros.

    Keeps a compact JSON-friendly representation without scientific notation.
    """
    s = f"{qty:.8f}"
    s = s.rstrip("0").rstrip(".")
    return s if s else "0"
