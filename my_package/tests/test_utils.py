"""Tests for my_package.utils."""

import pytest
from my_package.utils import (
    reverse_string,
    is_palindrome,
    factorial,
    fibonacci,
    count_vowels,
    sanitize_string,
    validate_numeric,
)


class TestReverseString:
    """Tests for reverse_string."""

    def test_reverse_basic(self):
        assert reverse_string("hello") == "olleh"

    def test_reverse_empty(self):
        assert reverse_string("") == ""

    def test_reverse_single_char(self):
        assert reverse_string("a") == "a"

    def test_reverse_with_spaces(self):
        assert reverse_string("a b c") == "c b a"

    def test_reverse_non_string_raises(self):
        with pytest.raises(TypeError, match="Expected a string"):
            reverse_string(123)


class TestIsPalindrome:
    """Tests for is_palindrome."""

    def test_palindrome_basic(self):
        assert is_palindrome("racecar") is True

    def test_non_palindrome(self):
        assert is_palindrome("hello") is False

    def test_palindrome_with_spaces_and_case(self):
        assert is_palindrome("A man a plan a canal Panama") is True

    def test_empty_string(self):
        assert is_palindrome("") is True

    def test_single_char(self):
        assert is_palindrome("a") is True

    def test_with_punctuation(self):
        assert is_palindrome("Madam, I'm Adam") is True

    def test_non_string_raises(self):
        with pytest.raises(TypeError, match="Expected a string"):
            is_palindrome(12345)


class TestFactorial:
    """Tests for factorial."""

    def test_factorial_zero(self):
        assert factorial(0) == 1

    def test_factorial_one(self):
        assert factorial(1) == 1

    def test_factorial_small(self):
        assert factorial(5) == 120

    def test_factorial_larger(self):
        assert factorial(10) == 3628800

    def test_factorial_negative_raises(self):
        with pytest.raises(ValueError, match="not defined for negative"):
            factorial(-1)

    def test_factorial_non_int_raises(self):
        with pytest.raises(TypeError, match="Expected an int"):
            factorial(5.5)


class TestFibonacci:
    """Tests for fibonacci."""

    def test_fib_zero(self):
        assert fibonacci(0) == []

    def test_fib_one(self):
        assert fibonacci(1) == [0]

    def test_fib_two(self):
        assert fibonacci(2) == [0, 1]

    def test_fib_ten(self):
        assert fibonacci(10) == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

    def test_fib_negative_raises(self):
        with pytest.raises(ValueError, match="not defined for negative"):
            fibonacci(-5)

    def test_fib_non_int_raises(self):
        with pytest.raises(TypeError, match="Expected an int"):
            fibonacci("10")


class TestCountVowels:
    """Tests for count_vowels."""

    def test_all_vowels(self):
        assert count_vowels("aeiou") == 5

    def test_no_vowels(self):
        assert count_vowels("bcdfg") == 0

    def test_mixed_case(self):
        assert count_vowels("HeLLo WoRld") == 3

    def test_empty_string(self):
        assert count_vowels("") == 0

    def test_with_numbers(self):
        assert count_vowels("h3ll0") == 0

    def test_non_string_raises(self):
        with pytest.raises(TypeError, match="Expected a string"):
            count_vowels(None)


class TestSanitizeString:
    """Tests for sanitize_string."""

    def test_keep_spaces_default(self):
        assert sanitize_string("hello world!") == "hello world"

    def test_remove_all_non_alnum(self):
        assert sanitize_string("hello-world!!!", keep_spaces=False) == "helloworld"

    def test_already_clean(self):
        assert sanitize_string("abc123") == "abc123"

    def test_empty_string(self):
        assert sanitize_string("") == ""

    def test_only_special_chars(self):
        assert sanitize_string("@#$%") == ""

    def test_non_string_raises(self):
        with pytest.raises(TypeError, match="Expected a string"):
            sanitize_string(True)


class TestValidateNumeric:
    """Tests for validate_numeric."""

    def test_int(self):
        assert validate_numeric(42) is True

    def test_float_allowed(self):
        assert validate_numeric(3.14) is True

    def test_float_not_allowed(self):
        assert validate_numeric(3.14, allow_float=False) is False

    def test_string_is_not_numeric(self):
        assert validate_numeric("42") is False

    def test_bool_is_not_numeric(self):
        assert validate_numeric(True) is False

    def test_none_is_not_numeric(self):
        assert validate_numeric(None) is False

    def test_complex_not_numeric(self):
        assert validate_numeric(1 + 2j) is False
