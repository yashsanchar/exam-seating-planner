"""Custom exceptions used across the seating package (OOP: exception hierarchy)."""


class SeatingError(Exception):
    """Base class for every error raised by this package."""


class DataFormatError(SeatingError):
    """Input data (CSV files, layouts) is missing something or malformed."""


class InsufficientCapacityError(SeatingError):
    """There are not enough usable seats for the students."""


class InfeasibleArrangementError(SeatingError):
    """No arrangement exists (or none was found) that satisfies the rule."""
