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


class MeterInfo(TypedDict):
    """MeterInfo class."""

    meter_id: str
    name: str
    account_number: str
    user_id: str
    residence_id: str


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
        self._meters: list[MeterInfo] = []
        self._current_meter_id: str | None = None

    @_authenticated
    async def async_get_account_number(self) -> str | None:
        """Authenticate the client.

        Returns:
            The account number.
        """

        return self._account_number

    @_authenticated
    async def async_get_available_meters(self) -> list[MeterInfo]:
        """Get available meters for this account.

        Returns:
            List of available meters.
        """
        return self._meters

    async def async_switch_meter(self, meter_id: str) -> None:
        """Switch to a specific meter.

        Args:
            meter_id: The meter ID to switch to.

        Raises:
            ValueError: If meter_id is not found.
        """
        meter = next((m for m in self._meters if m["meter_id"] == meter_id), None)
        if not meter:
            raise ValueError(f"Meter {meter_id} not found")

        session = self._session
        hostname = self._hostname
        await session.get(
            f"https://{hostname}.watersmart.com/index.php/userPicker/pick",
            params={
                "userID": meter["user_id"],
                "residenceID": meter["residence_id"],
                "combined": "0",
                "returnUrlOverride": "",
            },
        )
        self._current_meter_id = meter_id

    @_authenticated
    async def async_get_hourly_data(self, meter_id: str | None = None) -> list[UsageRecord]:
        """Get hourly water usage data.

        Args:
            meter_id: Optional meter ID to get data for. If not provided,
                     uses the currently active meter.

        Returns:
            The objects in the response data.
        """
        if meter_id and meter_id != self._current_meter_id:
            await self.async_switch_meter(meter_id)

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

        # Extract account number - supports two HTML formats
        account_number = self._extract_account_number(soup)
        if not ACCOUNT_NUMBER_RE.match(account_number):
            self._account_number = None
            raise InvalidAccountNumberError("invalid account number: " + account_number)

        self._account_number = account_number

        # Extract available meters
        self._meters = self._extract_meters(soup)

    def _extract_account_number(self, soup: BeautifulSoup) -> str:
        """Extract account number from HTML.

        Supports two formats:
        1. Standard format with #account-navigation
        2. Alternative format with div.account (hptx style)

        Returns:
            The account number.

        Raises:
            ScrapeError: If account number cannot be extracted.
        """
        # Try standard format first
        account = soup.find(id="account-navigation")
        if account:
            account_number_title = account.find(
                lambda node: node.get_text(strip=True) == "Account Number"
            )
            if account_number_title:
                account_section = account_number_title.parent
                account_number_title.extract()
                return account_section.text.strip()

        # Try alternative format (hptx style)
        account_divs = soup.find_all("div", class_="account")
        for div in account_divs:
            text = div.get_text(strip=True)
            # Skip the "X Accounts" text
            if "Account" in text:
                continue
            # Match account number patterns (flexible format)
            if re.match(r"^\S+$", text) and not text.isdigit():
                return text

        raise ScrapeError("Could not extract account number from page")

    def _extract_meters(self, soup: BeautifulSoup) -> list[MeterInfo]:
        """Extract available meters from HTML.

        Returns:
            List of available meters.
        """
        meters: list[MeterInfo] = []

        # Look for userPicker links (multi-meter format)
        picker_links = soup.find_all("a", href=re.compile(r"userPicker/pick"))

        for link in picker_links:
            href = link.get("href", "")

            # Skip combined summary
            if "combined=1" in href or "combined=0" not in href:
                continue

            # Extract userID and residenceID
            user_id_match = re.search(r"userID=(\d+)", href)
            residence_id_match = re.search(r"residenceID=(\d+)", href)

            if user_id_match and residence_id_match:
                user_id = user_id_match.group(1)
                residence_id = residence_id_match.group(1)

                # Get meter name and account number
                inline_div = link.find("div", class_="inline")
                if inline_div:
                    name_h3 = inline_div.find("h3")
                    account_div = inline_div.find("div", class_="account")

                    name = name_h3.get_text(strip=True) if name_h3 else "Unknown"
                    account = account_div.get_text(strip=True) if account_div else self._account_number or "Unknown"

                    # Create a unique meter_id from user_id and residence_id
                    meter_id = f"{user_id}_{residence_id}"

                    meter: MeterInfo = {
                        "meter_id": meter_id,
                        "name": name,
                        "account_number": account,
                        "user_id": user_id,
                        "residence_id": residence_id,
                    }
                    meters.append(meter)

        # If no meters found, create a single default meter (backward compatibility)
        if not meters:
            meters.append({
                "meter_id": "default",
                "name": f"{self._hostname}",
                "account_number": self._account_number or "Unknown",
                "user_id": "",
                "residence_id": "",
            })

        return meters


def _assert_node(node: PageElement, message: str) -> PageElement:
    if not node:
        raise ScrapeError(message)
    return node
