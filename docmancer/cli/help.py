from __future__ import annotations

import inspect
import textwrap

import click
from docmancer.cli.ui import BANNER_COLOR, BANNER_LINES, TAGLINE, color_enabled, style


TERM_WIDTH = 100
HELP_CONTEXT_SETTINGS = {
    "help_option_names": ["--help"],
    "max_content_width": TERM_WIDTH,
    "terminal_width": TERM_WIDTH,
}


def format_examples(*lines: str) -> str:
    return "Examples:\n" + "\n".join(f"  {line}" for line in lines)


class _FormattedHelpMixin:
    _term_width = 20
    _desc_start = 22
    _rule_width = TERM_WIDTH

    def _color_enabled(self) -> bool:
        return color_enabled()

    def _style(self, ctx: click.Context, text: str, **styles: str | bool) -> str:
        return style(text, **styles)

    def _rule(self, ctx: click.Context, char: str = "─") -> str:
        text = char * self._rule_width
        if self._color_enabled():
            return click.style(text, fg="bright_black")
        return text

    def _write_banner(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(f"{self._rule(ctx)}\n")
        for line in BANNER_LINES:
            formatter.write(f"{self._style(ctx, line, fg=BANNER_COLOR, bold=True)}\n")
        formatter.write(f"{self._style(ctx, TAGLINE, fg='bright_black', italic=True)}\n")
        formatter.write(f"{self._rule(ctx)}\n")

    def _write_section(self, ctx: click.Context, formatter: click.HelpFormatter, heading: str) -> None:
        formatter.write_paragraph()
        label = f"◆ {heading}"
        formatter.write(f"{self._style(ctx, label, fg='cyan', bold=True)}\n")

    def _write_definition_rows(
        self,
        ctx: click.Context,
        formatter: click.HelpFormatter,
        rows: list[tuple[str, str]],
    ) -> None:
        description_width = max(20, formatter.width - self._desc_start)
        for term, description in rows:
            wrapped = textwrap.wrap(
                description,
                width=description_width,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]
            styled_term = self._style(ctx, term.ljust(self._term_width), fg="bright_green", bold=True)
            formatter.write(f"  {styled_term}{wrapped[0]}\n")
            for line in wrapped[1:]:
                formatter.write(" " * self._desc_start + f"{line}\n")

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if self.help:
            self._write_section(ctx, formatter, "Description")
            formatter.write_text(self._style(ctx, inspect.cleandoc(self.help), fg="white"))

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        self._write_banner(ctx, formatter)
        formatter.write_paragraph()
        self.format_usage(ctx, formatter)
        self.format_help_text(ctx, formatter)
        self.format_options(ctx, formatter)
        if isinstance(self, click.Group):
            self.format_commands(ctx, formatter)
        self.format_epilog(ctx, formatter)

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        records = []
        for param in self.get_params(ctx):
            record = param.get_help_record(ctx)
            if record is not None:
                records.append(record)

        if records:
            self._write_section(ctx, formatter, "Options")
            self._write_definition_rows(ctx, formatter, records)

    def format_epilog(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if self.epilog:
            formatter.write_paragraph()
            lines = self.epilog.rstrip().splitlines()
            if not lines:
                return
            formatter.write(f"{self._style(ctx, f'◆ {lines[0]}', fg='yellow', bold=True)}\n")
            for line in lines[1:]:
                formatter.write(f"{self._style(ctx, line, fg='bright_yellow')}\n")


class DocmancerCommand(_FormattedHelpMixin, click.Command):
    pass


class DocmancerGroup(_FormattedHelpMixin, click.Group):
    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows = []
        for subcommand in self.list_commands(ctx):
            command = self.get_command(ctx, subcommand)
            if command is None or command.hidden:
                continue
            rows.append((subcommand, command.get_short_help_str()))

        if rows:
            self._write_section(ctx, formatter, "Commands")
            self._write_definition_rows(ctx, formatter, rows)
