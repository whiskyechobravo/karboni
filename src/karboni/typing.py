from collections.abc import Callable
from typing import Annotated, Any, TypeVar, get_args, get_type_hints

Numeric = TypeVar("Numeric", int, float)
VersionType = Annotated[int, "min=0"]
JSONType = None | bool | int | float | str | list["JSONType"] | dict[str, "JSONType"]


class Range:
    def __init__(self, min_val: Numeric | None = None, max_val: Numeric | None = None):
        self.min = min_val  # type: ignore[var-annotated]
        self.max = max_val  # type: ignore[var-annotated]

    def validate(self, value: Numeric, param_name: str = "Value") -> None:
        """
        Validate a given numeric value against the defined range.

        Args:
            value: The numeric value to validate.
            param_name: The name of the parameter being validated.

        Raises:
            ValueError if the value is out of bounds.
        """
        if self.min is not None and value < self.min:
            msg = f"{param_name} ({value}) must be at least {self.min}."
            raise ValueError(msg)
        if self.max is not None and value > self.max:
            msg = f"{param_name} ({value}) must be at most {self.max}."
            raise ValueError(msg)


def validate_range_annotations(func: Callable[..., Any], **kwargs: Any) -> None:
    """
    Validate function arguments with Range annotations against their defined ranges.

    Args:
        func: The function whose arguments should be validated.
        kwargs: Keyword arguments to validate.

    Raises:
        ValueError if a value is out of bounds.
    """
    hints = get_type_hints(func, include_extras=True)
    for param_name, value in kwargs.items():
        if param_name in hints:
            args = get_args(hints[param_name])
            for arg in args:
                if isinstance(arg, Range):
                    arg.validate(value, param_name)
