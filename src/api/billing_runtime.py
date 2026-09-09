"""Server-only Stripe test-mode configuration boundary."""

from __future__ import annotations

import os
import re
from typing import Final, Literal, Self, assert_never

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError
from stripe import StripeClient

_ENABLED_ENV: Final = "RAG_STUDIO_BILLING_ENABLED"
_API_KEY_ENV: Final = "RAG_STUDIO_STRIPE_RESTRICTED_KEY"
_WEBHOOK_SECRET_ENV: Final = "RAG_STUDIO_STRIPE_WEBHOOK_SECRET"
_PRICE_ID_ENV: Final = "RAG_STUDIO_STRIPE_PRICE_ID"
_PUBLIC_APP_URL_ENV: Final = "RAG_STUDIO_PUBLIC_APP_URL"
_PORTAL_CONFIGURATION_ENV: Final = "RAG_STUDIO_STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID"
_TEST_OBJECT_PAIRS_ENV: Final = "RAG_STUDIO_STRIPE_TEST_OBJECT_PAIRS"
_PRICE_ID_PATTERN: Final = re.compile(r"price_[A-Za-z0-9]{14,}")
_PORTAL_CONFIGURATION_PATTERN: Final = re.compile(r"bpc_[A-Za-z0-9]{14,}")
STRIPE_API_VERSION: Final = "2026-07-29.dahlia"


class _BillingFeatureFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: Literal["true", "false"]


class BillingConfiguration(BaseModel):
    """Validated values required by the server-side Stripe client and webhook."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr = Field(min_length=24)
    webhook_secret: SecretStr = Field(min_length=24)
    price_id: str = Field(pattern=r"^price_[A-Za-z0-9]{14,}$")
    public_app_url: AnyHttpUrl
    portal_configuration_id: str = Field(pattern=r"^bpc_[A-Za-z0-9]{14,}$")
    test_object_pairs: frozenset[tuple[str, str]] = Field(min_length=1, repr=False)

    @field_validator("api_key")
    @classmethod
    def validate_test_restricted_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        prefix = "rk_" + "test_"
        if not key.startswith(prefix) or not key.removeprefix(prefix).isalnum():
            raise PydanticCustomError("billing_api_key", "invalid billing API key")
        return value

    @field_validator("webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if (
            not secret.startswith("whsec_")
            or not secret.removeprefix("whsec_").isalnum()
        ):
            raise PydanticCustomError(
                "billing_webhook_secret", "invalid billing webhook secret"
            )
        return value

    @field_validator("public_app_url")
    @classmethod
    def validate_public_app_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise PydanticCustomError("billing_app_url", "invalid billing app URL")
        if value.query is not None or value.fragment is not None:
            raise PydanticCustomError("billing_app_url", "invalid billing app URL")
        if value.scheme == "http" and value.host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise PydanticCustomError("billing_app_url", "invalid billing app URL")
        return value

    @field_validator("test_object_pairs", mode="before")
    @classmethod
    def parse_test_object_pairs(cls, value: str) -> frozenset[tuple[str, str]]:
        entries = value.split(",")
        if not value or any(not entry.strip() for entry in entries):
            raise PydanticCustomError(
                "billing_test_object_pairs", "invalid billing test object pairs"
            )
        pairs: set[tuple[str, str]] = set()
        for entry in entries:
            members = tuple(member.strip() for member in entry.split("|"))
            if (
                len(members) != 2
                or _PRICE_ID_PATTERN.fullmatch(members[0]) is None
                or _PORTAL_CONFIGURATION_PATTERN.fullmatch(members[1]) is None
            ):
                raise PydanticCustomError(
                    "billing_test_object_pairs", "invalid billing test object pairs"
                )
            pairs.add((members[0], members[1]))
        return frozenset(pairs)

    @model_validator(mode="after")
    def validate_test_object_binding(self) -> Self:
        configured_pair = (self.price_id, self.portal_configuration_id)
        if configured_pair not in self.test_object_pairs:
            raise PydanticCustomError(
                "billing_test_object_binding",
                "billing object pair is outside the server test pairs",
            )
        return self


def load_billing_configuration() -> BillingConfiguration | None:
    """Load enabled Stripe values or return the fail-safe disabled state."""
    feature = _BillingFeatureFlag.model_validate(
        {"enabled": os.getenv(_ENABLED_ENV, "false").strip().lower()}
    )
    match feature.enabled:
        case "false":
            return None
        case "true":
            return BillingConfiguration.model_validate(
                {
                    "api_key": os.getenv(_API_KEY_ENV),
                    "webhook_secret": os.getenv(_WEBHOOK_SECRET_ENV),
                    "price_id": os.getenv(_PRICE_ID_ENV),
                    "public_app_url": os.getenv(_PUBLIC_APP_URL_ENV),
                    "portal_configuration_id": os.getenv(_PORTAL_CONFIGURATION_ENV),
                    "test_object_pairs": os.getenv(_TEST_OBJECT_PAIRS_ENV, ""),
                }
            )
        case unreachable:
            assert_never(unreachable)


def create_stripe_client(configuration: BillingConfiguration) -> StripeClient:
    """Create an isolated Stripe client without mutating module-level credentials."""
    return StripeClient(
        configuration.api_key.get_secret_value(),
        stripe_version=STRIPE_API_VERSION,
        max_network_retries=2,
    )
