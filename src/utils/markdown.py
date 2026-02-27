"""Markdown formatting helpers for wiki generation."""


class MarkdownHelper:
    """Utility class for generating GitHub-flavored Markdown."""

    @staticmethod
    def heading(text: str, level: int = 1) -> str:
        level = max(1, min(6, level))
        return f"{'#' * level} {text}"

    @staticmethod
    def table(headers: list[str], rows: list[list[str]], alignments: list[str] | None = None) -> str:
        """Generate a Markdown table.

        Args:
            headers: Column header names.
            rows: List of row data (each row is a list of cell strings).
            alignments: Optional list of 'left', 'center', or 'right' per column.
        """
        if not headers:
            return ""

        # Escape pipe characters in all cells
        safe_headers = [MarkdownHelper.escape_pipes(h) for h in headers]
        safe_rows = [
            [MarkdownHelper.escape_pipes(str(cell)) for cell in row]
            for row in rows
        ]

        # Build separator
        if alignments is None:
            alignments = ["left"] * len(headers)

        separators = []
        for align in alignments:
            if align == "right":
                separators.append("---:")
            elif align == "center":
                separators.append(":---:")
            else:
                separators.append("---")

        lines = [
            "| " + " | ".join(safe_headers) + " |",
            "| " + " | ".join(separators) + " |",
        ]
        for row in safe_rows:
            # Pad row if shorter than headers
            padded = row + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(padded[:len(headers)]) + " |")

        return "\n".join(lines)

    @staticmethod
    def code_block(code: str, language: str = "", platform: str = "github") -> str:
        # Azure DevOps Wiki uses ::: mermaid / ::: syntax for diagrams
        if language == "mermaid" and platform == "azure_devops":
            return f"::: mermaid\n{code}\n:::"
        return f"```{language}\n{code}\n```"

    @staticmethod
    def collapsible(summary: str, content: str) -> str:
        return f"<details>\n<summary>{summary}</summary>\n\n{content}\n\n</details>"

    @staticmethod
    def link(text: str, url: str) -> str:
        return f"[{text}]({url})"

    @staticmethod
    def escape_pipes(text: str) -> str:
        """Escape pipe characters for use inside Markdown table cells."""
        if text is None:
            return ""
        return str(text).replace("|", "\\|")

