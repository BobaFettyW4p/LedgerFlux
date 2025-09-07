"""
Common utilities for the market data fan-out system.
"""

import hashlib
from typing import List


def stable_hash(product: str, num_shards: int) -> int:
    """
    Create a stable hash of a product for sharding.
    
    Args:
        product: Product symbol (e.g., "BTC-USD")
        num_shards: Number of shards
        
    Returns:
        Shard number (0 to num_shards-1)
    """
    # Use SHA-256 for stable hashing
    hash_obj = hashlib.sha256(product.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest(), 16)
    return hash_int % num_shards


def shard_product(product: str, num_shards: int) -> int:
    """
    Alias for stable_hash - determines the shard ID for a given product.
    
    Args:
        product: Product symbol (e.g., "BTC-USD")
        num_shards: Number of shards
        
    Returns:
        Shard number (0 to num_shards-1)
    """
    return stable_hash(product, num_shards)


def get_shard_subject(product: str, num_shards: int, base_subject: str = "market_ticks") -> str:
    """
    Get the JetStream subject for a product's shard.
    
    Args:
        product: Product symbol
        num_shards: Number of shards
        base_subject: Base subject name
        
    Returns:
        Subject name (e.g., "market_ticks.0")
    """
    shard = stable_hash(product, num_shards)
    return f"{base_subject}.{shard}"


def validate_product_list(products: List[str]) -> List[str]:
    """
    Validate and normalize product list.
    
    Args:
        products: List of product symbols
        
    Returns:
        Validated and normalized product list
        
    Raises:
        ValueError: If any product is invalid
    """
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


def format_price(price: float, decimals: int = 2) -> str:
    """
    Format price for display.
    
    Args:
        price: Price value
        decimals: Number of decimal places
        
    Returns:
        Formatted price string
    """
    return f"${price:,.{decimals}f}"


def format_quantity(quantity: float, decimals: int = 8) -> str:
    """
    Format quantity for display.
    
    Args:
        quantity: Quantity value
        decimals: Number of decimal places
        
    Returns:
        Formatted quantity string
    """
    return f"{quantity:.{decimals}f}".rstrip('0').rstrip('.')
