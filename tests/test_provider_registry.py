import unittest

from mcp_autogui.provider_registry import (
    ProviderBuildContext,
    available_evidence_providers,
    create_evidence_providers,
    register_evidence_provider,
    validate_evidence_provider,
)


class FixtureEvidenceProvider:
    provider_id = "fixture-evidence"
    fact_paths = frozenset()

    def collect(self, _assertions, _snapshot):
        return ()


class ProviderRegistryTests(unittest.TestCase):
    def test_registered_extension_is_validated_and_built_without_core_changes(self):
        provider_id = "test-registry-evidence"

        def validate(config, location):
            if set(config) != {"enabled"} or not isinstance(config["enabled"], bool):
                raise ValueError(f"{location}.enabled must be true or false")

        register_evidence_provider(
            provider_id,
            validate,
            lambda config, _context: FixtureEvidenceProvider() if config["enabled"] else None,
        )
        self.assertIn(provider_id, available_evidence_providers())
        validate_evidence_provider(provider_id, {"enabled": True}, f"evidence_providers.{provider_id}")

        providers = create_evidence_providers(
            {provider_id: {"enabled": True}},
            ProviderBuildContext(store=object(), capture_observation=lambda: (b"", (1, 1), {})),
        )

        self.assertEqual([provider.provider_id for provider in providers], ["fixture-evidence"])

    def test_unknown_provider_is_rejected_before_runtime_assembly(self):
        with self.assertRaisesRegex(ValueError, "must be one of"):
            validate_evidence_provider("missing", {}, "evidence_providers.missing")

    def test_duplicate_provider_registration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already registered"):
            register_evidence_provider(
                "compositor_window", lambda _config, _location: None, lambda _config, _context: None
            )
