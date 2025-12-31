import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import List


def shard_index(product: str, num_shards: int) -> int:
    hash_obj = hashlib.sha256(product.encode("utf-8"))
    hash_int = int(hash_obj.hexdigest(), 16)
    return hash_int % num_shards


def shard_product(product: str, num_shards: int) -> int:
    """Stable shard mapping based on product name."""
    return shard_index(product, num_shards)


def stable_hash(value: str) -> str:
    """Return a short, deterministic hash useful for ids or logging."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def get_shard_subject(
    product: str, num_shards: int, base_subject: str = "market.ticks"
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


def format_quantity(quantity: float, precision: int = 8) -> str:
    quantized = Decimal(str(quantity)).quantize(
        Decimal(10) ** -precision, rounding=ROUND_HALF_UP
    )
    return f"{quantized.normalize()}"
