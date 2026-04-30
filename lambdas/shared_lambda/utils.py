# shared_lambda/utils.py
# Shared utility functions used across query_lambda and shared_lambda

import math

def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """
    Computes cosine similarity between two vectors.
    Returns value between -1 and 1.
    1.0 = identical direction, 0.0 = perpendicular, -1.0 = opposite.
    """
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = math.sqrt(sum(a * a for a in vec_a))
    magnitude_b = math.sqrt(sum(b * b for b in vec_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)
