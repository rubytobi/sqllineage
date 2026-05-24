import warnings

from sqlfluff.core import (
    FluffConfig,
    Linter,
    SQLLexError,
    SQLParseError,
    dialect_readout,
)
from sqlfluff.core.parser import BaseSegment

from sqllineage.core.analyzer import LineageAnalyzer
from sqllineage.core.holders import StatementLineageHolder
from sqllineage.core.metadata_provider import MetaDataProvider
from sqllineage.core.parser.sqlfluff.extractors.base import BaseExtractor
from sqllineage.exceptions import (
    InvalidSyntaxException,
    UnsupportedStatementException,
)
from sqllineage.utils.entities import AnalyzerContext


class SqlFluffLineageAnalyzer(LineageAnalyzer):
    """SQL Statement Level Lineage Analyzer for `sqlfluff`"""

    PARSER_NAME = "sqlfluff"
    SUPPORTED_DIALECTS = list(dialect.label for dialect in dialect_readout())

    def __init__(self, file_path: str, dialect: str, silent_mode: bool = False):
        self._sqlfluff_config = FluffConfig.from_path(
            path=file_path, overrides={"dialect": dialect}
        )
        self._silent_mode = silent_mode
        self._segment_cache: dict[str, BaseSegment] = {}

    def split_tsql(self, sql: str) -> list[str]:
        """
        use sqlfluff parse to split tsql statements. This is in particular for semicolon not present cases.
        The result is cached so that later analyze method doesn't have to parse regarding single statement sql.
        """
        sqls = []
        for segment in self._list_specific_statement_segment(sql):
            self._segment_cache[segment.raw] = segment
            sqls.append(segment.raw)
        return sqls

    def preparse(self, statements: list[str]) -> None:
        """
        Parse all statements in a single Linter call, caching the resulting segments.
        This eliminates the per-statement FluffConfig deepcopy that occurs inside every
        Linter() construction, replacing N copies with one.

        Cache keys are the original input strings (not segment.raw) so that lookups in
        analyze() always hit regardless of how the caller normalises whitespace or
        semicolons.  On a segment-count mismatch the cache is left empty and analyze()
        falls back to per-statement parsing transparently.
        """
        combined = ";\n".join(s.rstrip("; \t\n") for s in statements)
        segments = self._list_specific_statement_segment(combined)
        if len(segments) == len(statements):
            for stmt, segment in zip(statements, segments):
                self._segment_cache[stmt] = segment

    def analyze(
        self, sql: str, metadata_provider: MetaDataProvider
    ) -> StatementLineageHolder:
        if sql in self._segment_cache:
            statement_segments = [self._segment_cache[sql]]
        else:
            statement_segments = self._list_specific_statement_segment(sql)
        if len(statement_segments) == 0:
            raise UnsupportedStatementException(
                f"SQLLineage cannot parse SQL:{sql}"
            )  # pragma: no cover
        else:
            statement_segment = statement_segments[0]
            holder = BaseExtractor.try_extract(
                self._sqlfluff_config.get("dialect"),
                metadata_provider,
                statement_segment,
                AnalyzerContext(),
            )
            if holder is not None:
                return StatementLineageHolder.of(holder)
            else:
                if self._silent_mode:
                    warnings.warn(
                        f"SQLLineage doesn't support analyzing statement type [{statement_segment.type}] for SQL:{sql}"
                    )
                    return StatementLineageHolder()
                else:
                    raise UnsupportedStatementException(
                        f"SQLLineage doesn't support analyzing statement type [{statement_segment.type}] for SQL:{sql}"
                    )

    def _list_specific_statement_segment(self, sql: str):
        parsed = Linter(config=self._sqlfluff_config).parse_string(sql)
        violations = [
            str(e)
            for e in parsed.violations
            if isinstance(e, (SQLLexError, SQLParseError))
        ]
        if violations:
            violation_msg = "\n".join(violations)
            raise InvalidSyntaxException(
                f"This SQL statement is unparsable, please check potential syntax error for SQL:\n"
                f"{sql}\n"
                f"{violation_msg}"
            )
        segments = []
        for top_segment in getattr(parsed.tree, "segments", []):
            match top_segment.type:
                case "statement":
                    segments.append(top_segment.segments[0])
                case "batch":
                    statements = top_segment.get_children("statement")
                    if len(statements) > 1:
                        warnings.warn(
                            "SQL statements is not split by semicolon. "
                            "SQLLineage is not guaranteed to generate correct result under this circumstances.",
                            SyntaxWarning,
                            stacklevel=2,
                        )
                    for statement in statements:
                        segments.append(statement.segments[0])
        return segments
