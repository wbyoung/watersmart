"""WaterSmart client to connect & scrape data."""

from __future__ import annotations

from collections.abc import Callable
import datetime as dt
import functools
import re
from typing import Any, TypedDict, cast

import aiohttp
from bs4 import BeautifulSoup, PageElement

# Account number format will vary between municipality, so
# match on a string of non-whitespace characters.
ACCOUNT_NUMBER_RE = re.compile(r"^\S+$")


def _authenticated[F: Callable[..., Any], ReturnT](func: F) -> F:
    @functools.wraps(func)
    async def _pre_authenticate(
        self: WaterSmartClient,
        *args,  # noqa: ANN002
        **kwargs,  # noqa: ANN003
    ) -> ReturnT:
        await self._authenticate_if_needed()
        return cast("ReturnT", await func(self, *args, **kwargs))

    return cast("F", _pre_authenticate)


class AuthenticationError(Exception):
    """Authentication Error."""

    def __init__(self, errors: list[str] | None = None) -> None:
        """Initialize."""
        self._errors = errors


class InvalidAccountNumberError(Exception):
    """Invalid account number Error."""


class ScrapeError(Exception):
    """Scrape Error."""


class UsageHistoryPayload(TypedDict):
    """UsageHistoryPayload class."""

    data: UsageHistory


class UsageHistory(TypedDict):
    """UsageHistory class."""

    series: list[UsageRecord]


class UsageRecord(TypedDict):
    """UsageRecord class."""

    read_datetime: int
    gallons: float | None
    leak_gallons: int | None
    flags: None


class WaterSmartClient:
    """WaterSmart Client."""

    def __init__(
        self,
        hostname: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession = None,
    ) -> None:
        """Initialize."""
        self._hostname = hostname
        self._username = username
        self._password = password
        self._session = session or aiohttp.ClientSession()
        self._account_number: str | None = None
        self._authenticated_at: dt.datetime | None = None

    @_authenticated
    async def async_get_account_number(self) -> str | None:
        """Authenticate the client.

        Returns:
            The account number.
        """

        return self._account_number

    @_authenticated
    async def async_get_hourly_data(self) -> list[UsageRecord]:
        """Get hourly water usage data.

        Returns:
            The objects in the response data.
        """

        session = self._session
        hostname = self._hostname
        response = await session.get(
            f"https://{hostname}.watersmart.com/index.php/rest/v1/Chart/RealTimeChart"
        )
        response_json: UsageHistoryPayload = await response.json()

        return response_json["data"]["series"]

    async def _authenticate_if_needed(self) -> None:
        if not self._authenticated_at or self._authenticated_at < dt.datetime.now(
            tz=dt.UTC
        ) - dt.timedelta(minutes=10):
            await self._authenticate()
        self._authenticated_at = dt.datetime.now(tz=dt.UTC)

    async def _authenticate(self) -> None:
        session = self._session
        hostname = self._hostname
        login_response = await session.post(
            f"https://{hostname}.watersmart.com/index.php/welcome/login?forceEmail=1",
            data={
                "token": "",
                "email": self._username,
                "password": self._password,
            },
        )
        login_response_text = await login_response.text()
        soup = BeautifulSoup(login_response_text, "html.parser")

        login_refresh_token_node = soup.find("input", {"name": "loginRefreshToken"})
        login_refresh_token = (
            login_refresh_token_node.get("value", "")
            if login_refresh_token_node
            else None
        )

        if login_refresh_token:
            login_response = await session.post(
                f"https://{hostname}.watersmart.com/index.php/welcome/login?forceEmail=1",
                data={
                    "token": "",
                    "loginRefreshToken": login_refresh_token,
                    "email": self._username,
                    "password": self._password,
                },
            )
            login_response_text = await login_response.text()
            soup = BeautifulSoup(login_response_text, "html.parser")

        errors = [error.text.strip() for error in soup.select(".error-message")]
        errors = [error for error in errors if error]

        if len(errors):
            raise AuthenticationError(errors)

        account = _assert_node(
            soup.find(id="account-navigation"), "Missing #account-navigation"
        )
        account_number_title = _assert_node(
            account.find(lambda node: node.get_text(strip=True) == "Account Number"),
            "Missing tag with string content `Account Number` under #account-navigation",
        )
        account_section = account_number_title.parent
        account_number_title.extract()

        account_number = account_section.text.strip()

        if not ACCOUNT_NUMBER_RE.match(account_number):
            self._account_number = None
            raise InvalidAccountNumberError("invalid account number: " + account_number)

        self._account_number = account_number


def _assert_node(node: PageElement, message: str) -> PageElement:
    if not node:
        raise ScrapeError(message)
    return node
