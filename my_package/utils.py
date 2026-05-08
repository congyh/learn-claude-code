"""
Utility functions for common operations.

Includes helpers for string manipulation, mathematical calculations,
and input validation.
"""

import re
from typing import Any, List, Optional, Union


def reverse_string(s: str) -> str:
    """Return the reverse of the input string.

    Args:
        s: The string to reverse.

    Returns:
        The reversed string.

    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected a string, got {type(s).__name__}")
    return s[::-1]


def is_palindrome(s: str) -> bool:
    """Check if a string is a palindrome (ignoring case and non-alphanumeric chars).

    Args:
        s: The string to check.

    Returns:
        True if the string is a palindrome, False otherwise.

    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected a string, got {type(s).__name__}")
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", s).lower()
    return cleaned == cleaned[::-1]


def factorial(n: int) -> int:
    """Compute the factorial of a non-negative integer.

    Args:
        n: A non-negative integer.

    Returns:
        The factorial of n.

    Raises:
        TypeError: If input is not an integer.
        ValueError: If input is negative.
    """
    if not isinstance(n, int):
        raise TypeError(f"Expected an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError("Factorial is not defined for negative numbers")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result


def fibonacci(n: int) -> List[int]:
    """Generate the first n numbers in the Fibonacci sequence.

    Args:
        n: The number of Fibonacci numbers to generate (non-negative int).

    Returns:
        A list of the first n Fibonacci numbers.

    Raises:
        TypeError: If input is not an integer.
        ValueError: If input is negative.
    """
    if not isinstance(n, int):
        raise TypeError(f"Expected an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError("Fibonacci is not defined for negative numbers")
    if n == 0:
        return []
    if n == 1:
        return [0]
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq


def count_vowels(s: str) -> int:
    """Count the number of vowels (a, e, i, o, u) in a string (case-insensitive).

    Args:
        s: The string to examine.

    Returns:
        The count of vowels in the string.

    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected a string, got {type(s).__name__}")
    return sum(1 for ch in s.lower() if ch in "aeiou")


def sanitize_string(s: str, keep_spaces: bool = True) -> str:
    """Remove non-alphanumeric characters from a string.

    Args:
        s: The string to sanitize.
        keep_spaces: Whether to keep spaces (default: True).

    Returns:
        The sanitized string containing only alphanumeric chars and optionally spaces.

    Raises:
        TypeError: If input is not a string.
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected a string, got {type(s).__name__}")
    pattern = r"[^a-zA-Z0-9 ]" if keep_spaces else r"[^a-zA-Z0-9]"
    return re.sub(pattern, "", s)


def validate_numeric(value: Any, allow_float: bool = True) -> bool:
    """Check if a value is numeric (int or float).

    Args:
        value: The value to validate.
        allow_float: Whether to accept float values (default: True).

    Returns:
        True if the value is numeric, False otherwise.
    """
    if allow_float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, int) and not isinstance(value, bool)
