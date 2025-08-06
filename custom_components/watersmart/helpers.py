"""Helpers for WaterSmart integration."""

from urllib.parse import urlparse


def parse_hostname(value: str) -> tuple[str, str | None]:
    """Parse a value into hostname and domain.

    The value can be one of:
        - FQDN, i.e. myutility.bellevuewa.gov
        - URL, i.e. https://myutility.bellevuewa.gov (only https is allowed)
        - A host, i.e. bendoregon

    Returns:
        A tuple with the hostname and domain.
    """
    url = urlparse(value)

    if hostname := url.hostname:
        assert url.scheme == "https"
    else:
        hostname = value

    components = hostname.split(".", 1)
    hostname = components[0]
    domain = components[1] if len(components) == 2 else None

    return hostname, domain
