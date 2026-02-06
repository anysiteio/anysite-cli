"""Standard exit codes for agent-friendly CLI output."""

EXIT_SUCCESS = 0
EXIT_ERROR = 1  # general / internal error
EXIT_USAGE = 2  # invalid arguments, missing params
EXIT_AUTH = 3  # authentication failed
EXIT_NOT_FOUND = 4  # resource not found
EXIT_NETWORK = 5  # network, timeout, rate-limit
