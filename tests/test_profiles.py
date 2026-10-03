"""Deterministic profile selection using synthetic OpenedClient objects only."""

from dataclasses import replace

import pytest

from custom_components.hoben.myhoben import OpenedClient
from custom_components.hoben.profiles import StoveProfile, select_stove_profile


@pytest.fixture
def opened() -> OpenedClient:
    """Provide parsed-field values with an entirely synthetic 32-byte GUID."""
    return OpenedClient(
        product_revision=0,
        product_type=2,
        software_minor=0,
        software_major=0,
        device_guid="A" * 32,
        application_version=0,
    )


@pytest.mark.parametrize("revision", [0, 1, 2, 255])
@pytest.mark.parametrize("major", [0, 1, 2, 255])
@pytest.mark.parametrize(("minor", "application_version"), [(0, 0), (255, 65535)])
def test_v4_has_no_revision_or_software_restrictions(
    opened: OpenedClient,
    revision: int,
    major: int,
    minor: int,
    application_version: int,
) -> None:
    """Type 5 alone selects V4, even at the parsed fields' upper boundaries."""
    assert (
        select_stove_profile(
            replace(
                opened,
                product_type=5,
                product_revision=revision,
                software_major=major,
                software_minor=minor,
                application_version=application_version,
            )
        )
        is StoveProfile.V4
    )


@pytest.mark.parametrize(
    ("product_type", "revision", "major", "expected"),
    [
        (2, 0, 0, StoveProfile.V6),
        (2, 1, 0, StoveProfile.V6),
        (2, 2, 0, StoveProfile.BOILER_V6_230),
        (3, 0, 0, StoveProfile.V6),
        (3, 0, 1, StoveProfile.V6),
    ],
)
@pytest.mark.parametrize(
    ("minor", "application_version"), [(0, 0), (5, 6), (6, 5), (255, 65535)]
)
def test_confirmed_profiles(
    opened: OpenedClient,
    product_type: int,
    revision: int,
    major: int,
    expected: StoveProfile,
    minor: int,
    application_version: int,
) -> None:
    """Confirmed V6/boiler rules add no minor or application version condition."""
    assert (
        select_stove_profile(
            replace(
                opened,
                product_type=product_type,
                product_revision=revision,
                software_major=major,
                software_minor=minor,
                application_version=application_version,
            )
        )
        is expected
    )


@pytest.mark.parametrize(
    ("product_type", "revision", "major"),
    [
        (2, 0, 1),
        (2, 1, 1),
        (2, 2, 1),
        (2, 0, 255),
        (2, 3, 0),
        (2, 255, 0),
        (3, 0, 2),
        (3, 0, 255),
        (3, 1, 2),
        (3, 2, 0),
        (3, 2, 1),
        (3, 255, 0),
        (0, 0, 0),
        (1, 0, 0),
        (4, 0, 0),
        (255, 0, 0),
    ],
)
def test_unsupported_profiles(
    opened: OpenedClient, product_type: int, revision: int, major: int
) -> None:
    """Unsupported types, revisions and majors remain explicit unknowns."""
    assert (
        select_stove_profile(
            replace(
                opened,
                product_type=product_type,
                product_revision=revision,
                software_major=major,
            )
        )
        is StoveProfile.UNKNOWN
    )


@pytest.mark.parametrize("major", [0, 1])
@pytest.mark.parametrize("minor", [0, 5, 6, 255])
@pytest.mark.parametrize("application_version", [0, 5, 6, 65535])
def test_ambiguous_version_discriminator(
    opened: OpenedClient, major: int, minor: int, application_version: int
) -> None:
    """Vary both candidate fields independently across 5/6 without guessing."""
    assert (
        select_stove_profile(
            replace(
                opened,
                product_type=3,
                product_revision=1,
                software_major=major,
                software_minor=minor,
                application_version=application_version,
            )
        )
        is StoveProfile.UNKNOWN
    )


@pytest.mark.parametrize(
    ("product_type", "revision", "major", "expected"),
    [
        (5, 255, 255, StoveProfile.V4),
        (2, 0, 0, StoveProfile.V6),
        (2, 2, 0, StoveProfile.BOILER_V6_230),
        (3, 0, 1, StoveProfile.V6),
        (3, 1, 0, StoveProfile.UNKNOWN),
        (3, 1, 1, StoveProfile.UNKNOWN),
        (255, 0, 0, StoveProfile.UNKNOWN),
    ],
)
def test_device_guid_does_not_affect_selection(
    opened: OpenedClient,
    product_type: int,
    revision: int,
    major: int,
    expected: StoveProfile,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Changing only a synthetic identifier affects neither result nor logs."""
    opened = replace(
        opened,
        product_type=product_type,
        product_revision=revision,
        software_major=major,
    )
    with caplog.at_level("DEBUG"):
        assert select_stove_profile(opened) is expected
        assert select_stove_profile(replace(opened, device_guid="B" * 32)) is expected
    assert not caplog.records


@pytest.mark.parametrize(
    "value",
    [
        None,
        5,
        "SYNTHETIC-AUTHORIZATION",
        {"device_guid": "A" * 32, "user_guid": "SYNTHETIC-USER"},
        OpenedClient,
    ],
    ids=["none", "integer", "text", "mapping", "class"],
)
def test_requires_opened_client(
    value: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Reject invalid callers with a static error and no identifier logging."""
    with caplog.at_level("DEBUG"):
        with pytest.raises(
            TypeError, match="^opened must be an OpenedClient instance$"
        ):
            select_stove_profile(value)
    assert not caplog.records
