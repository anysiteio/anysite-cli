"""Tests for error code infrastructure in exception hierarchy."""

import pytest

from anysite.api.errors import (
    AnysiteError,
    AuthenticationError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from anysite.cli.exit_codes import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_NETWORK,
    EXIT_NOT_FOUND,
    EXIT_USAGE,
)
from anysite.dataset.errors import CircularDependencyError, DatasetError, SourceNotFoundError
from anysite.llm.errors import ConfigError, LLMError, PromptError, ProviderError


class TestAnysiteErrorBase:
    """Test base exception class defaults."""

    def test_default_error_code(self):
        err = AnysiteError("test message")
        assert err.error_code == "UNKNOWN_ERROR"

    def test_default_exit_code(self):
        err = AnysiteError("test message")
        assert err.exit_code == EXIT_ERROR
        assert err.exit_code == 1

    def test_default_retryable(self):
        err = AnysiteError("test message")
        assert err.retryable is False

    def test_default_suggestions(self):
        err = AnysiteError("test message")
        assert err.suggestions == []

    def test_to_dict_minimal(self):
        err = AnysiteError("test message")
        result = err.to_dict()
        assert result == {
            "code": "UNKNOWN_ERROR",
            "message": "test message",
            "retryable": False,
        }

    def test_to_dict_with_suggestions(self):
        class CustomError(AnysiteError):
            @property
            def suggestions(self) -> list[str]:
                return ["Try this", "Or that"]

        err = CustomError("test")
        result = err.to_dict()
        assert "suggestions" in result
        assert result["suggestions"] == ["Try this", "Or that"]

    def test_to_dict_with_details(self):
        err = AnysiteError("test", details={"key": "value"})
        result = err.to_dict()
        assert "details" in result
        assert result["details"] == {"key": "value"}


class TestAPIErrorCodes:
    """Test error codes for API exception subclasses."""

    @pytest.mark.parametrize(
        "error_class,expected_code,expected_exit,expected_retryable",
        [
            (AuthenticationError, "AUTH_FAILED", EXIT_AUTH, False),
            (RateLimitError, "RATE_LIMIT", EXIT_NETWORK, True),
            (NotFoundError, "NOT_FOUND", EXIT_NOT_FOUND, False),
            (ValidationError, "VALIDATION_ERROR", EXIT_USAGE, False),
            (ServerError, "SERVER_ERROR", EXIT_ERROR, True),
            (NetworkError, "NETWORK_ERROR", EXIT_NETWORK, True),
            (TimeoutError, "TIMEOUT", EXIT_NETWORK, True),
        ],
    )
    def test_error_attributes(self, error_class, expected_code, expected_exit, expected_retryable):
        """Test error_code, exit_code, and retryable for each API error class."""
        err = error_class("test message")
        assert err.error_code == expected_code
        assert err.exit_code == expected_exit
        assert err.retryable == expected_retryable


class TestAPIErrorSuggestions:
    """Test that each API error subclass provides helpful suggestions."""

    def test_authentication_error_suggestions(self):
        err = AuthenticationError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert all(isinstance(s, str) for s in suggestions)
        assert any("app.anysite.io" in s for s in suggestions)

    def test_rate_limit_error_suggestions(self):
        err = RateLimitError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("retry" in s.lower() for s in suggestions)
        assert any("rate-limit" in s.lower() for s in suggestions)

    def test_rate_limit_error_suggestions_with_retry_after(self):
        err = RateLimitError(retry_after=30)
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("30" in s for s in suggestions)

    def test_not_found_error_suggestions(self):
        err = NotFoundError()
        # NotFoundError doesn't override suggestions property, should return []
        suggestions = err.suggestions
        assert isinstance(suggestions, list)

    def test_validation_error_suggestions(self):
        err = ValidationError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("describe" in s.lower() for s in suggestions)

    def test_server_error_suggestions(self):
        err = ServerError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("retry" in s.lower() for s in suggestions)

    def test_network_error_suggestions(self):
        err = NetworkError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("connection" in s.lower() or "internet" in s.lower() for s in suggestions)

    def test_timeout_error_suggestions(self):
        err = TimeoutError()
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("timeout" in s.lower() for s in suggestions)


class TestAPIErrorToDictMethod:
    """Test to_dict() method for API errors."""

    def test_authentication_error_to_dict(self):
        err = AuthenticationError("custom message")
        result = err.to_dict()
        assert result["code"] == "AUTH_FAILED"
        assert result["message"] == "custom message"
        assert result["retryable"] is False
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0

    def test_rate_limit_error_to_dict(self):
        err = RateLimitError()
        result = err.to_dict()
        assert result["code"] == "RATE_LIMIT"
        assert result["retryable"] is True
        assert "suggestions" in result

    def test_validation_error_to_dict(self):
        errors = [
            {"loc": ["body", "username"], "msg": "field required"},
            {"loc": ["body", "age"], "msg": "must be integer"},
        ]
        err = ValidationError(errors=errors)
        result = err.to_dict()
        assert result["code"] == "VALIDATION_ERROR"
        assert result["retryable"] is False
        assert "suggestions" in result
        assert "body.username" in result["message"]

    def test_server_error_to_dict(self):
        err = ServerError(status_code=503)
        result = err.to_dict()
        assert result["code"] == "SERVER_ERROR"
        assert result["retryable"] is True
        assert "503" in result["message"]

    def test_network_error_to_dict(self):
        original = ConnectionError("connection refused")
        err = NetworkError(original_error=original)
        result = err.to_dict()
        assert result["code"] == "NETWORK_ERROR"
        assert result["retryable"] is True

    def test_timeout_error_to_dict(self):
        err = TimeoutError(timeout=30)
        result = err.to_dict()
        assert result["code"] == "TIMEOUT"
        assert result["retryable"] is True
        assert "30" in result["message"]


class TestDatasetErrorCodes:
    """Test error codes for dataset exception classes."""

    def test_dataset_error_code(self):
        err = DatasetError("test message")
        assert err.error_code == "DATASET_ERROR"
        assert err.exit_code == EXIT_ERROR  # Inherits from AnysiteError
        assert err.retryable is False

    def test_circular_dependency_error_code(self):
        err = CircularDependencyError(["a", "b", "c", "a"])
        assert err.error_code == "CIRCULAR_DEPENDENCY"
        assert err.exit_code == EXIT_ERROR
        assert err.retryable is False
        assert "a -> b -> c -> a" in str(err)

    def test_source_not_found_error_code(self):
        err = SourceNotFoundError("missing_source", "dependent_source")
        assert err.error_code == "SOURCE_NOT_FOUND"
        assert err.exit_code == EXIT_ERROR
        assert err.retryable is False
        assert "missing_source" in str(err)
        assert "dependent_source" in str(err)


class TestLLMErrorCodes:
    """Test error codes for LLM exception classes."""

    def test_llm_error_code(self):
        err = LLMError("test message")
        assert err.error_code == "LLM_ERROR"
        assert err.exit_code == EXIT_ERROR  # Inherits from AnysiteError
        assert err.retryable is False

    def test_provider_error_code(self):
        err = ProviderError("provider failed", status_code=500)
        assert err.error_code == "LLM_PROVIDER_ERROR"
        assert err.retryable is True  # ProviderError is retryable
        assert err.status_code == 500

    def test_config_error_code(self):
        err = ConfigError("missing config")
        assert err.error_code == "CONFIG_ERROR"
        assert err.retryable is False
        suggestions = err.suggestions
        assert len(suggestions) > 0
        assert any("llm setup" in s.lower() for s in suggestions)

    def test_prompt_error_code(self):
        err = PromptError("invalid prompt template")
        assert err.error_code == "PROMPT_ERROR"
        assert err.retryable is False


class TestErrorCodeInheritance:
    """Test that error codes are properly inherited and can be overridden."""

    def test_dataset_errors_inherit_from_anysite_error(self):
        err = DatasetError("test")
        assert isinstance(err, AnysiteError)
        assert hasattr(err, "error_code")
        assert hasattr(err, "exit_code")
        assert hasattr(err, "retryable")

    def test_llm_errors_inherit_from_anysite_error(self):
        err = LLMError("test")
        assert isinstance(err, AnysiteError)
        assert hasattr(err, "error_code")
        assert hasattr(err, "exit_code")
        assert hasattr(err, "retryable")

    def test_error_code_override(self):
        """Test that subclasses can override error_code."""
        base_err = LLMError("base")
        provider_err = ProviderError("provider")

        assert base_err.error_code == "LLM_ERROR"
        assert provider_err.error_code == "LLM_PROVIDER_ERROR"
        assert base_err.error_code != provider_err.error_code

    def test_retryable_override(self):
        """Test that subclasses can override retryable."""
        base_err = LLMError("base")
        provider_err = ProviderError("provider")

        assert base_err.retryable is False
        assert provider_err.retryable is True


class TestExitCodeConstants:
    """Test that exit codes match expected values."""

    def test_exit_code_values(self):
        """Verify exit code constant values."""
        assert EXIT_ERROR == 1
        assert EXIT_USAGE == 2
        assert EXIT_AUTH == 3
        assert EXIT_NOT_FOUND == 4
        assert EXIT_NETWORK == 5

    def test_api_errors_use_correct_exit_codes(self):
        """Verify API errors map to correct exit codes."""
        assert AuthenticationError("").exit_code == 3
        assert ValidationError("").exit_code == 2
        assert NotFoundError().exit_code == 4
        assert RateLimitError().exit_code == 5
        assert NetworkError().exit_code == 5
        assert TimeoutError().exit_code == 5
        assert ServerError().exit_code == 1
