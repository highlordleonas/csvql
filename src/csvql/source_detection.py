"""Deterministic source selection from requests, descriptors, and bounded evidence."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import cast

from csvql.exceptions import ConfigurationFailure, ConfigurationFinding
from csvql.operation import OperationCancelled, OperationContext
from csvql.source import (
    AmbiguousSource,
    DetectionResult,
    DiagnosticCode,
    DiagnosticEvidence,
    DiagnosticStage,
    FrozenJSONArray,
    FrozenJSONObject,
    FrozenJSONValue,
    InvalidSource,
    RequiredAction,
    SelectedSource,
    SelectionReason,
    SourceDiagnostic,
    SourceRequest,
    UnknownSource,
    UnsupportedSource,
)
from csvql.source_identifiers import (
    AggregateIdentificationBudget,
    IdentificationEvidence,
    IdentificationLimits,
    IdentificationStatus,
    IdentifierTable,
)
from csvql.source_registry import DescriptorRegistry, DescriptorView

_INCOMPLETE_STATUSES = {
    IdentificationStatus.INDETERMINATE,
    IdentificationStatus.BUDGET_EXHAUSTED,
}


class SourceDetectionService:
    """Apply source-type precedence without importing or constructing adapters."""

    def __init__(
        self,
        registry: DescriptorRegistry,
        identifiers: IdentifierTable,
        *,
        limits: IdentificationLimits | None = None,
    ) -> None:
        self._registry = registry
        self._identifiers = identifiers
        self._limits = limits or IdentificationLimits()
        expected_identifiers = {
            descriptor.provider_key: descriptor.identifier.identifier_key
            for descriptor in registry.descriptors
            if descriptor.identifier is not None
        }
        actual_identifiers = {
            provider_key: identifiers.identifier(provider_key).identifier_key
            for provider_key in identifiers.provider_keys
        }
        findings = [
            ConfigurationFinding(
                code="missing_identifier_implementation",
                subject=provider_key,
                detail="Descriptor identifier has no implementation.",
            )
            for provider_key in sorted(set(expected_identifiers) - set(actual_identifiers))
        ]
        findings.extend(
            ConfigurationFinding(
                code="orphan_identifier_implementation",
                subject=provider_key,
                detail="Identifier implementation has no descriptor registration.",
            )
            for provider_key in sorted(set(actual_identifiers) - set(expected_identifiers))
        )
        findings.extend(
            ConfigurationFinding(
                code="identifier_key_mismatch",
                subject=provider_key,
                detail="Descriptor and implementation identifier keys do not match.",
            )
            for provider_key in sorted(set(expected_identifiers) & set(actual_identifiers))
            if expected_identifiers[provider_key] != actual_identifiers[provider_key]
        )
        if findings:
            raise ConfigurationFailure(tuple(findings))

    def detect(
        self,
        request: SourceRequest,
        *,
        operation: OperationContext | None = None,
    ) -> DetectionResult:
        """Return a selected or diagnostic outcome using authoritative precedence."""

        if operation is not None:
            operation.checkpoint()

        explicit_descriptor = None
        if request.explicit_type is not None:
            explicit_descriptor = self._registry.resolve_type(request.explicit_type)
            if explicit_descriptor is None:
                action = RequiredAction(
                    "choose_supported_type",
                    self._registry.provider_keys,
                )
                return UnsupportedSource(
                    request=request,
                    diagnostic=_diagnostic(
                        request,
                        DiagnosticCode.SOURCE_TYPE_UNKNOWN,
                        "The explicit source type is not registered.",
                        action,
                        evidence=(
                            DiagnosticEvidence(
                                "",
                                "explicit_type",
                                request.explicit_type.casefold(),
                            ),
                        ),
                    ),
                    unsupported_value=request.explicit_type,
                    required_action=action,
                )

        locator = _local_locator(request)
        try:
            locator_stat = locator.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return _invalid_locator(
                request,
                "locator_missing",
                "The source locator does not exist.",
            )
        except OSError:
            return _invalid_locator(
                request,
                "locator_observation_failed",
                "The source locator could not be observed safely.",
            )
        if operation is not None:
            operation.checkpoint()

        if stat.S_ISLNK(locator_stat.st_mode):
            return _invalid_locator(
                request,
                "symlink_not_followed",
                "Symbolic-link locators are not followed during detection.",
            )
        is_directory = stat.S_ISDIR(locator_stat.st_mode)
        is_file = stat.S_ISREG(locator_stat.st_mode)
        if not is_directory and not is_file:
            return _invalid_locator(
                request,
                "unsupported_filesystem_shape",
                "The source locator must be a regular file or supported directory.",
            )

        if is_directory and explicit_descriptor is None:
            candidates = tuple(
                descriptor.provider_key
                for descriptor in self._registry.descriptors
                if "directory" in descriptor.locator_shapes
            )
            action = RequiredAction("specify_type", candidates)
            return AmbiguousSource(
                request=request,
                diagnostic=_diagnostic(
                    request,
                    DiagnosticCode.SOURCE_AMBIGUOUS,
                    "Directories require an explicit source type.",
                    action,
                    evidence=(DiagnosticEvidence("", "locator_shape", "directory"),),
                ),
                candidates=candidates,
                required_action=action,
            )

        if explicit_descriptor is not None:
            return self._select(
                request,
                explicit_descriptor,
                shape="directory" if is_directory else "file",
                selection_reason="explicit_type",
                extension=None,
            )

        if is_file:
            extension_match = self._registry.match_extension(request.locator)
            if extension_match is not None:
                descriptor, extension = extension_match
                return self._select(
                    request,
                    descriptor,
                    shape="file",
                    selection_reason="extension",
                    extension=extension,
                )
            unsupported_hint = self._registry.match_unsupported_extension(request.locator)
            if unsupported_hint is not None:
                action = RequiredAction("convert_or_choose_type")
                code = (
                    DiagnosticCode.SOURCE_UNSUPPORTED_EXCEL_BINARY
                    if unsupported_hint.diagnostic_code
                    == DiagnosticCode.SOURCE_UNSUPPORTED_EXCEL_BINARY.value
                    else DiagnosticCode.SOURCE_UNSUPPORTED
                )
                return UnsupportedSource(
                    request=request,
                    diagnostic=_diagnostic(
                        request,
                        code,
                        unsupported_hint.guidance,
                        action,
                        evidence=(
                            DiagnosticEvidence(
                                "",
                                "unsupported_extension",
                                unsupported_hint.extension,
                            ),
                        ),
                    ),
                    unsupported_value=unsupported_hint.extension,
                    required_action=action,
                )

        return self._identify(request, locator, operation=operation)

    def _select(
        self,
        request: SourceRequest,
        descriptor: DescriptorView,
        *,
        shape: str,
        selection_reason: SelectionReason,
        extension: str | None,
    ) -> DetectionResult:
        if shape not in descriptor.locator_shapes:
            return _invalid_locator(
                request,
                f"{shape}_not_supported",
                f"The selected source type does not accept a {shape} locator.",
            )
        options_or_invalid = _validate_and_default_options(request, descriptor)
        if isinstance(options_or_invalid, InvalidSource):
            return options_or_invalid
        return SelectedSource(
            request=request,
            provider_key=descriptor.provider_key,
            source_kind=descriptor.source_kind,
            descriptor=descriptor,
            selection_reason=selection_reason,
            extension_evidence=extension,
            options=options_or_invalid,
        )

    def _identify(
        self,
        request: SourceRequest,
        locator: Path,
        *,
        operation: OperationContext | None,
    ) -> DetectionResult:
        budget = AggregateIdentificationBudget(self._limits, operation=operation)
        observed: list[IdentificationEvidence] = []
        incomplete_providers: set[str] = set()
        recognized_providers: set[str] = set()
        cause_classifications: set[str] = set()

        descriptors = tuple(
            descriptor
            for descriptor in self._registry.descriptors
            if descriptor.identifier is not None
        )
        for index, descriptor in enumerate(descriptors):
            if operation is not None:
                operation.checkpoint()
            if budget.bytes_read >= self._limits.aggregate_bytes:
                for skipped in descriptors[index:]:
                    observed.append(
                        IdentificationEvidence(
                            provider_key=skipped.provider_key,
                            status=IdentificationStatus.BUDGET_EXHAUSTED,
                            evidence_kind="identification_budget",
                            stable_detail="not_evaluated",
                            bytes_read=0,
                        )
                    )
                    incomplete_providers.add(skipped.provider_key)
                break
            identifier = self._identifiers.identifier(descriptor.provider_key)
            try:
                evidence = identifier.identify(
                    locator,
                    budget.for_identifier(descriptor.provider_key),
                )
            except OperationCancelled:
                raise
            except Exception:
                evidence = IdentificationEvidence(
                    provider_key=descriptor.provider_key,
                    status=IdentificationStatus.INDETERMINATE,
                    evidence_kind="identifier_error",
                    stable_detail="identifier_error",
                    bytes_read=0,
                    cause_classification="identifier_error",
                )
            observed.append(evidence)
            if evidence.status is IdentificationStatus.RECOGNIZED:
                recognized_providers.add(descriptor.provider_key)
            elif evidence.status in _INCOMPLETE_STATUSES:
                incomplete_providers.add(descriptor.provider_key)
            if evidence.cause_classification is not None:
                cause_classifications.add(evidence.cause_classification)

        diagnostic_evidence = tuple(
            DiagnosticEvidence(
                item.provider_key,
                item.evidence_kind,
                item.stable_detail,
            )
            for item in observed
        )
        candidates = tuple(sorted(recognized_providers | incomplete_providers))
        if candidates:
            action = RequiredAction("specify_type", candidates)
            return AmbiguousSource(
                request=request,
                diagnostic=_diagnostic(
                    request,
                    DiagnosticCode.SOURCE_AMBIGUOUS,
                    "Bounded identification cannot select a source type automatically.",
                    action,
                    evidence=diagnostic_evidence,
                    cause_classifications=tuple(cause_classifications),
                ),
                candidates=candidates,
                required_action=action,
            )

        action = RequiredAction("specify_type_or_extension", self._registry.provider_keys)
        return UnknownSource(
            request=request,
            diagnostic=_diagnostic(
                request,
                DiagnosticCode.SOURCE_UNKNOWN,
                "No registered source type recognized the bounded evidence.",
                action,
                evidence=diagnostic_evidence,
            ),
            required_action=action,
        )


def _local_locator(request: SourceRequest) -> Path:
    locator = Path(request.locator)
    if not locator.is_absolute():
        if request.anchor is None:
            return Path(os.path.abspath(os.path.normpath(os.fspath(locator))))
        locator = request.anchor / locator
    return Path(os.path.abspath(os.path.normpath(os.fspath(locator))))


def _invalid_locator(
    request: SourceRequest,
    detail: str,
    message: str,
) -> InvalidSource:
    action = RequiredAction("correct_locator")
    return InvalidSource(
        request=request,
        diagnostic=_diagnostic(
            request,
            DiagnosticCode.SOURCE_LOCATOR_SHAPE_INVALID,
            message,
            action,
            evidence=(DiagnosticEvidence("", "locator_shape", detail),),
        ),
        required_action=action,
    )


def _invalid_options(
    request: SourceRequest,
    evidence: tuple[DiagnosticEvidence, ...],
) -> InvalidSource:
    action = RequiredAction("correct_options")
    return InvalidSource(
        request=request,
        diagnostic=_diagnostic(
            request,
            DiagnosticCode.SOURCE_REQUEST_INVALID,
            "Source options do not match the selected descriptor.",
            action,
            evidence=evidence,
        ),
        required_action=action,
    )


def _validate_and_default_options(
    request: SourceRequest,
    descriptor: DescriptorView,
) -> tuple[tuple[str, FrozenJSONValue], ...] | InvalidSource:
    definitions = {definition.key: definition for definition in descriptor.options}
    requested = dict(request.options)
    evidence: list[DiagnosticEvidence] = []
    for key, value in request.options:
        definition = definitions.get(key)
        if definition is None:
            evidence.append(
                DiagnosticEvidence(
                    descriptor.provider_key,
                    "unknown_option",
                    key,
                )
            )
            continue
        if not _matches_value_kind(value, definition.value_kind):
            evidence.append(
                DiagnosticEvidence(
                    descriptor.provider_key,
                    "option_kind",
                    key,
                )
            )
    for definition in descriptor.options:
        if definition.required and definition.key not in requested:
            evidence.append(
                DiagnosticEvidence(
                    descriptor.provider_key,
                    "required_option",
                    definition.key,
                )
            )
    if evidence:
        return _invalid_options(request, tuple(evidence))

    defaulted = dict(request.options)
    for definition in descriptor.options:
        if definition.key not in defaulted and definition.has_default:
            defaulted[definition.key] = cast(FrozenJSONValue, definition.default)
    return tuple(sorted(defaulted.items()))


def _matches_value_kind(value: FrozenJSONValue, value_kind: str) -> bool:
    if value_kind == "string":
        return isinstance(value, str)
    if value_kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_kind == "boolean":
        return isinstance(value, bool)
    if value_kind == "object":
        return isinstance(value, FrozenJSONObject)
    if value_kind == "array":
        return isinstance(value, FrozenJSONArray)
    return False


def _diagnostic(
    request: SourceRequest,
    code: DiagnosticCode,
    message: str,
    required_action: RequiredAction,
    *,
    evidence: tuple[DiagnosticEvidence, ...] = (),
    cause_classifications: tuple[str, ...] = (),
) -> SourceDiagnostic:
    return SourceDiagnostic(
        code=code,
        stage=DiagnosticStage.DETECTION,
        message=message,
        safe_source_reference=request.safe_source_reference,
        evidence=evidence,
        required_action=required_action,
        cause_classifications=cause_classifications,
    )
